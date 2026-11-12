"""Footage for edits: raw B-roll from images.nasa.gov, found + licence-checked with the same code as the
educational pipeline (pipeline/discover/finders/nasa_images.py) and downloaded with the same resolver
(pipeline/stages/download/archive_api.py). Registered in the source registry with status 'edit'
(so the educational produce job never touches them) and tagged with a theme in table edit_sources.
"""
import re
import time
import urllib.request

from pipeline.core import registry
from pipeline.core.settings import WORK
from pipeline.discover.finders import nasa_images
from pipeline.stages.download.archive_api import UA, _nasa_file_url

SRC_DIR = WORK / "edits" / "sources"
SCHEMA = "CREATE TABLE IF NOT EXISTS edit_sources (source_id TEXT PRIMARY KEY, theme TEXT, added_on TEXT);"


def theme_sources(theme: str) -> list[str]:
    with registry.connect() as c:
        c.executescript(SCHEMA)
        ids = [r[0] for r in c.execute("SELECT source_id FROM edit_sources WHERE theme=?", (theme,))]
    return [i for i in ids if (SRC_DIR / f"{i}.mp4").exists()]


def tag(source_id: str, theme: str) -> None:
    with registry.connect() as c:
        c.executescript(SCHEMA)
        c.execute("INSERT OR IGNORE INTO edit_sources VALUES (?,?,?)", (source_id, theme, time.strftime("%Y-%m-%d")))


def download(source_id: str, cfg: dict) -> None:
    rec = registry.require_approved(source_id)
    url = _nasa_file_url(rec["url"], {"nasa_quality": cfg.get("quality", ["large", "medium"]),
                                      "max_mb": cfg.get("max_mb", 500)})
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SRC_DIR / f"{source_id}.mp4.part"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(SRC_DIR / f"{source_id}.mp4")


def find_new(theme: str, cfg: dict, log=print) -> list[str]:
    """Search NASA for raw footage for this theme; licence-check, register, download. Returns new ids."""
    must = re.compile(cfg.get("must_match", r"b-?roll"), re.I)
    known = registry.known_urls()
    found, rejected = nasa_images.search({
        "queries": cfg.get("queries", []), "min_minutes": cfg.get("min_minutes", 1),
        "max_minutes": cfg.get("max_minutes", 20), "max_checks": cfg.get("max_checks", 15),
        "exclude_title_patterns": cfg.get("exclude_title_patterns", []),
        "exclude_centers": cfg.get("exclude_centers", ["JPL"])}, known)
    new = []
    for f in found:
        nid = f["url"].rsplit("/", 1)[-1]
        if not must.search(f"{f['title']} {nid}"):
            registry.mark_seen(f["url"], "edits", f["title"], "rejected", "not raw B-roll")
            continue
        if len(new) >= int(cfg.get("max_new", 2)):
            break
        rec = dict(f["record"], source_id=f"edit_{f['record']['source_id']}", status="edit",
                   added_by=f"auto:edits:{theme}", added_on=time.strftime("%Y-%m-%d"))
        registry.upsert(rec)
        registry.mark_seen(f["url"], "edits", f["title"], "added", f"theme {theme}")
        try:
            log(f"  footage: downloading {rec['source_id']} ({f['title'][:60]})")
            download(rec["source_id"], cfg)
        except Exception as e:
            log(f"  footage: download failed for {rec['source_id']}: {e}")
            continue
        tag(rec["source_id"], theme)
        new.append(rec["source_id"])
    for r in rejected:
        registry.mark_seen(r["url"], "edits", r["title"], "rejected", r["reason"])
    return new
