"""Copy the Short to output/review/ with a sidecar JSON. Never uploads anything.
Also records the narration as 'produced' so future scripts are checked for repetition against it."""
import shutil
import time

from pipeline.core import ledger, registry
from pipeline.core.srt import make_srt
from pipeline.core.settings import REVIEW_DIR
from pipeline.core.tools import write_json


def run(unit, cfg):
    rec = registry.require_approved(unit.source_id)
    script = unit.json("short/script.json")
    cap = unit.json("short/captions.json")
    narration = " ".join(script["sentences"])
    description = "\n\n".join(filter(None, [
        script["description"],
        script["attribution"],
        f"Source: {rec['url']}",
        f"Licence: {rec['licence']}",
        cfg.get("description_footer", ""),
    ]))
    mp4 = REVIEW_DIR / f"{unit.id}.mp4"
    sidecar = REVIEW_DIR / f"{unit.id}.json"
    shutil.copyfile(unit.path("short/final.mp4"), mp4)
    srt = REVIEW_DIR / f"{unit.id}.srt"                  # subtitles for YouTube's subtitle upload
    srt.write_text(make_srt(cap), encoding="utf-8")
    write_json(sidecar, {
        "short_id": unit.id,
        "title": script["title"],
        "description": description,
        "privacy": "private",
        "subtitles_srt": srt.name,
        "duration_seconds": cap.get("final_duration", cap["total_duration"]),
        "source": {k: rec[k] for k in ("source_id", "url", "title", "owner", "licence", "commercial_use_allowed",
                                       "derivatives_allowed", "attribution_text", "restrictions",
                                       "licence_evidence", "date_checked")},
        "script": {"question": script["question"], "sentences": script["sentences"], "facts": script["facts"],
                   "shots": script["shots"], "source_window": script.get("window")},
        "scores": script["review"]["scores"],
        "review": {k: script["review"][k] for k in ("verdict", "model_verdict", "issues", "local")},
        "rewritten": script.get("rewritten", False),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    ledger.add_published(unit.id, unit.source_id, script["title"], narration)
    write_json(unit.path("short/package.json"), {"mp4": str(mp4), "sidecar": str(sidecar)})
    print(f"  -> {mp4}")
