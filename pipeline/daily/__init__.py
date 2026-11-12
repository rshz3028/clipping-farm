"""Daily jobs: run_daily.py runs the jobs listed in pipeline.toml [daily] jobs, in order.

A job is any module pipeline/daily/<name>.py with:
    def run(ctx) -> None
ctx (see Context) gives: ctx.args, ctx.cfg (its [daily.<name>] settings), ctx.state (today's
progress, saved to work/runs/<date>.json), ctx.save(), ctx.log(msg), ctx.need() (Shorts still to make).

To add a job (e.g. "schedule", "report"): create pipeline/daily/<name>.py and add its name to
[daily] jobs. To switch a job off: remove it from the list.
"""
import time
from dataclasses import dataclass, field

from pipeline.core import runner
from pipeline.core.tools import write_json


@dataclass
class Context:
    args: object
    state: dict
    state_file: object
    cfg: dict = field(default_factory=dict)

    def log(self, msg: str) -> None:
        runner._log(f"{time.strftime('%H:%M:%S')} {msg}")

    def save(self) -> None:
        write_json(self.state_file, self.state)

    def need(self) -> int:
        return self.state["target"] - len(self.state["made"])
