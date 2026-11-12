"""Daily job: record YouTube performance of every video on the channel (fetch_analytics.py).

Runs in its own process, never opens a browser, and never stops the daily run if it fails
(e.g. sign-in expired: run `python fetch_analytics.py` once by hand to sign in again).
"""
import subprocess
import sys

from pipeline.core.settings import ROOT
from pipeline.core.tools import NO_WINDOW


def run(ctx):
    ctx.log("analytics: fetching YouTube stats")
    try:
        p = subprocess.run([sys.executable, str(ROOT / "fetch_analytics.py"), "--no-login"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        ctx.log("analytics: timed out (skipped)")
        return
    for line in (p.stdout + p.stderr).splitlines():
        if line.strip():
            ctx.log(f"   {line}")
    if p.returncode:
        ctx.log(f"analytics: failed (exit {p.returncode}); the rest of the run is unaffected")
