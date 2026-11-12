"""Weekly Claude review of what works (proposals only; nothing is changed automatically).

Runs at most once every `[analytics] weekly_every_days` days, and only when at least
`[analytics] weekly_min_videos` public videos are old enough (7 days) to judge.
Output: work/analytics/proposals/<date>.md  (also shown on the dashboard).
1 Claude call per run.
"""
import datetime as dt
import json

from pipeline.core import claude_cli
from pipeline.core.settings import CONFIG, WORK
from pipeline.analytics import scorecard

CFG = CONFIG.get("analytics", {})
OUT = WORK / "analytics" / "proposals"

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "what_works": {"type": "array", "items": {"type": "string"}},
        "what_fails": {"type": "array", "items": {"type": "string"}},
        "proposals": {"type": "array", "items": {
            "type": "object",
            "properties": {"target": {"type": "string"}, "change": {"type": "string"},
                           "evidence": {"type": "string"}, "confidence": {"type": "string"}},
            "required": ["target", "change", "evidence", "confidence"]}},
        "next_experiment": {"type": "string"},
    },
    "required": ["summary", "what_works", "what_fails", "proposals", "next_experiment"],
}


def latest():
    files = sorted(OUT.glob("*.md")) if OUT.exists() else []
    return files[-1] if files else None


def due():
    """(is_due, reason)"""
    if not CFG.get("weekly_review", False):
        return False, "weekly review is off ([analytics] weekly_review = false)"
    last = latest()
    every = CFG.get("weekly_every_days", 7)
    if last and (dt.date.today() - dt.date.fromisoformat(last.stem[:10])).days < every:
        return False, f"last review {last.stem} (< {every} days ago)"
    data = scorecard.build()
    ready = [v for v in data["videos"] if v["privacy"] == "public" and (v["age_days"] or 0) >= 7]
    need = CFG.get("weekly_min_videos", 20)
    if len(ready) < need:
        return False, f"only {len(ready)} public videos are 7+ days old (need {need})"
    return True, data


def run(log=print):
    ok, data = due()
    if not ok:
        log(f"weekly review: skipped ({data})")
        return None
    keep = ("title", "kind", "topic", "hook_text", "track", "music_style", "duration_s", "age_days",
            "views", "engaged_views", "views_d2", "views_d7", "outlier_d7", "avg_view_pct", "hook_ret",
            "mid_ret", "end_ret", "rel_perf", "viewed_pct", "feed_share", "subs_gained", "shares")
    vids = [{k: v[k] for k in keep} | {"diagnosis": v["diagnosis"]["label"]}
            for v in data["videos"] if v["privacy"] == "public"]
    payload = json.dumps({"channel_medians": data["medians"], "videos": vids}, ensure_ascii=False, default=str)
    today = dt.date.today().isoformat()
    try:
        r = claude_cli.call(stage="analytics", unit_id=today, prompt="weekly_analytics",
                            user_text=payload, schema=SCHEMA)
    except Exception as e:                      # never break the daily run
        log(f"weekly review: Claude call failed ({str(e)[:200]})")
        return None
    lines = [f"# Weekly review {today}", "", r["summary"], "", "## What works"]
    lines += [f"- {x}" for x in r["what_works"]] + ["", "## What fails"]
    lines += [f"- {x}" for x in r["what_fails"]] + ["", "## Proposals (owner decides)"]
    for p in r["proposals"]:
        lines += [f"- **{p['target']}**: {p['change']}  ", f"  evidence: {p['evidence']} (confidence: {p['confidence']})"]
    lines += ["", "## Next experiment", r["next_experiment"], ""]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{today}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    log(f"weekly review: written {path}")
    return path
