"""Moment selection with one `claude -p` call per source."""
from pipeline.core import claude_cli, registry
from pipeline.core.briefs import source_header
from pipeline.core.textprep import condensed_transcript
from pipeline.core.tools import write_json

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["candidates"],
    "properties": {"candidates": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "question", "angle", "start", "end", "visual_evidence", "risks"],
        "properties": {
            "topic": {"type": "string"},
            "question": {"type": "string", "description": "the viewer question the Short answers"},
            "angle": {"type": "string", "description": "what the Short explains that the film does not"},
            "start": {"type": "number"}, "end": {"type": "number"},
            "visual_evidence": {"type": "string"},
            "risks": {"type": "string", "description": "outdated claims, sensitivities, or 'none'"},
        }}}},
}


def run(unit, cfg):
    rec = registry.require_approved(unit.source_id)
    transcript = unit.json("source/transcript.json")
    shots = unit.json("source/shots.json")
    n = int(cfg.get("max_candidates", 4))
    text = "\n".join([
        source_header(rec),
        f"DURATION: {transcript['duration']:.0f} s, {len(shots['shots'])} shots",
        f"Return up to {n} candidates, best first.",
        "TRANSCRIPT ([start-end seconds] text):",
        condensed_transcript(transcript, cfg.get("block_seconds", 20)),
    ])
    out = claude_cli.call(stage="select", unit_id=unit.id, prompt=cfg.get("prompt", "select_moments"),
                          user_text=text, schema=SCHEMA, model=cfg.get("model", "sonnet"),
                          effort=cfg.get("effort"))
    cands = []
    for i, c in enumerate(out["candidates"][:n], 1):
        c["start"] = max(0.0, float(c["start"]))
        c["end"] = min(transcript["duration"], float(c["end"]))
        if c["end"] - c["start"] < 5:
            continue
        cands.append({"candidate_id": f"c{i}", **c})
    write_json(unit.path("source/candidates.json"), {"source_id": unit.source_id, "candidates": cands})
    print(f"  {len(cands)} candidates")
