"""Stage: captions — word timings + styled ASS subtitle file (captions, header, end card). Contract: CONTRACTS.md."""
LEVEL = "short"
INPUTS = ["short/script.json", "short/narration.wav", "short/narration.json"]
OUTPUTS = ["short/captions.json", "short/captions.ass"]
SHARED_SETTINGS = ["timing"]     # [timing] in pipeline.toml
