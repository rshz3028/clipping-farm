"""Licensed music for edits: NoCopyrightSounds (NCS), phonk + Brazilian phonk.

Licence (https://ncs.io/usage-policy, checked 2026-11-12): free to use in YouTube videos by
independent creators, monetisation allowed, the track's credit block must be in the description.
The credit block is copied verbatim from the track's ncs.io page (never written by a model).
Only the chosen track is downloaded (one MP3, ~5-8 MB) to work/edits/music/ncs/.
Every track is recorded in table music_tracks; every use in table edits (pipeline/edits/make.py).
"""
import html
import re
import time
import urllib.request
from urllib.parse import urlparse

from pipeline.core import registry
from pipeline.core.settings import WORK
from pipeline.discover.finders import slug

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) archival-shorts-pipeline/0.1"}
MUSIC_DIR = WORK / "edits" / "music" / "ncs"
GENRES = {"phonk": 16, "brazilian_phonk": 26}           # ncs.io music-search genre ids
ALLOWED = {"ncs.io", "ncsmusic.s3.eu-west-1.amazonaws.com"}
LICENCE = "NCS (NoCopyrightSounds) - free for YouTube creators incl. monetisation, credit required (ncs.io/usage-policy)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS music_tracks (
    track_id TEXT PRIMARY KEY, title TEXT, artists TEXT, genre TEXT, page_url TEXT, mp3_url TEXT,
    credit TEXT, licence TEXT, local_path TEXT, bpm REAL, added_on TEXT
);
"""


def _get(url: str) -> bytes:
    if urlparse(url).netloc not in ALLOWED:
        raise ValueError(f"music host not allowed: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def catalog(genre: str) -> list[dict]:
    t = _get(f"https://ncs.io/music-search?q=&genre={GENRES[genre]}&mood=").decode("utf-8", "replace")
    out = []
    for row in re.findall(r"<tr.*?</tr>", t, re.S):
        art = re.search(r'data-artistraw="([^"]*)"', row)
        trk = re.search(r'data-track="([^"]*)"', row)
        mp3 = re.search(r'"(https://ncsmusic\.s3\.eu-west-1\.amazonaws\.com/tracks/[^"]+?\.mp3)"', row)
        page = re.search(r'href="/([A-Za-z0-9_\-]+)"', row)
        if art and trk and mp3 and page:
            title, artists = html.unescape(trk.group(1)), html.unescape(art.group(1))
            out.append(dict(track_id="ncs_" + slug(f"{artists} {title}", 48), title=title, artists=artists,
                            genre=genre, page_url=f"https://ncs.io/{page.group(1)}", mp3_url=mp3.group(1)))
    return out


def credit(page_url: str) -> str:
    t = _get(page_url).decode("utf-8", "replace")
    i = t.find('class="attribution"')
    if i < 0:
        raise RuntimeError(f"no credit block on {page_url}")
    raw = t[i:i + 3000]
    raw = re.sub(r"<(https?://[^>\s]+)>", r"\1", raw)          # some pages write links as <http://...>
    txt = html.unescape(re.sub(r"<br\s*/?>", "\n", raw)).replace("\\_", "_")   # and some escape underscores
    lines = [ln.strip() for ln in re.sub(r"<[^>]+>", "\n", txt).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith('class=')]
    a = next((k for k, ln in enumerate(lines) if ln.startswith("Song:")), None)
    b = next((k for k, ln in enumerate(lines) if ln.startswith("Watch:")), None)
    lines = lines[a:b + 1] if a is not None and b is not None and b >= a else []
    links_ok = all(any(ln.startswith(k) and "http" in ln for ln in lines) for k in ("Free Download", "Watch:"))
    if not any("NoCopyrightSounds" in ln for ln in lines) or not links_ok:
        raise RuntimeError(f"unexpected credit block on {page_url}: {lines}")
    return "\n".join(lines)


def use_counts() -> dict:
    with registry.connect() as c:
        c.executescript(SCHEMA)
        try:
            return {r[0]: r[1] for r in c.execute("SELECT track_id, COUNT(*) FROM edits GROUP BY track_id")}
        except Exception:
            return {}


def choose(weights: dict, rng, recent_days_block: int = 3) -> dict:
    """Pick a genre in proportion to the trend weights (each genre keeps a floor), then the least-used
    track of that genre (random among ties). Downloads it if needed and records it."""
    genres = list(GENRES)
    wts = [0.25 + weights.get(g, 0) for g in genres]
    genre = rng.choices(genres, weights=wts)[0]
    tracks = catalog(genre) or catalog("phonk")
    used = use_counts()
    low = min(used.get(t["track_id"], 0) for t in tracks)
    pick = rng.choice([t for t in tracks if used.get(t["track_id"], 0) == low])
    with registry.connect() as c:
        c.executescript(SCHEMA)
        row = c.execute("SELECT * FROM music_tracks WHERE track_id=?", (pick["track_id"],)).fetchone()
    if row and row["local_path"] and (WORK / row["local_path"]).exists():
        return dict(row)
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    path = MUSIC_DIR / f"{pick['track_id']}.mp3"
    if not path.exists():
        data = _get(pick["mp3_url"])
        if len(data) < 500_000:
            raise RuntimeError(f"download too small for {pick['mp3_url']}")
        path.write_bytes(data)
    rec = dict(pick, credit=credit(pick["page_url"]), licence=LICENCE,
               local_path=path.relative_to(WORK).as_posix(), bpm=None, added_on=time.strftime("%Y-%m-%d"))
    with registry.connect() as c:
        c.execute(f"INSERT OR REPLACE INTO music_tracks ({','.join(rec)}) VALUES ({','.join('?' * len(rec))})",
                  tuple(rec.values()))
    return rec
