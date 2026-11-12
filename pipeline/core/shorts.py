"""Short units: work/shorts/<source_id>__<candidate_id>/, created from passing scripts.

A Short is FROZEN once packaged: later changes to settings or prompts never touch it again
(its review video and sidecar stay exactly as made)."""
import json

from pipeline.core.settings import SHORTS_DIR
from pipeline.core.stage import Unit
from pipeline.core.tools import write_json


def is_packaged(short_id: str) -> bool:
    return (SHORTS_DIR / short_id / ".stages" / "package.json").exists()


def pending_shorts() -> list[str]:
    """Shorts whose script passed but which are not packaged yet (e.g. after an interruption)."""
    return [d.name for d in sorted(SHORTS_DIR.glob("*__*"))
            if (d / "script.json").exists() and not is_packaged(d.name)]


def materialize(source_id: str) -> list[str]:
    """Create a folder + script.json for every script that passed the check. Returns short ids."""
    checked = Unit(source_id).json("source/checked.json")
    ids = []
    for res in checked["results"]:
        if res["verdict"] != "pass":
            continue
        short = Unit(f"{source_id}__{res['candidate_id']}")
        if is_packaged(short.id):           # frozen
            ids.append(short.id)
            continue
        data = dict(res["script"])
        data["review"] = res.get("second_review") or res["first_review"]
        data["rewritten"] = res["rewritten"]
        p = short.path("short/script.json")
        # only rewrite when content changed, so later stages are not re-run needlessly
        if not p.exists() or json.loads(p.read_text(encoding="utf-8")) != json.loads(json.dumps(data)):
            write_json(p, data)
        ids.append(short.id)
    return ids


def source_exhausted(source_id: str) -> bool:
    """True when the source's check has run and every passing script has been made into a Short."""
    u = Unit(source_id)
    if not (u.source_dir / ".stages" / "check.json").exists():
        return False
    passing = [r for r in u.json("source/checked.json")["results"] if r["verdict"] == "pass"]
    return all(is_packaged(f"{source_id}__{r['candidate_id']}") for r in passing)
