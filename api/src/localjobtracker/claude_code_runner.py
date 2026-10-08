"""ClaudeCodeRunner: the only module that knows about the Claude Code CLI (D-20).

Flags follow planning/runner-notes.md, checked against Claude Code 2.1.289. Every run is
restricted: no tools, no MCP servers, no settings files from the working folder, and no
prompts that could wait for an answer. A dollar cap limits each run.

Output is read as stream-json, incrementally: a reader thread parses each line as it arrives,
so a plan limit or the answer's text (D-105) can be seen before the CLI exits. A plan limit
shows up as a `rate_limit_event` (or an `api_retry` with category `rate_limit`) and is raised
as RateLimitError (D-63).
"""

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from localjobtracker.runner import RateLimitError, RunResult

# A profile prompt can read every CV, so a run may take many minutes. The timeout is the
# only stop for a run that goes on too long (D-75).
DEFAULT_TIMEOUT_S = 15 * 60
# How often a running CLI is checked for a cancel request or a timeout.
POLL_INTERVAL_S = 0.2
# The model every profile prompt runs on (D-74). The id is given in full, because the
# CLI's "sonnet" alias points at a newer model.
MODEL = "claude-sonnet-5"
# rate_limit_info.status values that mean the run may continue. Any other status is a limit.
ALLOWED_RATE_LIMIT_STATUSES = frozenset({"allowed", "allowed_warning"})


def build_args(executable: str, json_schema: dict[str, Any] | None = None) -> list[str]:
    # The prompt is not an argument. Windows limits a command line to about 32,000 characters,
    # and a profile prompt can hold every CV. The prompt goes to standard input instead.
    args = [
        executable,
        "-p",
        "--model",
        MODEL,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--restricted",
        "--strict-mcp-config",
        "--tools",
        "",
        "--permission-prompts",
        "none",
        "--no-session-persistence",
    ]
    if json_schema is not None:
        args += ["--json-schema", json.dumps(json_schema)]
    return args


def _parse_event_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        event: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def _events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        event = _parse_event_line(line)
        if event is not None:
            events.append(event)
    return events


def _partial_text(event: dict[str, Any]) -> str | None:
    """A text chunk from --include-partial-messages, if this event carries one (D-105).

    Unverified shape: assumes Claude Code wraps the raw Anthropic streaming event under
    `type: "stream_event"` / `event`, per its headless docs. Confirm against a real streamed
    run (this step list's real-file run) and adjust here if the shape differs — see
    planning/runner-notes.md.
    """
    if event.get("type") != "stream_event":
        return None
    inner = event.get("event")
    if not isinstance(inner, dict) or inner.get("type") != "content_block_delta":
        return None
    delta = inner.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return None
    text = delta.get("text")
    return text if isinstance(text, str) else None


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


def _model(events: list[dict[str, Any]]) -> str | None:
    """The model the CLI reports in its start event, so each run records what it used."""
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            model = event.get("model")
            return model if isinstance(model, str) else None
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
    model = _model(events)

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
        # An API error comes as the result text (for example "API Error: 529 ..."). Show that.
        detail = str(message.get("result") or "").strip()
        reason = detail[:300] or message.get("subtype") or f"exit {exit_code}"
        return RunResult(
            ok=False,
            error=f"Claude Code run failed ({reason}).",
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            model=model,
        )
    # With --json-schema the answer can come as structured_output. Use it when it is there.
    structured = message.get("structured_output")
    text = json.dumps(structured) if structured is not None else str(message.get("result", ""))
    return RunResult(
        ok=True,
        text=text,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        model=model,
    )


def _cli_environment() -> dict[str, str]:
    """The environment for the CLI, without an API key. With no key set, the CLI uses the
    claude.ai login and its plan limits, as Claude Code does (D-75). A key would switch
    the run to per-token API billing, so it is removed."""
    return {name: value for name, value in os.environ.items() if name != "ANTHROPIC_API_KEY"}


class ClaudeCodeRunner:
    def __init__(self, workdir: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.workdir = workdir
        self.timeout_s = timeout_s

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> RunResult:
        executable = shutil.which("claude")
        if executable is None:
            return RunResult(ok=False, error="The claude command was not found on PATH.")
        self.workdir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        process = subprocess.Popen(
            build_args(executable, json_schema),
            cwd=self.workdir,
            env=_cli_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin is not None
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except BrokenPipeError:
            # The CLI stopped reading early. Its output below says why.
            pass

        # stdout is drained continuously in a thread, not read at exit, so a text chunk (and a
        # rate-limit event) is visible to on_text before the CLI finishes. stderr is drained too,
        # only so its pipe never fills and blocks the CLI; nothing currently reads it.
        lines: list[str] = []

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)
                event = _parse_event_line(line)
                if event is None or on_text is None:
                    continue
                chunk = _partial_text(event)
                if chunk:
                    try:
                        on_text(chunk)
                    except Exception:
                        pass  # a reporting callback must never break the run

        def drain_stderr() -> None:
            assert process.stderr is not None
            for _ in process.stderr:
                pass

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        deadline = started + self.timeout_s
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                process.terminate()
                process.wait()
                stdout_thread.join(timeout=5.0)
                return RunResult(ok=False, error="Cancelled.")
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                stdout_thread.join(timeout=5.0)
                return RunResult(
                    ok=False, error=f"Claude Code did not finish in {self.timeout_s:.0f} s."
                )
            time.sleep(POLL_INTERVAL_S)

        stdout_thread.join(timeout=5.0)
        stderr_thread.join(timeout=5.0)
        duration_ms = int((time.monotonic() - started) * 1000)
        return parse_stream("".join(lines), process.returncode, duration_ms)
