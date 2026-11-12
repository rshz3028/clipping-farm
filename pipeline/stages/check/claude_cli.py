"""Originality check: local measurements + one batched `claude -p` review per source.
Scripts sent back for rewrite are rewritten in ONE batched call and re-checked in ONE call.
At most one rewrite per script; anything still failing is rejected."""
from pipeline.core import claude_cli, ledger, registry
from pipeline.core.briefs import candidate_brief, load_shots
from pipeline.core.textprep import longest_copied_run, similarity, words_between
from pipeline.core.tools import write_json
from pipeline.core.script_format import SCHEMA as SCRIPT_SCHEMA, clean_script

SCORE_KEYS = ["narrative_independence", "original_explanation", "educational_value",
              "source_dependence", "repetition", "factual_confidence"]
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reviews"],
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["candidate_id", "scores", "verdict", "issues", "rewrite_instructions"],
        "properties": {
            "candidate_id": {"type": "string"},
            "scores": {"type": "object", "additionalProperties": False, "required": SCORE_KEYS,
                       "properties": {k: {"type": "number", "minimum": 0, "maximum": 10} for k in SCORE_KEYS}},
            "verdict": {"type": "string", "enum": ["pass", "rewrite", "reject"]},
            "issues": {"type": "array", "items": {"type": "string"}},
            "rewrite_instructions": {"type": "string"},
        }}}},
}


def _narration(s):
    return " ".join(s["sentences"])


def _local(s, transcript, published):
    full_source = " ".join(seg["text"] for seg in transcript["segments"])
    n, txt = longest_copied_run(_narration(s), full_source)
    sims = sorted(({"short_id": p["short_id"], "title": p["title"],
                    "similarity": round(similarity(_narration(s), p["narration"]), 3), "narration": p["narration"]}
                   for p in published), key=lambda x: -x["similarity"])[:3]
    return {"copied_run_words": n, "copied_text": txt,
            "max_prior_similarity": sims[0]["similarity"] if sims else 0.0, "similar_published": sims}


def _review_text(scripts, locals_, transcript, pad):
    parts = []
    for s in scripts:
        loc = locals_[s["candidate_id"]]
        a, b = max(0, s["window"][0] - pad), s["window"][1] + pad
        similar = "\n".join(f"  - ({p['similarity']}) {p['title']}: {p['narration']}"
                            for p in loc["similar_published"]) or "  (none published yet)"
        parts.append("\n".join([
            f"=== SCRIPT candidate_id={s['candidate_id']} ===",
            f"TITLE: {s['title']}", f"QUESTION: {s['question']}",
            f"NARRATION ({s['word_count']} words): {_narration(s)}",
            "FACT CLAIMS:", *[f"  - {f}" for f in s["facts"]],
            f"LONGEST PHRASE COPIED FROM SOURCE: {loc['copied_run_words']} words: \"{loc['copied_text']}\"",
            "MOST SIMILAR PUBLISHED SCRIPTS:", similar,
            "SOURCE TRANSCRIPT FOR THIS WINDOW:", words_between(transcript, a, b),
        ]))
    return "\n\n".join(parts)


def _apply_thresholds(review, loc, th):
    """The model's verdict can only be made stricter by the local rules, never looser."""
    sc, fails = review["scores"], []
    if sc["narrative_independence"] < th["min_narrative_independence"]: fails.append("narrative_independence too low")
    if sc["original_explanation"] < th["min_original_explanation"]: fails.append("original_explanation too low")
    if sc["educational_value"] < th["min_educational_value"]: fails.append("educational_value too low")
    if sc["source_dependence"] > th["max_source_dependence"]: fails.append("source_dependence too high")
    if sc["repetition"] > th["max_repetition"]: fails.append("repetition too high")
    if sc["factual_confidence"] < th["min_factual_confidence"]: fails.append("factual_confidence too low")
    if loc["copied_run_words"] > th["max_copied_words"]:
        fails.append(f"copies {loc['copied_run_words']} consecutive words from the source")
    if loc["max_prior_similarity"] > th["max_prior_similarity"]: fails.append("too similar to a published script")
    verdict = review["verdict"]
    if verdict == "pass" and fails:
        verdict = "rewrite"
    return verdict, fails


def _review(unit, cfg, scripts, transcript, published, pad):
    locals_ = {s["candidate_id"]: _local(s, transcript, published) for s in scripts}
    out = claude_cli.call(stage="check", unit_id=unit.id, prompt=cfg.get("prompt", "check_originality"),
                          user_text=_review_text(scripts, locals_, transcript, pad),
                          schema=REVIEW_SCHEMA, model=cfg.get("model", "sonnet"), effort=cfg.get("effort"))
    reviews = {r["candidate_id"]: r for r in out["reviews"]}
    results = {}
    for s in scripts:
        cid = s["candidate_id"]
        r = reviews.get(cid) or {"scores": {k: 0 for k in SCORE_KEYS}, "verdict": "reject",
                                 "issues": ["reviewer returned no review"], "rewrite_instructions": ""}
        verdict, fails = _apply_thresholds(r, locals_[cid], cfg["thresholds"])
        loc = {k: v for k, v in locals_[cid].items() if k != "similar_published"}
        loc["similar_published"] = [{k: v for k, v in p.items() if k != "narration"}
                                    for p in locals_[cid]["similar_published"]]
        results[cid] = {"verdict": verdict, "model_verdict": r["verdict"], "scores": r["scores"],
                        "issues": r["issues"] + fails, "rewrite_instructions": r["rewrite_instructions"],
                        "local": loc}
    return results


def run(unit, cfg):
    rec = registry.require_approved(unit.source_id)
    transcript = unit.json("source/transcript.json")
    shots = load_shots(unit)
    cands = {c["candidate_id"]: c for c in unit.json("source/candidates.json")["candidates"]}
    scripts = unit.json("source/scripts.json")["scripts"]
    pad = float(cfg.get("window_padding", 45))
    published = ledger.published_scripts()
    final = []
    if scripts:
        first = _review(unit, cfg, scripts, transcript, published, pad)
        need = [s for s in scripts if first[s["candidate_id"]]["verdict"] == "rewrite"]
        second, rewritten = {}, {}
        if need and int(cfg.get("max_rewrites", 1)) >= 1:
            briefs = []
            for s in need:
                rv = first[s["candidate_id"]]
                briefs.append("\n".join([
                    candidate_brief(rec, transcript, shots, cands[s["candidate_id"]], pad),
                    "CURRENT SCRIPT:", f"TITLE: {s['title']}", "SENTENCES:",
                    *[f"  {i}. {t}" for i, t in enumerate(s["sentences"])],
                    "CURRENT SHOT LIST (shot -> sentence index):",
                    *[f"  S{x['shot']} -> {x['sentence']} ({x['reason']})" for x in s["shots"]],
                    "REVIEWER ISSUES:", *[f"  - {x}" for x in rv["issues"]],
                    f"REWRITE INSTRUCTIONS: {rv['rewrite_instructions']}",
                ]))
            out = claude_cli.call(stage="check", unit_id=unit.id, prompt=cfg.get("rewrite_prompt", "rewrite_script"),
                                  user_text=(f"LENGTH: {cfg['min_words']}-{cfg['max_words']} words per script.\n\n"
                                             + "\n\n".join(briefs)), schema=SCRIPT_SCHEMA,
                                  model=cfg.get("model", "sonnet"), effort=cfg.get("effort"))
            old = {s["candidate_id"]: s for s in need}
            for s in out["scripts"]:
                cid = s["candidate_id"]
                if cid not in old:
                    continue
                new = clean_script(s, rec, transcript, shots, cands[cid], pad, cfg.get("words_per_second", 2.5))
                if not new["shots"]:      # rewrite lost the shot list: keep the old one, clamp indices
                    last = len(new["sentences"]) - 1
                    s["shots"] = [dict(x, sentence=min(x["sentence"], last)) for x in old[cid]["shots"]]
                    new = clean_script(s, rec, transcript, shots, cands[cid], pad, cfg.get("words_per_second", 2.5))
                rewritten[cid] = new
            if rewritten:
                second = _review(unit, cfg, list(rewritten.values()), transcript, published, pad)
        for s in scripts:
            cid = s["candidate_id"]
            entry = {"candidate_id": cid, "first_review": first[cid], "rewritten": cid in rewritten}
            if cid in rewritten:
                rv = second[cid]
                entry["second_review"] = rv
                entry["script"] = rewritten[cid]
                entry["verdict"] = "pass" if rv["verdict"] == "pass" else "reject"   # no second rewrite
            else:
                entry["script"] = s
                entry["verdict"] = first[cid]["verdict"] if first[cid]["verdict"] != "rewrite" else "reject"
            final.append(entry)
    write_json(unit.path("source/checked.json"), {"source_id": unit.source_id, "results": final})
    print("  " + ", ".join(f"{e['candidate_id']}={e['verdict']}" for e in final))
