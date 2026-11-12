"""Word timings: Whisper re-listens to our own narration (GPU), then its words are matched
to the script's words so captions use the exact script spelling. Words Whisper missed are
interpolated inside their sentence. Then builds an ASS file:
  - captions: 1-3 word groups, current word highlighted
  - header: the question at the top while the narration plays
  - end card: attribution text after the narration ends
"""
import difflib
import gc
import re

from pipeline.core.settings import MODELS
from pipeline.core.textprep import tokens
from pipeline.core.tools import setup_cuda_dlls, write_json


def _whisper_words(wav, cfg, prompt):
    setup_cuda_dlls()
    from faster_whisper import WhisperModel
    model_dir = MODELS / "whisper" / cfg.get("whisper_model", "large-v3-turbo")
    model = WhisperModel(str(model_dir), device=cfg.get("device", "cuda"), compute_type=cfg.get("compute_type", "int8"))
    try:
        segs, _ = model.transcribe(str(wav), language="en", word_timestamps=True, initial_prompt=prompt[:800],
                                   condition_on_previous_text=False, vad_filter=False)
        return [{"w": w.word.strip(), "s": w.start, "e": w.end} for s in segs for w in (s.words or [])]
    finally:
        del model
        gc.collect()


def _script_words(narr):
    out = []
    for s in narr["sentences"]:
        for raw in s["text"].split():
            out.append({"text": raw, "norm": "".join(tokens(raw)), "sent": s["i"]})
    return out


def _align(script_words, heard, narr):
    a = [w["norm"] for w in script_words]
    b = ["".join(tokens(w["w"])) for w in heard]
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            sw, hw = script_words[blk.a + k], heard[blk.b + k]
            sw["s"], sw["e"] = hw["s"], hw["e"]
    # fill gaps by sharing time evenly inside each sentence, and clamp to sentence bounds
    sents = {s["i"]: s for s in narr["sentences"]}
    for si, sent in sents.items():
        idx = [i for i, w in enumerate(script_words) if w["sent"] == si]
        i = 0
        while i < len(idx):
            if "s" in script_words[idx[i]]:
                i += 1
                continue
            j = i
            while j < len(idx) and "s" not in script_words[idx[j]]:
                j += 1
            lo = script_words[idx[i - 1]]["e"] if i > 0 else sent["start"]
            hi = script_words[idx[j]]["s"] if j < len(idx) else sent["end"]
            n = j - i
            for k in range(n):
                w = script_words[idx[i + k]]
                w["s"] = lo + (hi - lo) * k / n
                w["e"] = lo + (hi - lo) * (k + 1) / n
            i = j
        for k in idx:
            w = script_words[k]
            w["s"] = min(max(w["s"], sent["start"]), sent["end"])
            w["e"] = min(max(w["e"], w["s"] + 0.05), sent["end"])
    return script_words


def _chunks(words, max_words, max_chars):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x["text"] for x in cur + [w])) > max_chars
                    or w["sent"] != cur[-1]["sent"]):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.,;:!?]$", w["text"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _ass_color(hex_rgb, alpha="00"):
    h = hex_rgb.lstrip("#")
    return f"&H{alpha}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _wrap(text, width):
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def run(unit, cfg):
    script = unit.json("short/script.json")
    narr = unit.json("short/narration.json")
    heard = _whisper_words(unit.path("short/narration.wav"), cfg, " ".join(script["sentences"]))
    words = _align(_script_words(narr), heard, narr)
    groups = _chunks(words, cfg.get("max_words", 3), cfg.get("max_chars", 18))

    t = cfg.get("timing", {})
    pb = float(t.get("playback_speed", 1.0))           # render speeds the whole video up by pb
    end_card = float(t.get("end_card_seconds", 2.5)) * pb
    total = min(narr["duration"] + end_card, float(t.get("max_seconds", 59.5)) * pb)
    W, H = cfg.get("width", 1080), cfg.get("height", 1920)
    text_c, hi_c = _ass_color(cfg.get("text_color", "#FFFFFF")), _ass_color(cfg.get("highlight_color", "#FFD84D"))
    font = cfg.get("font", "Be Vietnam Pro")

    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{cfg.get('font_size', 80)},{text_c},{text_c},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,5,40,40,0,1",
        f"Style: Head,{font},{cfg.get('header_size', 56)},{text_c},{text_c},&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,4,0,5,60,60,0,1",
        f"Style: End,{font},{cfg.get('end_size', 46)},{text_c},{text_c},&H00000000,&H50000000,-1,0,0,0,100,100,0,0,3,18,0,5,80,80,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cx, cy = W // 2, cfg.get("caption_y", 1480)
    for g in groups:
        for k, w in enumerate(g):          # one event per word: same group, current word highlighted
            start = w["s"]
            end = g[k + 1]["s"] if k + 1 < len(g) else w["e"]
            if end - start < 0.04:
                continue
            txt = " ".join((f"{{\\c{hi_c}}}{_esc(x['text'])}{{\\c{text_c}}}" if x is w else _esc(x["text"])) for x in g)
            ass.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{\\pos({cx},{cy})}}{txt}")
    header = {"question": script["question"], "title": script["title"]}.get(cfg.get("header", "question"))
    if header:
        ass.append(f"Dialogue: 0,{_ts(0)},{_ts(narr['speech_end'])},Head,,0,0,0,,"
                   f"{{\\pos({cx},{cfg.get('header_y', 250)})}}{_wrap(_esc(header), cfg.get('header_wrap', 26))}")
    ass.append(f"Dialogue: 2,{_ts(narr['speech_end'] + 0.2)},{_ts(total)},End,,0,0,0,,{{\\pos({cx},{H // 2})\\fad(250,0)}}"
               f"{_wrap(_esc(script['attribution']), cfg.get('end_wrap', 34))}")

    tmp = unit.path("short/captions.ass.tmp")
    tmp.write_text("\n".join(ass) + "\n", encoding="utf-8-sig")
    tmp.replace(unit.path("short/captions.ass"))
    matched = sum(1 for w in words if w.get("s") is not None)
    write_json(unit.path("short/captions.json"), {
        "total_duration": round(total, 3), "speech_end": narr["speech_end"],
        "playback_speed": pb, "final_duration": round(total / pb, 3),
        "words": [{"text": w["text"], "s": round(w["s"], 3), "e": round(w["e"], 3), "sent": w["sent"]} for w in words],
        "groups": [[w["text"] for w in g] for g in groups], "heard_words": len(heard),
    })
    print(f"  {len(words)} words ({len(heard)} heard by Whisper) in {len(groups)} caption groups; total {total:.1f}s")
