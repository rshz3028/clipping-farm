"""Import Studio-only Shorts numbers ("Shown in feed", "Viewed vs swiped away") from CSV files.

The YouTube API does not provide these two numbers. To add them:
  YouTube Studio -> Analytics -> Advanced mode -> Content: Shorts -> add the metrics
  "Shown in feed" and "Viewed (vs. swiped away)" -> Export -> Comma-separated values (.csv)
  Unzip and put the "Table data.csv" (any name is fine) into  work/analytics/studio/
The next run (or `python dashboard.py`) imports it. Column names are matched loosely, so
small renames by YouTube don't break it; a hand-made CSV with columns
  video_id, shown_in_feed, viewed_pct   works too.
"""
import csv
import datetime as dt
import re

from pipeline.core.settings import WORK
from pipeline.analytics import store

STUDIO_DIR = WORK / "analytics" / "studio"
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _col(header, *needles):
    for i, h in enumerate(header):
        h2 = h.strip().lower()
        if all(n in h2 for n in needles):
            return i
    return None


def _num(s):
    s = (s or "").strip().replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def import_all(log=print):
    STUDIO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(STUDIO_DIR.glob("*.csv"))
    if not files:
        return 0
    conn = store.connect()
    n = 0
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        for f in files:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.reader(fh))
            if not rows:
                continue
            head = rows[0]
            c_id = _col(head, "video_id")
            if c_id is None:
                c_id = _col(head, "content")
            c_shown = _col(head, "shown", "feed")
            if c_shown is None:
                c_shown = _col(head, "shown_in_feed")
            c_view = (_col(head, "viewed", "swiped") if _col(head, "viewed", "swiped") is not None
                      else _col(head, "stayed to watch") if _col(head, "stayed to watch") is not None
                      else _col(head, "viewed_pct"))
            if c_id is None or (c_shown is None and c_view is None):
                log(f"studio import: {f.name}: could not find the columns (have: {', '.join(head)[:200]})")
                continue
            got = 0
            for r in rows[1:]:
                vid = r[c_id].strip() if c_id < len(r) else ""
                if not _ID.match(vid):
                    continue                      # skips the "Total" row
                shown = _num(r[c_shown]) if c_shown is not None and c_shown < len(r) else None
                viewed = _num(r[c_view]) if c_view is not None and c_view < len(r) else None
                conn.execute("INSERT OR REPLACE INTO studio_stats VALUES (?,?,?,?,?)",
                             (vid, f.name, now, int(shown) if shown is not None else None, viewed))
                got += 1
            n += got
        conn.commit()
    finally:
        conn.close()
    if n:
        log(f"studio import: {n} rows from {len(files)} file(s)")
    return n
