"""The ONLY place that calls Claude: `claude -p` as a locked-down subprocess.

- No tools, no MCP servers, no skills, no saved session, no user settings.
- Runs in an empty folder, so it cannot see any project files.
- Our prompt file replaces Claude Code's default system prompt (far fewer tokens).
- Output is forced to match a JSON schema.
- Every call (tokens, cost, time, errors) is logged to the llm_calls table.
"""
import json
import os
import shutil
import subprocess
import time

from pipeline.core import ledger
from pipeline.core.settings import ROOT, WORK
from pipeline.core.tools import NO_WINDOW

PROMPTS = ROOT / "prompts"
EMPTY_CWD = WORK / "_brain_cwd"


class BrainError(Exception):
    pass


def _env() -> dict:
    try:   # reuse MoneyPrinterTurbo: strips env vars that would switch away from subscription login
        from loguru import logger
        logger.remove()
        from app.services.llm import build_claude_code_env
        env, _removed = build_claude_code_env(dict(os.environ))
        return env
    except Exception:
        return {k: v for k, v in os.environ.items()
                if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_"))}


def call(*, stage: str, unit_id: str, prompt: str, user_text: str, schema: dict,
         model: str = "sonnet", max_turns: int = 3, timeout: int = 600,
         effort: str | None = None) -> dict:
    """Run one Claude call and return the parsed JSON object.

    prompt:    name of a file in prompts/ (without .md), used as the system prompt
    user_text: the data (transcript excerpts etc.), sent on stdin
    """
    EMPTY_CWD.mkdir(parents=True, exist_ok=True)
    system_prompt_file = PROMPTS / f"{prompt}.md"
    exe = shutil.which("claude") or "claude"
    cmd = [exe, "-p", "--output-format", "json", "--max-turns", str(max_turns),
           "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--no-session-persistence", "--setting-sources", "",
           "--model", model, "--system-prompt-file", str(system_prompt_file),
           "--json-schema", json.dumps(schema)]
    if effort:
        cmd += ["--effort", effort]
    t0 = time.time()
    log = dict(stage=stage, unit_id=unit_id, prompt=prompt, model=model)
    try:
        r = subprocess.run(cmd, input=user_text, capture_output=True, text=True, encoding="utf-8",
                           cwd=EMPTY_CWD, env=_env(), timeout=timeout, creationflags=NO_WINDOW)
        if r.returncode != 0 and not r.stdout.strip():
            raise BrainError(f"claude exited {r.returncode}: {r.stderr.strip()[:500]}")
        raw_dir = WORK / "_llm_raw"
        raw_dir.mkdir(exist_ok=True)
        (raw_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{stage}_{unit_id}_{prompt}.json").write_text(
            json.dumps({"input": user_text, "stdout": r.stdout, "stderr": r.stderr}, ensure_ascii=False),
            encoding="utf-8")
        out = json.loads(r.stdout)
        u = out.get("usage", {})
        log.update(input_tokens=u.get("input_tokens"),
                   cache_write_tokens=u.get("cache_creation_input_tokens"),
                   cache_read_tokens=u.get("cache_read_input_tokens"),
                   output_tokens=u.get("output_tokens"),
                   cost_usd=out.get("total_cost_usd"))
        if out.get("is_error") or out.get("subtype") != "success":
            raise BrainError(f"claude returned an error: {out.get('subtype')} {str(out.get('result'))[:300]}")
        data = out.get("structured_output")
        if data is None:
            data = json.loads(out.get("result", ""))
        ledger.log_call(**log, ok=1, seconds=round(time.time() - t0, 1))
        print(f"  claude [{prompt}] in={log['input_tokens']}+{log['cache_write_tokens']}w"
              f"+{log['cache_read_tokens']}r out={log['output_tokens']} "
              f"cost=${log['cost_usd'] or 0:.4f} {time.time() - t0:.0f}s")
        return data
    except Exception as e:
        ledger.log_call(**log, ok=0, seconds=round(time.time() - t0, 1), error=str(e)[:1000])
        raise BrainError(str(e)) from e
