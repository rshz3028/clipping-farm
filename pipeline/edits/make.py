"""Make one music edit end to end:
  trending styles (YouTube Shorts chart) -> licensed NCS track in that style -> footage for the theme
  -> beat-synced cut -> output/edits_review/<edit_id>.mp4 + .json (title, description, credits).

Settings: pipeline.toml [edits] and [edits.themes.<theme>]. Every edit is recorded in table `edits`
(track + shots used) so later edits rotate music and avoid repeating the same shots.
"""
import json
import random
import re
import time

from pipeline.core import registry
from pipeline.core.settings import CONFIG, OUTPUT, WORK
from pipeline.core.tools import write_json
from pipeline.edits import editor, footage, music, trends

REVIEW = OUTPUT / "edits_review"
SCHEMA = """
CREATE TABLE IF NOT EXISTS edits (
    edit_id TEXT PRIMARY KEY, theme TEXT, made TEXT, track_id TEXT, bpm REAL, seconds REAL,
    sources TEXT, shots TEXT, output TEXT, trend TEXT
);
"""
AIRCRAFT = r"\b(F/A-18|F-18|F-15|F-16|F-35|F-5|T-38|SR-71|X-59|X-43|X-15|B-52|C-17|U-2|ER-2|DC-8|P-3|G-III|747|Super Hornet)\b"


def cfg() -> dict:
    return CONFIG.get("edits", {})


def recent_shots(theme: str, n_edits: int = 6) -> set:
    with registry.connect() as c:
        c.executescript(SCHEMA)
        rows = c.execute("SELECT shots FROM edits WHERE theme=? ORDER BY made DESC LIMIT ?", (theme, n_edits)).fetchall()
    return {tuple(x) for r in rows for x in json.loads(r[0] or "[]")}


def title_for(theme_cfg: dict, recs: list[dict], rng) -> str:
    names = []
    for r in recs:
        for m in re.findall(AIRCRAFT, f"{r['title']} {r.get('restrictions', '')}"):
            if m not in names:
                names.append(m)
    subject = " & ".join(names[:2]) or theme_cfg.get("subject", "Jets")
    tpl = rng.choice(theme_cfg.get("titles", ["{subject} full send ✈️🔥"]))
    return f"{tpl.format(subject=subject)} {theme_cfg.get('hashtags', '')}".strip()[:100]


def make_one(theme: str = "jets", seconds: float | None = None, seed: int | None = None, log=print) -> dict:
    c = cfg()
    tc = c.get("themes", {}).get(theme, {})
    rng = random.Random(seed if seed is not None else time.time_ns())
    seconds = float(seconds or c.get("seconds", 20))

    # 1. footage: top up the theme's footage when fewer than min_sources are on disk
    sids = footage.theme_sources(theme)
    if len(sids) < int(tc.get("min_sources", 3)):
        log(f"  footage: {len(sids)} sources for '{theme}', searching NASA for more")
        try:
            footage.find_new(theme, tc, log)
        except Exception as e:
            log(f"  footage search failed ({e}); continuing with what we have")
        sids = footage.theme_sources(theme)
    if len(sids) < 1:
        raise RuntimeError(f"no footage for theme '{theme}'")
    recs = {s: registry.require_approved(s) for s in sids}          # licence gate, every time

    # 2. music: trend -> licensed track
    try:
        weights = trends.style_weights(trends.shorts_chart(c.get("chart_country", "us")))
    except Exception as e:
        log(f"  trends: chart unavailable ({e}); using equal weights")
        weights = {}
    track = music.choose(weights, rng)
    log(f"  music: {track['artists']} - {track['title']} ({track['genre']}; trend {weights})")

    # 3. analysis + beat-synced plan
    shots = {s: editor.analyse(s)["shots"] for s in sids}
    bpm, bt, drop, _ = editor.beats(WORK / track["local_path"])
    log(f"  beat: {bpm:.1f} BPM, drop at {bt[drop]:.1f}s")
    segs = editor.plan(bt, drop, seconds, rng)
    clips = editor.pick_clips(segs, shots, rng, avoid=recent_shots(theme))
    music_start, total = segs[0][0], segs[-1][1] - segs[0][0]

    # 4. render
    REVIEW.mkdir(parents=True, exist_ok=True)
    edit_id = f"edit_{theme}_{time.strftime('%Y%m%d_%H%M%S')}"
    out = REVIEW / f"{edit_id}.mp4"
    log(f"  render: {len(clips)} cuts, {total:.1f}s -> {out.name}")
    enc = editor.render(clips, WORK / track["local_path"], out, music_start, total)

    # 5. sidecar: credits always from the registry / the NCS page, never from a model
    used = [s for s in sids if any(cl["sid"] == s for cl in clips)]
    used_recs = [recs[s] for s in used]
    footage_credits = "\n".join(r["attribution_text"] for r in used_recs)
    title = title_for(tc, used_recs, rng)
    desc = (f"{footage_credits}\n\n{track['credit']}\n\n"
            f"Archival footage is used as illustration; no endorsement by NASA is implied.\n"
            f"{tc.get('hashtags', '')}").strip()
    meta = dict(kind="music_edit", theme=theme, edit_id=edit_id, title=title, description=desc,
                tags=tc.get("tags", []), category=tc.get("category", "Autos & Vehicles"),
                source={"source_id": used[0]},
                sources=[{k: r[k] for k in ("source_id", "url", "licence", "attribution_text", "restrictions")}
                         for r in used_recs],
                music=dict(track_id=track["track_id"], title=track["title"], artists=track["artists"],
                           page=track["page_url"], licence=track["licence"], credit=track["credit"],
                           bpm=round(bpm, 1), start=round(music_start, 3)),
                trend=weights, clips=clips, seconds=round(total, 2), encoder=enc,
                made=time.strftime("%Y-%m-%d %H:%M:%S"))
    write_json(out.with_suffix(".json"), meta)
    with registry.connect() as con:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO edits VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (edit_id, theme, meta["made"], track["track_id"], round(bpm, 1), round(total, 2),
                     json.dumps(used), json.dumps(sorted({(cl["sid"], cl["parent"]) for cl in clips})),
                     str(out.relative_to(OUTPUT)), json.dumps(weights)))
        con.execute("UPDATE music_tracks SET bpm=? WHERE track_id=?", (round(bpm, 1), track["track_id"]))
    log(f"  done: {out}")
    return meta
