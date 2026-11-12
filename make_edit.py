"""Make one beat-synced music edit now (same code as the daily "edits" job).

    python make_edit.py                       # theme "jets", length from pipeline.toml [edits]
    python make_edit.py --seconds 25 --seed 3

Picks a licensed NCS phonk track in the style trending on YouTube Shorts, cuts registered NASA
B-roll on its beat, writes output/edits_review/edit_<theme>_<time>.mp4 + .json (title, description
with all credits). Settings: pipeline.toml [edits].
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
if Path(sys.prefix).resolve() != VENV.resolve():
    sys.exit(subprocess.call([str(VENV / "Scripts" / "python.exe"), str(Path(__file__).resolve()), *sys.argv[1:]]))

from pipeline.edits.make import make_one   # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--theme", default="jets")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    make_one(a.theme, a.seconds, a.seed)
