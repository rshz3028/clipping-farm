"""One FFmpeg command: archival shots cut to the narration, full frame centred over a blurred
copy of itself, ASS captions burned in, narration as the only audio (original sound muted).
Encodes with NVENC; falls back to the CPU encoder if NVENC fails."""
import subprocess

from pipeline.core.settings import ROOT
from pipeline.core.tools import NO_WINDOW, ffmpeg


def plan_clips(script, shots, narr, total, cfg):
    """Return [(source_start, length)] covering 0..total, following the script's shot list."""
    by_id = {s["i"]: s for s in shots["shots"]}
    sents = narr["sentences"]
    per_sent = {i: [x["shot"] for x in script["shots"] if x["sentence"] == i] for i in range(len(sents))}
    min_len = float(cfg.get("min_clip_seconds", 1.2))
    cursor = {}                       # how far into each shot we have already used
    clips, last_shot = [], script["shots"][0]["shot"] if script["shots"] else 0
    for i, s in enumerate(sents):
        a = 0.0 if i == 0 else s["start"]
        b = sents[i + 1]["start"] if i + 1 < len(sents) else total
        ids = per_sent[i] or [last_shot]                    # no shot given: keep the previous footage running
        n = max(1, min(len(ids), int((b - a) // min_len)))
        ids = ids[:n]
        for j, sid in enumerate(ids):
            length = (b - a) / n
            sh = by_id[sid]
            start = cursor.get(sid, sh["start"] + 0.1)
            clips.append((round(start, 3), round(length, 3)))
            cursor[sid] = start + length
            last_shot = sid
    return clips


def _graph(n_clips, w_src, h_src, total, cfg, ass_rel, fonts_rel, pb=1.0):
    W, H, fps = cfg.get("width", 1080), cfg.get("height", 1920), cfg.get("fps", 30)
    parts = [f"[{k}:v]fps={fps},scale={w_src}:{h_src},setsar=1,format=yuv420p[v{k}]" for k in range(n_clips)]
    parts.append("".join(f"[v{k}]" for k in range(n_clips)) + f"concat=n={n_clips}:v=1:a=0[cat]")
    parts.append("[cat]split[a][b]")
    parts.append(f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                 f"boxblur={cfg.get('blur', 20)}:2,eq=brightness={cfg.get('bg_brightness', -0.18)}[bg]")
    parts.append(f"[b]scale={W}:-2[fg]")
    parts.append(f"[bg][fg]overlay=0:{cfg.get('fg_y', 520)},trim=0:{total},setpts=PTS-STARTPTS,"
                 f"ass='{ass_rel}':fontsdir='{fonts_rel}',setpts=PTS/{pb}[vout]")
    parts.append(f"[{n_clips}:a]apad,atrim=0:{total},atempo={pb},loudnorm=I={cfg.get('loudness', -14)}:TP=-1.5:LRA=11,"
                 f"aresample=48000[aout]")
    return ";\n".join(parts)


def run(unit, cfg):
    script = unit.json("short/script.json")
    shots = unit.json("source/shots.json")
    narr = unit.json("short/narration.json")
    total = unit.json("short/captions.json")["total_duration"]          # before speed-up
    pb = float(cfg.get("timing", {}).get("playback_speed", 1.0))
    final = total / pb
    clips = plan_clips(script, shots, narr, total, cfg)
    w_src, h_src = shots["width"] - shots["width"] % 2, shots["height"] - shots["height"] % 2

    rel = lambda p: p.resolve().relative_to(ROOT).as_posix()      # relative paths avoid 'D:' escaping in filters
    graph_file = unit.tmp_dir() / "render_graph.txt"
    graph_file.write_text(_graph(len(clips), w_src, h_src, total, cfg, rel(unit.path("short/captions.ass")),
                                 cfg.get("fonts_dir", "MoneyPrinterTurbo/resource/fonts"), pb), encoding="utf-8")
    src = rel(unit.path("source/source.mp4"))
    out_tmp = unit.tmp_dir() / "final.mp4"
    inputs = []
    for start, length in clips:
        inputs += ["-ss", f"{start}", "-t", f"{length + 0.05}", "-i", src]
    inputs += ["-i", rel(unit.path("short/narration.wav"))]

    for enc in [cfg.get("encoder", "h264_nvenc"), cfg.get("fallback_encoder", "libx264")]:
        venc = (["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", str(cfg.get("cq", 21)), "-b:v", "0"]
                if "nvenc" in enc else ["-c:v", enc, "-preset", "medium", "-crf", str(cfg.get("crf", 20))])
        cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *inputs,
               "-filter_complex_script", rel(graph_file), "-map", "[vout]", "-map", "[aout]",
               *venc, "-pix_fmt", "yuv420p", "-r", str(cfg.get("fps", 30)),
               "-c:a", "aac", "-b:a", "192k", "-t", f"{final:.3f}", "-movflags", "+faststart", rel(out_tmp)]
        print(f"  {len(clips)} clips, {final:.1f}s at {pb}x speed, encoder {enc}")
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW)
        if r.returncode == 0:
            out_tmp.replace(unit.path("short/final.mp4"))
            return
        print(f"  {enc} failed: {r.stderr.strip()[-600:]}")
    raise RuntimeError("Rendering failed with both encoders")
