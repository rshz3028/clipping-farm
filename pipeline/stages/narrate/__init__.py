"""Stage: narrate — speech for the script, with exact per-sentence timing. Contract: CONTRACTS.md."""
LEVEL = "short"
INPUTS = ["short/script.json"]
OUTPUTS = ["short/narration.wav", "short/narration.json"]
SHARED_SETTINGS = ["timing"]     # [timing] in pipeline.toml
