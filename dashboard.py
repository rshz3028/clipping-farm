"""Build and open the progress dashboard (output/dashboard.html).

    python dashboard.py               rebuild from saved data and open it in the browser
    python dashboard.py --no-open     rebuild only (used by the daily run)
    python dashboard.py --weekly      also run the weekly Claude review if it is due

No YouTube calls here: run `python fetch_analytics.py` first for fresh numbers
(the daily run does both automatically).
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
if Path(sys.prefix).resolve() != VENV.resolve():
    sys.exit(subprocess.call([str(VENV / "Scripts" / "python.exe"), str(Path(__file__).resolve()), *sys.argv[1:]]))

from pipeline.analytics import dashboard, weekly   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    args = ap.parse_args()
    if args.weekly:
        weekly.run()
    page = dashboard.build(open_browser=not args.no_open)
    print(f"Dashboard: {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
