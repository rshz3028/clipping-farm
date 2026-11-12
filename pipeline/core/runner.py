"""Runs stages, decides what can be skipped, and isolates each run in its own process.

A stage is SKIPPED when its done-marker (work/.../.stages/<stage>.json) shows:
  - the same implementation and the same settings as now, and
  - its input files have not changed since, and
  - all its output files still exist.
Otherwise it re-runs. Because a re-run rewrites its outputs, the stages after
it see changed inputs and re-run too. Stages before it are untouched.

Each stage runs in a separate Python process, so the GPU and RAM are fully
released between stages (never two models loaded at once).
"""
import hashlib
import json
import os
import subprocess
import sys
import time

from pipeline.core import registry
from pipeline.core.settings import ROOT
from pipeline.core.stage import Unit, load_stage
from pipeline.core.tools import NO_WINDOW, read_json, write_json


class StageFailed(Exception):
    pass


class UsageLimit(StageFailed):
    """Claude reported a usage/rate limit. Stop the run; re-run later to continue."""


EXIT_USAGE_LIMIT = 3
KILLED_CODES = {-2, -15, 130, 143, 0xC000013A, -1073741510}   # Ctrl+C / terminate on Windows and Unix
LOG_FILE = None          # set by run_daily.py: every stage's output is also appended here


def _log(line: str) -> None:
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _fingerprint(spec) -> str:
    """Implementation + settings + any prompt files the settings name (editing a prompt re-runs the stage)."""
    prompts = {}
    for v in spec.cfg.values():
        if isinstance(v, str) and (ROOT / "prompts" / f"{v}.md").is_file():
            prompts[v] = hashlib.sha256((ROOT / "prompts" / f"{v}.md").read_bytes()).hexdigest()
    fp = {"impl": spec.impl_name, "cfg": spec.cfg}
    if prompts:
        fp["prompts"] = prompts
    blob = json.dumps(fp, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _input_stamps(unit: Unit, spec) -> dict:
    out = {}
    for ref in spec.inputs:
        p = unit.path(ref)
        out[ref] = p.stat().st_mtime_ns if p.exists() else None
    return out


def _marker(unit: Unit, stage: str):
    d = unit.dir / ".stages"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{stage}.json"


def is_current(unit: Unit, stage: str) -> bool:
    spec = load_stage(stage)
    m = _marker(unit, stage)
    if not m.exists():
        return False
    done = read_json(m)
    return (done.get("fingerprint") == _fingerprint(spec)
            and done.get("inputs") == _input_stamps(unit, spec)
            and all(unit.path(r).exists() for r in spec.outputs))


def run_stage_inprocess(stage: str, unit_id: str) -> None:
    """Called inside the child process: actually execute one stage."""
    unit = Unit(unit_id)
    spec = load_stage(stage)
    if spec.level != unit.kind:
        raise StageFailed(f"Stage '{stage}' works on a {spec.level}, but got {unit.kind} '{unit_id}'")
    registry.require_approved(unit.source_id)          # hard gate for every stage
    missing = [r for r in spec.inputs if not unit.path(r).exists()]
    if missing:
        raise StageFailed(f"{stage}: missing inputs {missing} (run the earlier stages first)")
    t0 = time.time()
    spec.implementation().run(unit, spec.cfg)
    missing = [r for r in spec.outputs if not unit.path(r).exists()]
    if missing:
        raise StageFailed(f"{stage} ({spec.impl_name}) did not produce {missing}")
    write_json(_marker(unit, stage), {
        "stage": stage, "impl": spec.impl_name, "fingerprint": _fingerprint(spec),
        "inputs": _input_stamps(unit, spec), "seconds": round(time.time() - t0, 1),
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


def run(stage: str, unit_id: str, force: bool = False) -> str:
    """Run one stage for one unit in a child process. Returns 'skipped' or 'done'."""
    unit = Unit(unit_id)
    registry.require_approved(unit.source_id)
    if not force and is_current(unit, stage):
        _log(f"[{stage}] {unit_id}: up to date, skipped")
        return "skipped"
    _log(f"[{stage}] {unit_id}: running ({load_stage(stage).impl_name})")
    cmd = [sys.executable, "-m", "pipeline", "_child", stage, unit_id]
    # No console window for the child; its output is piped back here and shown (and logged).
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                         text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=NO_WINDOW)
    log = open(LOG_FILE, "a", encoding="utf-8") if LOG_FILE else None
    try:
        for line in p.stdout:
            print(line, end="", flush=True)
            if log and "Warning" not in line:
                log.write(line.split("\r")[-1])
    finally:
        if log:
            log.close()
    returncode = p.wait()
    if returncode in KILLED_CODES:        # the stage was killed (Ctrl+C, closed window, shutdown): not a failure
        raise KeyboardInterrupt(f"[{stage}] {unit_id} was interrupted")
    if returncode == EXIT_USAGE_LIMIT:
        raise UsageLimit(f"[{stage}] {unit_id}: Claude usage limit reached")
    if returncode != 0:
        raise StageFailed(f"[{stage}] {unit_id}: failed (exit code {returncode})")
    return "done"
