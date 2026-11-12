"""Script writing: ONE `claude -p` call writes scripts for all chosen candidates of a source."""
from pipeline.core import claude_cli, registry
from pipeline.core.briefs import candidate_brief, load_shots
from pipeline.core.script_format import SCHEMA, clean_script
from pipeline.core.shorts import is_packaged
from pipeline.core.tools import write_json



def run(unit, cfg):
    rec = registry.require_approved(unit.source_id)
    transcript = unit.json("source/transcript.json")
    shots = load_shots(unit)
    # skip topics whose Short is already finished (frozen); take the next unused ones instead
    cands = [c for c in unit.json("source/candidates.json")["candidates"]
             if not is_packaged(f"{unit.source_id}__{c['candidate_id']}")][: int(cfg.get("scripts_per_source", 2))]
    pad = float(cfg.get("window_padding", 45))
    if not cands:
        write_json(unit.path("source/scripts.json"), {"source_id": unit.source_id, "scripts": []})
        return
    briefs = "\n\n".join(candidate_brief(rec, transcript, shots, c, pad) for c in cands)
    out = claude_cli.call(stage="script", unit_id=unit.id, prompt=cfg.get("prompt", "write_script"),
                          user_text=(f"Write one script per brief ({len(cands)} briefs).\n"
                                     f"LENGTH: {cfg['min_words']}-{cfg['max_words']} words per script.\n\n{briefs}"),
                          schema=SCHEMA, model=cfg.get("model", "sonnet"), effort=cfg.get("effort"))
    by_cid = {c["candidate_id"]: c for c in cands}
    scripts = [clean_script(s, rec, transcript, shots, by_cid[s["candidate_id"]], pad,
                            cfg.get("words_per_second", 2.5))
               for s in out["scripts"] if s["candidate_id"] in by_cid]
    write_json(unit.path("source/scripts.json"), {"source_id": unit.source_id, "scripts": scripts})
    print(f"  {len(scripts)} scripts")
