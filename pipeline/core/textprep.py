"""Local (free) text work that keeps Claude calls small: condensing transcripts,
cutting windows, and measuring copied phrases / similarity."""
import re


def fmt_t(sec: float) -> str:
    return f"{sec:.1f}"


def condensed_transcript(transcript: dict, block_seconds: float = 20.0) -> str:
    """Merge segments into ~20 s blocks: '[92.1-111.8] text'. Cuts tokens a lot."""
    lines, cur, start, end = [], [], None, None
    for s in transcript["segments"]:
        if start is None:
            start = s["start"]
        cur.append(s["text"])
        end = s["end"]
        if end - start >= block_seconds:
            lines.append(f"[{fmt_t(start)}-{fmt_t(end)}] {' '.join(cur)}")
            cur, start = [], None
    if cur:
        lines.append(f"[{fmt_t(start)}-{fmt_t(end)}] {' '.join(cur)}")
    return "\n".join(lines)


def words_between(transcript: dict, a: float, b: float) -> str:
    out = []
    for s in transcript["segments"]:
        for w in s["words"]:
            if w["s"] >= a and w["e"] <= b:
                out.append(w["w"])
    return " ".join(out)


def shots_in_window(transcript: dict, shots: dict, a: float, b: float) -> str:
    """One line per shot inside [a, b] with what is being said during it
    (the only text hint we have about what is on screen)."""
    lines = []
    for sh in shots["shots"]:
        if sh["end"] <= a or sh["start"] >= b:
            continue
        said = words_between(transcript, sh["start"], sh["end"])
        shows = shots.get("_descriptions", {}).get(str(sh["i"]))
        lines.append(f"S{sh['i']} [{fmt_t(sh['start'])}-{fmt_t(sh['end'])}, {sh['end']-sh['start']:.1f}s]"
                     + (f" shows: {shows[:140]};" if shows else "")
                     + f" said: {said[:160] or '(no speech)'}")
    return "\n".join(lines)


_WORD = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def longest_copied_run(script: str, source: str) -> tuple[int, str]:
    """Longest run of consecutive words in `script` that also appears in `source`."""
    s, src = tokens(script), tokens(source)
    src_ngrams = {}
    best, best_txt = 0, ""
    for n in range(4, 40):
        grams = {tuple(src[i:i + n]) for i in range(len(src) - n + 1)}
        found = None
        for i in range(len(s) - n + 1):
            if tuple(s[i:i + n]) in grams:
                found = " ".join(s[i:i + n])
                break
        if not found:
            break
        best, best_txt = n, found
        src_ngrams[n] = grams
    return best, best_txt


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of word 3-grams (0 = nothing shared, 1 = identical)."""
    ta, tb = tokens(a), tokens(b)
    ga = {tuple(ta[i:i + 3]) for i in range(len(ta) - 2)}
    gb = {tuple(tb[i:i + 3]) for i in range(len(tb) - 2)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)
