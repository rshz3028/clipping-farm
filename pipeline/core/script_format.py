"""The script format every script/check implementation must produce (see CONTRACTS.md)."""
from pipeline.core.briefs import allowed_shot_ids

SCRIPT_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["candidate_id", "title", "question", "sentences", "shots", "description", "facts", "attribution"],
    "properties": {
        "candidate_id": {"type": "string"},
        "title": {"type": "string"},
        "question": {"type": "string"},
        "sentences": {"type": "array", "items": {"type": "string"}},
        "shots": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["shot", "sentence", "reason"],
            "properties": {"shot": {"type": "integer"}, "sentence": {"type": "integer"},
                           "reason": {"type": "string"}}}},
        "description": {"type": "string"},
        "facts": {"type": "array", "items": {"type": "string"}},
        "attribution": {"type": "string"},
    },
}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["scripts"],
          "properties": {"scripts": {"type": "array", "items": SCRIPT_ITEM}}}


def clean_script(s: dict, rec, transcript, shots, cand, pad, wps: float) -> dict:
    """Local validation: keep only allowed shots, fix attribution, add timing estimates."""
    allowed = allowed_shot_ids(transcript, shots, cand, pad)
    n_sent = len(s["sentences"])
    s["shots"] = [x for x in s["shots"] if x["shot"] in allowed and 0 <= x["sentence"] < n_sent]
    s["attribution"] = rec["attribution_text"]          # always the registry text, never the model's
    words = sum(len(t.split()) for t in s["sentences"])
    by_id = {sh["i"]: sh for sh in shots["shots"]}
    s["word_count"] = words
    s["est_seconds"] = round(words / wps, 1)
    s["footage_seconds"] = round(sum(by_id[x["shot"]]["end"] - by_id[x["shot"]]["start"] for x in s["shots"]), 1)
    s["source_id"] = rec["source_id"]
    s["window"] = [cand["start"], cand["end"]]
    return s
