"""Stage: select — up to N candidate Short topics per source, best first. Contract: CONTRACTS.md."""
LEVEL = "source"
INPUTS = ["source/transcript.json", "source/shots.json"]
OUTPUTS = ["source/candidates.json"]
