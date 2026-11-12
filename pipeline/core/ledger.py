"""SQLite tables beyond the source registry: Claude call log and published scripts."""
import time

from pipeline.core.registry import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    stage           TEXT NOT NULL,
    unit_id         TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    model           TEXT,
    ok              INTEGER NOT NULL,
    input_tokens    INTEGER,
    cache_write_tokens INTEGER,
    cache_read_tokens  INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    seconds         REAL,
    error           TEXT
);
CREATE TABLE IF NOT EXISTS published_scripts (
    short_id    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    title       TEXT,
    narration   TEXT NOT NULL,
    created     TEXT NOT NULL
);
"""


def _conn():
    c = connect()
    c.executescript(SCHEMA)
    return c


def log_call(**row) -> None:
    row.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
    cols = ", ".join(row)
    with _conn() as c:
        c.execute(f"INSERT INTO llm_calls ({cols}) VALUES ({', '.join('?' * len(row))})",
                  tuple(row.values()))


def calls_today() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM llm_calls WHERE ts >= date('now','localtime') ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def published_scripts() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM published_scripts").fetchall()]


def add_published(short_id: str, source_id: str, title: str, narration: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO published_scripts VALUES (?,?,?,?,?)",
                  (short_id, source_id, title, narration, time.strftime("%Y-%m-%d %H:%M:%S")))
