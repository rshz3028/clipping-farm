"""Stage: check — originality/quality review, at most one rewrite. Contract: CONTRACTS.md."""
LEVEL = "source"
INPUTS = ["source/transcript.json", "source/shots.json", "source/shot_descriptions.json",
          "source/candidates.json", "source/scripts.json"]
OUTPUTS = ["source/checked.json"]
