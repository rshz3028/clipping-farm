"""Source registry: the only videos the pipeline is allowed to touch.

The runner calls require_approved() before EVERY source-level stage, so no
stage implementation can bypass it.
"""
import sqlite3
from urllib.parse import urlparse

from pipeline.core.settings import DB_PATH, WORK

# Archives the user approved. Anything else is refused outright.
ALLOWED_HOSTS = {
    "images.nasa.gov",        # NASA Image and Video Library
    "archive.org",            # Prelinger Archives (collection re-checked at download)
    "www.loc.gov",            # Library of Congress
    "catalog.archives.gov",   # US National Archives
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id               TEXT PRIMARY KEY,
    url                     TEXT UNIQUE NOT NULL,
    title                   TEXT,
    owner                   TEXT NOT NULL,
    licence                 TEXT NOT NULL,
    commercial_use_allowed  INTEGER NOT NULL CHECK (commercial_use_allowed IN (0,1)),
    derivatives_allowed     INTEGER NOT NULL CHECK (derivatives_allowed IN (0,1)),
    attribution_text        TEXT NOT NULL,
    restrictions            TEXT,
    licence_evidence        TEXT,
    date_checked            TEXT NOT NULL,
    local_path              TEXT,         -- relative to the work folder
    status                  TEXT NOT NULL DEFAULT 'active',   -- active | used (all its Shorts made)
    added_by                TEXT NOT NULL DEFAULT 'hand',     -- hand | auto:<finder>
    added_on                TEXT
);
CREATE TABLE IF NOT EXISTS discovery_seen (
    url        TEXT PRIMARY KEY,
    finder     TEXT,
    title      TEXT,
    outcome    TEXT,        -- added | rejected
    reason     TEXT,
    checked_on TEXT
);
"""
NEW_COLUMNS = {   # added after the first version; created on old databases automatically
    "status": "TEXT NOT NULL DEFAULT 'active'",
    "added_by": "TEXT NOT NULL DEFAULT 'hand'",
    "added_on": "TEXT",
}


class SourceNotApproved(Exception):
    pass


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(sources)")}
    for col, decl in NEW_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE sources ADD COLUMN {col} {decl}")
    return conn


def host_allowed(url: str) -> bool:
    return urlparse(url).netloc.lower() in ALLOWED_HOSTS


def upsert(rec: dict) -> None:
    if not host_allowed(rec["url"]):
        raise SourceNotApproved(f"Host not on the approved archive list: {rec['url']}")
    cols = ", ".join(rec)
    marks = ", ".join(f":{k}" for k in rec)
    updates = ", ".join(f"{k}=excluded.{k}" for k in rec if k not in ("source_id", "local_path"))
    with connect() as c:
        c.execute(f"INSERT INTO sources ({cols}) VALUES ({marks}) "
                  f"ON CONFLICT(source_id) DO UPDATE SET {updates}", rec)


def require_approved(source_id: str) -> dict:
    """Return the source record, or raise if it may not be used."""
    with connect() as c:
        row = c.execute("SELECT * FROM sources WHERE source_id=?", (source_id,)).fetchone()
    if row is None:
        raise SourceNotApproved(f"{source_id}: not in the source registry")
    if not host_allowed(row["url"]):
        raise SourceNotApproved(f"{source_id}: host not on the approved archive list")
    if not (row["commercial_use_allowed"] and row["derivatives_allowed"]):
        raise SourceNotApproved(f"{source_id}: commercial use or derivatives not allowed")
    return dict(row)


def approved_sources(status: str | None = None) -> list[dict]:
    q = "SELECT * FROM sources WHERE commercial_use_allowed=1 AND derivatives_allowed=1"
    args = ()
    if status:
        q += " AND status=?"
        args = (status,)
    with connect() as c:
        rows = c.execute(q + " ORDER BY source_id", args).fetchall()
    return [dict(r) for r in rows]


def set_status(source_id: str, status: str) -> None:
    with connect() as c:
        c.execute("UPDATE sources SET status=? WHERE source_id=?", (status, source_id))


def known_urls() -> set[str]:
    with connect() as c:
        return ({r[0] for r in c.execute("SELECT url FROM sources")}
                | {r[0] for r in c.execute("SELECT url FROM discovery_seen")})


def mark_seen(url, finder, title, outcome, reason) -> None:
    import time
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO discovery_seen VALUES (?,?,?,?,?,?)",
                  (url, finder, title, outcome, (reason or "")[:500], time.strftime("%Y-%m-%d")))


def set_local_path(source_id: str, path) -> None:
    from pathlib import Path
    rel = Path(path).resolve().relative_to(WORK.resolve()).as_posix()
    with connect() as c:
        c.execute("UPDATE sources SET local_path=? WHERE source_id=?", (rel, source_id))


def print_table() -> None:
    with connect() as c:
        rows = c.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
    for r in rows:
        print(f"\n[{r['source_id']}] {r['title']}")
        for k in ("url", "owner", "licence", "commercial_use_allowed", "derivatives_allowed",
                  "attribution_text", "restrictions", "date_checked", "local_path", "status", "added_by"):
            print(f"   {k:24}: {r[k]}")
    print(f"\n{len(rows)} sources")
