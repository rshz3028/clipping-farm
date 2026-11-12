"""Daily job: free disk space.

- Sources whose Shorts are all made are marked 'used' and their big video file is deleted
  (transcript, shots, scripts and scores are kept: they are small and document each Short).
- Packaged Shorts lose their working copy of the video (the copy in output/ stays).
- Old raw Claude replies are deleted after N days.
Never touches output/review, output/approved or output/uploaded.
"""
import shutil
import time

from pipeline.core import registry
from pipeline.core.settings import SHORTS_DIR, SOURCES_DIR, WORK
from pipeline.core.shorts import is_packaged, source_exhausted


def _size(p):
    return p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _remove(p, freed):
    if p.exists():
        freed[0] += _size(p)
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def run(ctx):
    freed = [0]
    used = []
    if ctx.cfg.get("delete_used_sources", True):
        for r in registry.approved_sources("active"):
            sid = r["source_id"]
            if source_exhausted(sid):
                d = SOURCES_DIR / sid
                for name in ("source.mp4", "source.mp4.part", "_tmp"):
                    _remove(d / name, freed)
                registry.set_status(sid, "used")
                with registry.connect() as c:
                    c.execute("UPDATE sources SET local_path=NULL WHERE source_id=?", (sid,))
                used.append(sid)
    if ctx.cfg.get("delete_short_working_files", True):
        for d in SHORTS_DIR.glob("*__*"):
            if is_packaged(d.name):
                for name in ("final.mp4", "_tmp"):
                    _remove(d / name, freed)
    days = int(ctx.cfg.get("keep_llm_raw_days", 30))
    cutoff = time.time() - days * 86400
    for f in (WORK / "_llm_raw").glob("*.json"):
        if f.stat().st_mtime < cutoff:
            _remove(f, freed)
    ctx.state.setdefault("cleanup", []).append({"sources_used_up": used, "freed_mb": round(freed[0] / 1e6)})
    ctx.save()
    ctx.log(f"cleanup: {len(used)} sources used up {used if used else ''}; freed {freed[0] / 1e6:.0f} MB")
