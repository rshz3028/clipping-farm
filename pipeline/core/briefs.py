"""Builds the compact text 'briefs' that brain stages send to an LLM (any LLM)."""
from pipeline.core.textprep import shots_in_window, words_between


def load_shots(unit) -> dict:
    """shots.json plus the describe stage's descriptions (if any), for briefs."""
    shots = unit.json("source/shots.json")
    p = unit.path("source/shot_descriptions.json")
    if p.exists():
        shots["_descriptions"] = unit.json("source/shot_descriptions.json").get("descriptions", {})
    return shots


def window(candidate: dict, duration: float, pad: float) -> tuple[float, float]:
    return max(0.0, candidate["start"] - pad), min(duration, candidate["end"] + pad)


def source_header(rec: dict) -> str:
    return (f"SOURCE: {rec['title']}\nOWNER: {rec['owner']}\nLICENCE: {rec['licence']}\n"
            f"RESTRICTIONS: {rec['restrictions']}\nATTRIBUTION: {rec['attribution_text']}")


def candidate_brief(rec, transcript, shots, cand, pad) -> str:
    a, b = window(cand, transcript["duration"], pad)
    return "\n".join([
        f"=== BRIEF candidate_id={cand['candidate_id']} ===",
        source_header(rec),
        f"TOPIC: {cand['topic']}",
        f"QUESTION: {cand['question']}",
        f"ANGLE: {cand.get('angle', '')}",
        f"WINDOW: {a:.1f}-{b:.1f} s",
        "TRANSCRIPT OF WINDOW:",
        words_between(transcript, a, b),
        "SHOTS AVAILABLE (only these may be used):",
        shots_in_window(transcript, shots, a, b),
    ])


def allowed_shot_ids(transcript, shots, cand, pad) -> set[int]:
    a, b = window(cand, transcript["duration"], pad)
    return {s["i"] for s in shots["shots"] if s["end"] > a and s["start"] < b}
