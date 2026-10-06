"""ClaudeCodeRunner: the only module that knows about the Claude Code CLI (D-20).

Flags follow planning/runner-notes.md, checked against Claude Code 2.1.289. Every run is
restricted: no tools, no MCP servers, no settings files from the working folder, and no
prompts that could wait for an answer. A dollar cap limits each run.

Output is read as stream-json. A plan limit shows up as a `rate_limit_event` (or an
`api_retry` with category `rate_limit`) and is raised as RateLimitError (D-63).
"""

import json
import shutil
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from localjobtracker.runner import RateLimitError, RunResult

DEFAULT_TIMEOUT_S = 180
# How often a running CLI is checked for a cancel request or a timeout.
POLL_INTERVAL_S = 0.2
# The CLI's budget cap is an estimate, not a strict limit (runner-notes.md). Leave a margin.
MAX_BUDGET_USD = "0.25"
# rate_limit_info.status values that mean the run may continue. Any other status is a limit.
ALLOWED_RATE_LIMIT_STATUSES = frozenset({"allowed", "allowed_warning"})


def build_args(executable: str, prompt: str) -> list[str]:
    return [
        executable,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
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


def _events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event: Any = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _rate_limit(events: list[dict[str, Any]]) -> RateLimitError | None:
    """Return the limit error if the stream reports one. Field names follow runner-notes.md."""
    for event in events:
        if event.get("type") == "rate_limit_event":
            info: Any = event.get("rate_limit_info")
            if isinstance(info, dict) and info.get("status") not in ALLOWED_RATE_LIMIT_STATUSES:
                return RateLimitError(
                    "The Claude plan limit was reached.", _reset_time(info.get("resetsAt"))
                )
        if event.get("subtype") == "api_retry" and event.get("error_category") == "rate_limit":
            return RateLimitError("The Claude plan limit was reached.")
    results = [event for event in events if event.get("type") == "result"]
    if results and results[-1].get("api_error_status") == 429:
        return RateLimitError("The Claude plan limit was reached.")
    return None


def _reset_time(value: object) -> datetime | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC)
    return None


def parse_stream(stdout: str, exit_code: int, duration_ms: int) -> RunResult:
    """Read a stream-json run. Raises RateLimitError on a plan limit.

    The final `result` message carries the text. A failure inside a run can print on stdout
    with exit 0, so the result's own flags are checked too.
    """
    events = _events(stdout)
    limit = _rate_limit(events)
    if limit is not None:
        raise limit

    results = [event for event in events if event.get("type") == "result"]
    if not results:
        return RunResult(
            ok=False,
            error=f"Claude Code returned no result (exit {exit_code}).",
            duration_ms=duration_ms,
        )
    message = results[-1]
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

    def run(self, prompt: str, cancel: threading.Event | None = None) -> RunResult:
        executable = shutil.which("claude")
        if executable is None:
            return RunResult(ok=False, error="The claude command was not found on PATH.")
        self.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        process = subprocess.Popen(
            build_args(executable, prompt),
            cwd=self.workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        deadline = started + self.timeout_s
        while True:
            try:
                stdout, _stderr = process.communicate(timeout=POLL_INTERVAL_S)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    process.terminate()
                    process.communicate()
                    return RunResult(ok=False, error="Cancelled.")
                if time.monotonic() > deadline:
                    process.kill()
                    process.communicate()
                    return RunResult(
                        ok=False, error=f"Claude Code did not finish in {self.timeout_s:.0f} s."
                    )
        duration_ms = int((time.monotonic() - started) * 1000)
        return parse_stream(stdout, process.returncode, duration_ms)
