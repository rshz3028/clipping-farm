"""Fill content_features from our own sidecars (output/*/*.json) and the edits/music tables.

Only facts we recorded when making the video: kind, title, opening line, topic/source,
length, script words, music track/style/BPM. No API calls.
"""
import datetime as dt
import json

from pipeline.core.settings import OUTPUT
from pipeline.analytics import store


def _as_obj(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect():
    """Every sidecar in output/<folder>/ -> one feature dict. Later folders win (uploaded > approved > review)."""
    order = {"review": 0, "edits_review": 0, "approved": 1, "uploaded": 2}
    rows = {}
    for side in sorted(OUTPUT.glob("*/*.json"), key=lambda p: order.get(p.parent.name, 0)):
        try:
            m = json.loads(side.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(m, dict) or not m.get("title"):
            continue
        sid = side.stem
        is_edit = m.get("kind") == "music_edit" or sid.startswith("edit_")
        src = _as_obj(m.get("source")) or {}
        script = _as_obj(m.get("script")) or {}
        sentences = script.get("sentences") if isinstance(script, dict) else None
        music = _as_obj(m.get("music")) or {}
        rows[sid] = dict(
            short_id=sid,
            kind="edit" if is_edit else "short",
            title=m.get("title"),
            hook=(script.get("question") or (sentences or [None])[0]) if isinstance(script, dict) else None,
            topic=(src.get("title") if isinstance(src, dict) else None) or m.get("theme"),
            source_id=src.get("source_id") if isinstance(src, dict) else None,
            duration_s=_num(m.get("duration_seconds") or m.get("seconds")),
            words=sum(len(s.split()) for s in sentences) if sentences else None,
            rewritten=1 if str(m.get("rewritten")).lower() == "true" else 0,
            track=music.get("title") if isinstance(music, dict) else None,
            music_style=None, bpm=None,
            theme=m.get("theme"),
            folder=side.parent.name,
            made=m.get("created") or m.get("made"),
            youtube_id=m.get("youtube_video_id"),
        )
    return rows


def refresh(conn=None):
    own = conn is None
    conn = conn or store.connect()
    try:
        rows = collect()
        # music style + BPM come from the edits/music tables
        try:
            for r in conn.execute("SELECT e.edit_id, e.bpm, t.genre, t.title FROM edits e "
                                  "LEFT JOIN music_tracks t ON t.track_id = e.track_id"):
                if r["edit_id"] in rows:
                    rows[r["edit_id"]].update(bpm=r["bpm"], music_style=r["genre"],
                                              track=rows[r["edit_id"]]["track"] or r["title"])
        except Exception:
            pass
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows.values():
            r["updated_at"] = now
            cols = list(r)
            conn.execute(f"INSERT OR REPLACE INTO content_features ({','.join(cols)}) "
                         f"VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])
        conn.commit()
        return len(rows)
    finally:
        if own:
            conn.close()
