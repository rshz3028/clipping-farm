"""Daily run:  python run_daily.py --count N

Runs the jobs listed in pipeline.toml [daily] jobs, in order. By default:
  discover  find + add new sources when unused ones run low
  produce   make Shorts until N are in output/review for today
  cleanup   free disk space (used-up source videos, working copies, old logs)

Safe to stop at any time and run again: finished work is skipped and today's progress is kept
in work/runs/<date>.json. Nothing is uploaded; see upload_youtube.py.

  --count N        Shorts to make today (default 2)
  --source ID      only use this source (can repeat)
  --jobs a,b       run only these jobs this time (e.g. --jobs discover)
"""
import argparse
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
if Path(sys.prefix).resolve() != VENV.resolve():   # always use the project's own Python
    sys.exit(subprocess.call([str(VENV / "Scripts" / "python.exe"), str(Path(__file__).resolve()), *sys.argv[1:]]))

import msvcrt                                       # noqa: E402
import time                                         # noqa: E402

from pipeline.core import ledger, runner            # noqa: E402
from pipeline.core.settings import CONFIG, WORK     # noqa: E402
from pipeline.core.tools import read_json           # noqa: E402
from pipeline.daily import Context                  # noqa: E402


def acquire_lock():
    """Only one run at a time. Windows releases the lock automatically if the run dies."""
    f = open(WORK / "run.lock", "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit("Another run_daily.py is already running. Wait for it to finish.")
    return f


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--jobs", default="")
    args = ap.parse_args()

    lock = acquire_lock()
    today = time.strftime("%Y-%m-%d")
    for d in ("runs", "logs"):
        (WORK / d).mkdir(exist_ok=True)
    runner.LOG_FILE = WORK / "logs" / f"{today}.log"
    state_file = WORK / "runs" / f"{today}.json"
    state = read_json(state_file) if state_file.exists() else {"date": today, "made": []}
    state["target"] = args.count
    state["failed"] = {}            # failures are only skipped within one run; a new run retries them
    daily = CONFIG.get("daily", {})
    jobs = [j for j in (args.jobs.split(",") if args.jobs else daily.get("jobs", ["produce"])) if j]

    ctx = Context(args=args, state=state, state_file=state_file)
    ctx.save()
    ctx.log(f"=== run_daily: {len(state['made'])}/{args.count} Shorts made today; jobs: {', '.join(jobs)} ===")
    stopped = None
    try:
        for job in jobs:
            ctx.cfg = dict(daily.get(job, {}))
            importlib.import_module(f"pipeline.daily.{job}").run(ctx)
    except runner.UsageLimit as e:
        stopped = f"Claude usage limit reached ({e}). Run again later to continue."
    except KeyboardInterrupt:
        stopped = "Stopped. Run again to continue where it left off."

    calls = ledger.calls_today()
    ok = [c for c in calls if c["ok"]]
    tok_in = sum((c["input_tokens"] or 0) + (c["cache_write_tokens"] or 0) + (c["cache_read_tokens"] or 0) for c in ok)
    ctx.log("=== summary ===")
    ctx.log(f"Shorts made today: {len(state['made'])}/{state['target']}")
    for eid in state.get("edits_made", []):
        ctx.log(f"   edit: output/edits_review/{eid}.mp4")
    for sid in state["made"]:
        ctx.log(f"   output/review/{sid}.mp4")
    for k, v in state["failed"].items():
        ctx.log(f"   failed: {k}: {v}")
    ctx.log(f"Claude calls today: {len(calls)} ({len(calls) - len(ok)} failed), "
            f"{tok_in} input + {sum(c['output_tokens'] or 0 for c in ok)} output tokens")
    if stopped:
        ctx.log(stopped)
    lock.close()
    if "produce" not in jobs:
        return 0 if not stopped else 1
    return 0 if ctx.need() <= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
