"""Edit engine: footage analysis, beat tracking, cut plan, render. Shared by make_edit.py and the
daily `edits` job. Pure functions; paths and choices come from the caller (pipeline/edits/make.py).

Footage analysis (cached in work/edits/analysis/<source_id>.json): low-res pass for shot cuts +
motion/sharpness/contrast; shots split into <= 4 s pieces; each piece checked on full-res frames and
dropped if it has a visible face (YuNet; NASA staff-likeness rule), burned-in subtitles or text
slates/posters; sky fraction is kept to favour in-flight shots.
Music: numpy beat tracker (tempo by autocorrelation, phase by onset energy, drop = biggest energy rise).
"""
import json
import subprocess
from pathlib import Path

import numpy as np

from pipeline.core.settings import ROOT, WORK
from pipeline.core.tools import NO_WINDOW, ffmpeg

EDITS = WORK / "edits"
FPS = 30
AW, AH, AFPS = 256, 144, 6          # analysis resolution / frame rate
SKIP_HEAD, SKIP_TAIL = 3.0, 30.0    # seconds; NASA B-roll starts/ends with slates and info cards


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, **kw)


# ── footage analysis ──────────────────────────────────────────────────────────
def frame_checks(im):
    """im: 960x540 BGR. text = text-line-like blobs (slates, posters); subtitle = sharp white strokes
    in the bottom-centre strip (burned-in captions); sky = fraction of blue-sky pixels."""
    import cv2
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    grad = cv2.morphologyEx(g, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)))
    _, _, st, _ = cv2.connectedComponentsWithStats(bw)
    text = sum(1 for x, y, w, h, a in st[1:] if 8 <= h <= 34 and 3 * h <= w <= 700 and a / (w * h) > 0.45)
    band = g[470:530, 160:800].astype(np.int16)
    mn = cv2.erode(band.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.int16)
    subtitle = int((((band > 190) & (mn < band - 90)).sum(1) > 12).sum())
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    sky = float(((hsv[..., 0] >= 90) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 40) & (hsv[..., 2] > 90)).mean())
    return dict(text=text, subtitle=subtitle, sky=sky)


def analyse(source_id: str) -> dict:
    cache = EDITS / "analysis" / f"{source_id}.json"
    src = EDITS / "sources" / f"{source_id}.mp4"
    if cache.exists() and cache.stat().st_mtime > src.stat().st_mtime:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("skip") == [SKIP_HEAD, SKIP_TAIL] and data.get("version") == 3:
            return data
    import cv2
    print(f"  analysing {source_id} ...", flush=True)
    raw = run([ffmpeg(), "-v", "error", "-i", str(src), "-vf", f"fps={AFPS},scale={AW}:{AH}",
               "-pix_fmt", "gray", "-f", "rawvideo", "-"]).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, AH, AW).astype(np.float32)
    n = len(fr)
    diff = np.zeros(n)
    diff[1:] = np.abs(fr[1:] - fr[:-1]).mean(axis=(1, 2))
    sharp = np.array([cv2.Laplacian(f, cv2.CV_32F).var() for f in fr])
    contrast = fr.std(axis=(1, 2))
    bright = fr.mean(axis=(1, 2))
    # shot cuts: a diff spike well above its neighbourhood
    cuts = [0]
    for i in range(1, n):
        local = np.median(diff[max(1, i - 6):i + 6])
        if diff[i] > max(18.0, 3.5 * local) and i - cuts[-1] >= 2:
            cuts.append(i)
    cuts.append(n)
    face = cv2.FaceDetectorYN_create(str(ROOT / "models/yunet/face_detection_yunet_2023mar.onnx"), "",
                                     (960, 540), 0.75)
    cap = cv2.VideoCapture(str(src))
    shots, rejected = [], {}
    lo_f, hi_f = int(SKIP_HEAD * AFPS), n - int(SKIP_TAIL * AFPS)
    for a, b in zip(cuts[:-1], cuts[1:]):
        a2, b2 = max(a + 1, lo_f), min(b - 1, hi_f)                      # keep away from the cut itself
        if (b2 - a2) / AFPS < 0.6:
            continue
        seg = slice(a2, b2)
        if bright[seg].mean() < 35 or contrast[seg].mean() < 12:
            continue                               # black/slate/flat frames
        # long shots are checked in <= 4 s pieces so one subtitle or face only removes its piece
        for p0 in range(a2, b2, 4 * AFPS):
            p1 = min(b2, p0 + 4 * AFPS)
            if (p1 - p0) / AFPS < 0.6:
                continue
            bad, sky = None, []
            for t in np.linspace(p0, p1, 3) / AFPS:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
                ok, img = cap.read()
                if not ok:
                    continue
                im = cv2.resize(img, (960, 540))
                _, det = face.detect(im)
                f = frame_checks(im)
                sky.append(f["sky"])
                if det is not None and (det[:, 3] >= 24).any():
                    bad = "face"
                elif f["subtitle"] >= 15:
                    bad = "subtitle"
                elif f["text"] >= 6 or (f["text"] >= 4 and f["sky"] < 0.25):
                    bad = "text"
                if bad:
                    break
            if bad:
                rejected[bad] = rejected.get(bad, 0) + 1
                continue
            sl = slice(p0, p1)
            shots.append(dict(parent=int(a), start=p0 / AFPS, end=p1 / AFPS,
                              motion=[round(float(x), 2) for x in diff[p0 + 1:p1]],
                              sharp=float(np.median(sharp[sl])), contrast=float(contrast[sl].mean()),
                              sky=float(np.mean(sky)) if sky else 0.0))
    cap.release()
    out = dict(source_id=source_id, frames=n, skip=[SKIP_HEAD, SKIP_TAIL], version=3, shots=shots)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), encoding="utf-8")
    print(f"    {len(cuts) - 1} cuts, {len(shots)} usable pieces; rejected: {rejected or 'none'}")
    return out


# ── music analysis ────────────────────────────────────────────────────────────
def beats(music: Path):
    sr, hop, nfft = 22050, 512, 2048
    raw = run([ffmpeg(), "-v", "error", "-i", str(music), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]).stdout
    y = np.frombuffer(raw, np.float32)
    nfr = 1 + (len(y) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(nfr)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * np.hanning(nfft), axis=1))
    logm = np.log1p(10 * mag)
    flux = np.maximum(0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0], flux])
    env = (flux - flux.mean()) / (flux.std() + 1e-9)
    rms = np.sqrt((y[idx] ** 2).mean(axis=1))
    fps_env = sr / hop
    # tempo: autocorrelation, 70-180 BPM, mild preference around 130
    ac = np.correlate(env, env, "full")[len(env) - 1:]
    best, period = -1e9, None
    for bpm in np.arange(70, 180, 0.25):
        lag = 60 * fps_env / bpm
        lo = int(lag)
        v = ac[lo] + (lag - lo) * (ac[lo + 1] - ac[lo])
        v *= np.exp(-0.5 * (np.log2(bpm / 130) / 0.9) ** 2)
        if v > best:
            best, period = v, lag
    bpm = 60 * fps_env / period
    # phase: grid position that hits the most onset energy
    k = np.arange(int((nfr - 1) / period))
    phases = np.arange(0, period, 0.5)
    scores = [env[np.clip(np.round(p + k * period).astype(int), 0, nfr - 1)].sum() for p in phases]
    phase = phases[int(np.argmax(scores))]
    bt = (phase + k * period) / fps_env
    # energy per beat; the drop = biggest rise of mean energy (8 beats after vs 8 before), on a bar line
    e = np.array([rms[int(t * fps_env):int((t + 60 / bpm) * fps_env)].mean() for t in bt])
    rise = [(e[i:i + 8].mean() - e[i - 8:i].mean(), i) for i in range(8, len(e) - 16, 4)]
    drop = max(rise)[1] if rise else 8
    return bpm, bt, drop, len(y) / sr


# ── edit plan ─────────────────────────────────────────────────────────────────
def plan(bt, drop, seconds, rng):
    """List of (music_t0, music_t1, kind) cut on beats. Tempo-aware: one cut lasts >= ~0.7 s.
    Build-up: 2 long holds before the drop. After: steady cuts, a quick double-cut closing every
    second bar, and faster cuts in the last two bars."""
    bl = float(np.median(np.diff(bt)))
    step = max(1, int(round(0.75 / bl)))                    # beats per normal cut (2 at 152 BPM)
    bar = 4
    start = max(0, drop - 4 * step)
    segs, i = [], start
    end_t = bt[start] + seconds
    while i < len(bt) - step - 1 and bt[i] < end_t:
        rel = i - drop
        if i < drop:
            j = min(i + 2 * step, drop)
            segs.append((bt[i], bt[j], "intro"))
            i = j
            continue
        j = i + step
        if rel % (2 * bar) == 2 * bar - step or bt[i] > end_t - 2 * bar * bl:
            mid = (bt[i] + bt[j]) / 2
            segs += [(bt[i], mid, "fast"), (mid, bt[j], "fast")]
        else:
            segs.append((bt[i], bt[j], "down" if rel % bar == 0 else "beat"))
        i = j
    return segs


def pick_clips(segs, shots_by_src, rng, avoid=frozenset()):
    """avoid: {(source_id, parent_shot)} used by recent edits; those are ranked lower, not banned."""
    pool = []
    for sid, shots in shots_by_src.items():
        for s in shots:
            m = np.array(s["motion"]) if s["motion"] else np.zeros(1)
            score = (np.log1p(m.mean()) + 0.35 * np.log1p(s["sharp"]) + 0.02 * s["contrast"]
                     + 2.0 * s.get("sky", 0))          # in-flight / open-sky shots first
            if (sid, s["parent"]) in avoid:
                score -= 1.5
            pool.append(dict(s, sid=sid, score=float(score) + rng.uniform(0, 0.3)))
    pool.sort(key=lambda s: -s["score"])
    skyish = [s for s in pool if s.get("sky", 0) >= 0.25]
    if len(skyish) >= 2 * len(segs):
        pool = skyish                              # enough open-sky shots: drop hangars, booths, indoor
    used, parents, clips, last_sid = set(), {}, [], None
    for t0, t1, kind in segs:
        need = (t1 - t0) + 0.1
        ok = lambda s: s["end"] - s["start"] >= need and parents.get((s["sid"], s["parent"]), 0) < 2  # noqa: E731
        cand = [s for s in pool if id(s) not in used and ok(s)]
        if not cand:
            used.clear()
            parents.clear()
            cand = [s for s in pool if s["end"] - s["start"] >= need]
        diff_src = [s for s in cand[:12] if s["sid"] != last_sid] or cand
        s = diff_src[0] if kind != "intro" else rng.choice(sorted(cand[:20], key=lambda c: -c["sharp"])[:5])
        used.add(id(s))
        parents[(s["sid"], s["parent"])] = parents.get((s["sid"], s["parent"]), 0) + 1
        last_sid = s["sid"]
        # the highest-motion window inside the shot
        m = np.array(s["motion"])
        w = max(1, int(need * AFPS))
        if len(m) > w:
            k = int(np.argmax(np.convolve(m, np.ones(w), "valid")))
            st = s["start"] + (k + 1) / AFPS
        else:
            st = s["start"]
        st = min(st, s["end"] - need)
        clips.append(dict(sid=s["sid"], parent=s["parent"], src_start=round(max(0.0, st), 3), t0=t0, t1=t1, kind=kind))
    return clips


# ── render ────────────────────────────────────────────────────────────────────
def render(clips, music, out_path, music_start, total):
    inputs, parts = [], []
    f_prev = 0
    for i, c in enumerate(clips):
        f_end = round((c["t1"] - music_start) * FPS)          # cumulative frame grid: no drift
        nfr = max(2, f_end - f_prev)
        f_prev = f_end
        dur = nfr / FPS
        inputs += ["-ss", f"{c['src_start']:.3f}", "-t", f"{dur + 0.2:.3f}",
                   "-i", str(EDITS / "sources" / f"{c['sid']}.mp4")]
        punch = {"intro": 0.06, "down": 0.14, "beat": 0.09, "fast": 0.12}[c["kind"]]
        fx = (f"[{i}:v]setpts=PTS-STARTPTS,fps={FPS},crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920,"
              f"zoompan=z='1+{punch}*max(0\\,1-on/5)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS},"
              f"trim=end_frame={nfr},setpts=PTS-STARTPTS")
        if c["kind"] == "down":
            fx += ",fade=t=in:st=0:d=0.12:color=white"
        parts.append(fx + f"[v{i}]")
    n = len(clips)
    graph = ";\n".join(parts) + ";\n" + "".join(f"[v{i}]" for i in range(n)) + \
        f"concat=n={n}:v=1:a=0,eq=contrast=1.22:saturation=1.18:gamma=0.96,unsharp=5:5:0.6,vignette=PI/5," \
        f"noise=alls=5:allf=t,setsar=1,format=yuv420p[vout];\n" \
        f"[{n}:a]atrim=0:{total:.3f},afade=t=in:d=0.03,afade=t=out:st={total - 0.6:.3f}:d=0.6," \
        f"loudnorm=I=-14:TP=-1.0:LRA=11,aresample=48000[aout]"
    gfile = Path(out_path).with_suffix(".graph.txt")
    gfile.write_text(graph, encoding="utf-8")
    inputs += ["-ss", f"{music_start:.3f}", "-t", f"{total + 0.5:.3f}", "-i", str(music)]
    for enc in ["h264_nvenc", "libx264"]:
        venc = (["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", "20", "-b:v", "0"] if "nvenc" in enc
                else ["-c:v", enc, "-preset", "medium", "-crf", "19"])
        r = run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex_script", str(gfile),
                 "-map", "[vout]", "-map", "[aout]", *venc, "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{total:.3f}", "-movflags", "+faststart", str(out_path)])
        if r.returncode == 0:
            gfile.unlink(missing_ok=True)
            return enc
        print(f"  encoder {enc} failed: {r.stderr.decode(errors='replace')[-600:]}")
    raise RuntimeError("Render failed with both encoders.")
