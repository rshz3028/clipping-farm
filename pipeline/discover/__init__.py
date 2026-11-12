"""Source discovery: finds new archival films and adds the ones that qualify to the registry.

Plug-ins:
  pipeline/discover/finders/<name>.py   one per archive. Must provide:
        NAME = "<name>"
        search(cfg, known_urls: set) -> (candidates, rejected)
            candidates: [{"url", "title", "description", "year", "minutes", "subjects", "record"}]
                        "record" is a full registry row whose licence has ALREADY been verified
                        on the source's own page (commercial use + derivatives allowed).
            rejected:   [{"url", "title", "reason"}]
  pipeline/discover/scorers/<name>.py   judges how well each candidate fits the channel:
        score(candidates, cfg) -> {url: {"fit": 0-10, "reason": str, "topics": [str]}}

Which finders / scorer run, and their settings, are in pipeline.toml under [discover].
Every URL checked (added or rejected) is remembered, so it is never checked twice.
"""
import importlib
import time

from pipeline.core import registry
from pipeline.core.settings import CONFIG


def _cfg() -> dict:
    return dict(CONFIG.get("discover", {}))


def discover(max_new: int | None = None, log=print) -> list[str]:
    cfg = _cfg()
    max_new = int(max_new if max_new is not None else cfg.get("max_new", 5))
    known = registry.known_urls()
    candidates = []
    for name in cfg.get("finders", []):
        fcfg = dict(cfg.get(name, {}))
        finder = importlib.import_module(f"pipeline.discover.finders.{name}")
        try:
            found, rejected = finder.search(fcfg, known)
        except Exception as e:
            log(f"  finder {name} failed: {e}")
            continue
        for r in rejected:
            registry.mark_seen(r["url"], name, r.get("title"), "rejected", r["reason"])
            known.add(r["url"])
        for c in found:
            c["finder"] = name
            known.add(c["url"])
        log(f"  {name}: {len(found)} candidates passed licence/length/content checks, {len(rejected)} rejected")
        candidates += found
    if not candidates:
        return []

    candidates = candidates[: int(cfg.get("max_to_score", 30))]
    scorer = importlib.import_module(f"pipeline.discover.scorers.{cfg.get('scorer', 'claude_cli')}")
    scores = scorer.score(candidates, dict(cfg.get("scorer_settings", {})))
    min_fit = float(cfg.get("min_fit", 7))
    ranked = sorted(candidates, key=lambda c: -scores.get(c["url"], {}).get("fit", 0))
    added = []
    for c in ranked:
        s = scores.get(c["url"], {"fit": 0, "reason": "not scored"})
        if s["fit"] < min_fit or len(added) >= max_new:
            reason = (f"fit {s['fit']}: {s['reason']}" if s["fit"] < min_fit
                      else f"fit {s['fit']} but daily limit reached")
            if s["fit"] < min_fit:                    # good-but-over-limit ones are retried next time
                registry.mark_seen(c["url"], c["finder"], c["title"], "rejected", reason)
            continue
        rec = dict(c["record"])
        rec["source_id"] = _unique_id(rec["source_id"])
        rec["added_by"] = f"auto:{c['finder']}"
        rec["added_on"] = time.strftime("%Y-%m-%d")
        rec["licence_evidence"] += f" | fit {s['fit']}/10: {s['reason']}"
        registry.upsert(rec)
        registry.mark_seen(c["url"], c["finder"], c["title"], "added", f"fit {s['fit']}")
        added.append(rec["source_id"])
        log(f"  + {rec['source_id']}  (fit {s['fit']}) {c['title']}")
    return added


def _unique_id(base: str) -> str:
    existing = {r["source_id"] for r in registry.approved_sources()}
    sid, n = base, 2
    while sid in existing:
        sid, n = f"{base}_{n}", n + 1
    return sid
