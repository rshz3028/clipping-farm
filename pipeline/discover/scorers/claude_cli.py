"""Fit scoring: ONE batched `claude -p` call for all candidates found in a discovery run."""
from pipeline.core import claude_cli

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["scores"],
    "properties": {"scores": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "fit", "reason", "topics"],
        "properties": {"id": {"type": "integer"}, "fit": {"type": "number", "minimum": 0, "maximum": 10},
                       "reason": {"type": "string"}, "topics": {"type": "array", "items": {"type": "string"}}}}}},
}


def score(candidates, cfg):
    lines = []
    for i, c in enumerate(candidates):
        lines.append(f"[{i}] {c['title']} ({c.get('year') or 'year?'}, {c['minutes']} min)\n"
                     f"    subjects: {c.get('subjects', '')}\n    description: {c['description'][:400]}")
    out = claude_cli.call(stage="discover", unit_id="discover", prompt=cfg.get("prompt", "score_sources"),
                          user_text="Score every film.\n\n" + "\n".join(lines), schema=SCHEMA,
                          model=cfg.get("model", "sonnet"), effort=cfg.get("effort"))
    res = {}
    for s in out["scores"]:
        if 0 <= s["id"] < len(candidates):
            res[candidates[s["id"]]["url"]] = {"fit": s["fit"], "reason": s["reason"], "topics": s["topics"]}
    return res
