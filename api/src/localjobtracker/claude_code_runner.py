"""ClaudeCodeRunner: the only module that knows about the Claude Code CLI (D-20).

Flags follow planning/runner-notes.md, checked against Claude Code 2.1.289. Every run is
restricted: no tools, no MCP servers, no settings files from the working folder, and no
prompts that could wait for an answer. A dollar cap limits each run.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from localjobtracker.runner import RunResult

DEFAULT_TIMEOUT_S = 180
# The CLI's budget cap is an estimate, not a strict limit (runner-notes.md). Leave a margin.
MAX_BUDGET_USD = "0.25"


def build_args(executable: str, prompt: str) -> list[str]:
    return [
        executable,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--restricted",
        "--strict-mcp-config",
        "--tools",
        "",
        "--permission-prompts",
        "none",
        "--no-session-persistence",
        "--max-budget-usd",
        MAX_BUDGET_USD,
    ]


def parse_output(stdout: str, exit_code: int, duration_ms: int) -> RunResult:
    """Read the final `result` message. A failure inside a run can print on stdout with exit 0."""
    try:
        message: Any = json.loads(stdout)
    except json.JSONDecodeError:
        return RunResult(
            ok=False,
            error=f"Claude Code did not return JSON (exit {exit_code}).",
            duration_ms=duration_ms,
        )
    if not isinstance(message, dict):
        return RunResult(
            ok=False, error="Unexpected output from Claude Code.", duration_ms=duration_ms
        )

    cost = message.get("total_cost_usd")
    cost_usd = float(cost) if isinstance(cost, int | float) else None
    if exit_code != 0 or message.get("is_error"):
        reason = message.get("subtype") or f"exit {exit_code}"
        return RunResult(
            ok=False,
            error=f"Claude Code run failed ({reason}).",
            duration_ms=duration_ms,
            cost_usd=cost_usd,
        )
    return RunResult(
        ok=True,
        text=str(message.get("result", "")),
        duration_ms=duration_ms,
        cost_usd=cost_usd,
    )


class ClaudeCodeRunner:
    def __init__(self, workdir: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.workdir = workdir
        self.timeout_s = timeout_s

    def run(self, prompt: str) -> RunResult:
        executable = shutil.which("claude")
        if executable is None:
            return RunResult(ok=False, error="The claude command was not found on PATH.")
        self.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                build_args(executable, prompt),
                cwd=self.workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                ok=False, error=f"Claude Code did not finish in {self.timeout_s:.0f} s."
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        return parse_output(completed.stdout, completed.returncode, duration_ms)
