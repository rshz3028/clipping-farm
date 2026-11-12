"""Stage: package — finished MP4 + JSON sidecar into output/review/. Contract: CONTRACTS.md."""
LEVEL = "short"
INPUTS = ["short/final.mp4", "short/script.json", "short/captions.json"]
OUTPUTS = ["short/package.json"]
SHARED_SETTINGS = ["timing"]     # [timing] in pipeline.toml
