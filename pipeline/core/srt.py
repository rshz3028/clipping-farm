"""Build an .srt subtitle file (for YouTube's subtitle upload) from captions.json word timings."""
import re


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(round(t * 1000)), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_srt(captions: dict, max_words: int = 8, max_chars: int = 42) -> str:
    """One cue per short phrase (never crossing a sentence), timed to the FINAL video
    (word times are divided by the playback speed the render applied)."""
    pb = float(captions.get("playback_speed", 1.0))
    words = captions["words"]
    cues, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["sent"] != cur[-1]["sent"]
                    or len(" ".join(x["text"] for x in cur + [w])) > max_chars):
            cues.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?;:]$", w["text"]):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    out = []
    for i, c in enumerate(cues, 1):
        start, end = c[0]["s"] / pb, c[-1]["e"] / pb
        if i < len(cues):                       # hold until the next cue starts, but never overlap
            end = max(end, min(cues[i][0]["s"] / pb, end + 0.6))
        out.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{' '.join(x['text'] for x in c)}\n")
    return "\n".join(out)
