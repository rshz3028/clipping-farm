"""Stage: render — the finished vertical video. Contract: CONTRACTS.md."""
LEVEL = "short"
INPUTS = ["source/source.mp4", "source/shots.json", "short/script.json",
          "short/narration.wav", "short/narration.json", "short/captions.json", "short/captions.ass"]
OUTPUTS = ["short/final.mp4"]
SHARED_SETTINGS = ["timing"]     # [timing] in pipeline.toml
