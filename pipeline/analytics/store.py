"""Analytics tables in work/pipeline.db. Safe to call ensure() any number of times."""
from pipeline.core import registry

SCHEMA = """
CREATE TABLE IF NOT EXISTS yt_stats (
    video_id TEXT, fetched_at TEXT, title TEXT, published_at TEXT, privacy TEXT,
    duration_s REAL, short_id TEXT,
    views INTEGER, likes INTEGER, comments INTEGER,             -- public counters (live)
    a_views INTEGER, a_minutes REAL, a_avg_view_s REAL, a_avg_view_pct REAL,
    a_likes INTEGER, a_comments INTEGER, a_shares INTEGER, a_subs_gained INTEGER, a_subs_lost INTEGER,
    traffic_json TEXT,                                          -- views per traffic source
    PRIMARY KEY (video_id, fetched_at)
);
-- views per video per day (YouTube Analytics; lags 1-3 days). Replaced on every fetch.
CREATE TABLE IF NOT EXISTS yt_daily (
    video_id TEXT, day TEXT, views INTEGER, engaged_views INTEGER, minutes REAL,
    subs_gained INTEGER, fetched_at TEXT,
    PRIMARY KEY (video_id, day)
);
-- retention curve: up to 100 points per video (ratio 0.01..1.0). Replaced on every fetch.
-- watch_ratio > 1 = people rewatch/loop that part; rel_perf: 0..1 vs similar-length videos, 0.5 = median
CREATE TABLE IF NOT EXISTS yt_retention (
    video_id TEXT, ratio REAL, watch_ratio REAL, rel_perf REAL, fetched_at TEXT,
    PRIMARY KEY (video_id, ratio)
);
-- channel totals, one row per fetch
CREATE TABLE IF NOT EXISTS yt_channel (
    fetched_at TEXT PRIMARY KEY, channel_id TEXT, title TEXT,
    subscribers INTEGER, total_views INTEGER, video_count INTEGER
);
-- Studio-only Shorts numbers, imported from CSV exports (see studio.py)
CREATE TABLE IF NOT EXISTS studio_stats (
    video_id TEXT, file TEXT, imported_at TEXT, shown_in_feed INTEGER, viewed_pct REAL,
    PRIMARY KEY (video_id, file)
);
-- how each video was made (from our sidecars); one row per short_id / edit_id
CREATE TABLE IF NOT EXISTS content_features (
    short_id TEXT PRIMARY KEY, kind TEXT, title TEXT, hook TEXT, topic TEXT, source_id TEXT,
    duration_s REAL, words INTEGER, rewritten INTEGER, track TEXT, music_style TEXT, bpm REAL,
    theme TEXT, folder TEXT, made TEXT, youtube_id TEXT, updated_at TEXT
);
"""

# columns added to yt_stats after it was first created
_YT_STATS_EXTRA = {"engaged_views": "INTEGER", "location_json": "TEXT"}


def ensure(conn=None):
    own = conn is None
    conn = conn or registry.connect()
    try:
        conn.executescript(SCHEMA)
        have = {r[1] for r in conn.execute("PRAGMA table_info(yt_stats)")}
        for col, typ in _YT_STATS_EXTRA.items():
            if col not in have:
                conn.execute(f"ALTER TABLE yt_stats ADD COLUMN {col} {typ}")
        conn.commit()
    finally:
        if own:
            conn.close()


def connect():
    conn = registry.connect()
    ensure(conn)
    return conn
