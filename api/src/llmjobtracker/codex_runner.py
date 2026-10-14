"""CodexRunner: the only module that knows about the Codex CLI (D-20, extends D-195/D-204).

Flags and event shapes follow planning/runner-notes.md's Phase 7 section, confirmed live against
codex-cli 0.162.1. Every run passes --skip-git-repo-check (Codex refuses to run at all outside a
trusted/git directory otherwise) and --sandbox read-only (no filesystem/network side effects,
matching ClaudeCodeRunner's --restricted/no-tools stance - this app's jobs want an answer, not an
agent that edits files).

Codex's own output never reports a dollar cost or which model served the request (confirmed live,
runner-notes.md) - this runner always leaves cost_usd as None (the queue computes it from tokens
and the price table, Agent/specs/pricing.md) and records the model it explicitly requested rather
than parsing one out of nothing.

Output is read as JSONL, after the process exits. Codex's own equivalent of
--include-partial-messages (D-105's live text streaming) is not confirmed live yet, so on_text is
accepted but never called here - the same honest gap runner-notes.md records rather than guessing
a shape to stream from.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llmjobtracker.runner import AuthStatus, RateLimitError, RunResult

# Mirrors claude_code_runner.DEFAULT_TIMEOUT_S/POLL_INTERVAL_S - same reasoning (D-75).
DEFAULT_TIMEOUT_S = 15 * 60
POLL_INTERVAL_S = 0.2
# The model every Codex run uses unless told otherwise. Codex does not echo back which model it
# used (runner-notes.md), so this is also what RunResult.model records - not a parsed value.
MODEL = "gpt-5-codex"
# Mirrors claude_code_runner.AUTH_TIMEOUT_S.
AUTH_TIMEOUT_S = 15
# Substrings seen in a failed turn's error message that mean a plan/rate limit, not a real
# failure. Unconfirmed live (runner-notes.md: a real limit was not triggered) - built from
# third-party research per D-201, to be checked against a real limit the first time one is hit,
# the same "confirm when first seen" rule already applied twice to ClaudeCodeRunner.
RATE_LIMIT_MARKERS = ("rate_limit_exceeded", "insufficient_quota")


def auth_status() -> AuthStatus:
    """Confirmed live (2026-10-14): `codex login status` prints plain text ("Logged in using
    ChatGPT"), not JSON (no --json flag exists for it, unlike Claude Code's `auth status`), and
    exits 0 when logged in. The not-logged-in case is unconfirmed live (not deliberately logged
    out to check) - detected defensively by looking for "logged in" in the text, same "confirm
    when first seen" caveat as this module's rate-limit markers."""
    executable = shutil.which("codex")
    if executable is None:
        return AuthStatus(logged_in=False, detail="The codex command was not found on PATH.")
    try:
        completed = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=AUTH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return AuthStatus(logged_in=False, detail="Timed out checking the login status.")
    text = completed.stdout.strip() or completed.stderr.strip()
    logged_in = completed.returncode == 0 and "logged in" in text.lower()
    return AuthStatus(logged_in=logged_in, detail=text or f"exit {completed.returncode}")


def logout() -> None:
    """Runs `codex logout` (confirmed live to need no flags). Does nothing if the CLI isn't on
    PATH - there is then nothing to log out of."""
    executable = shutil.which("codex")
    if executable is None:
        return
    subprocess.run([executable, "logout"], capture_output=True, text=True, timeout=AUTH_TIMEOUT_S)


def build_args(executable: str, schema_path: Path | None = None) -> list[str]:
    # The prompt is not an argument, for the same reason as ClaudeCodeRunner: Windows' command-line
    # length limit, and a profile prompt that can hold every CV. It goes to standard input instead,
    # signalled by the "-" positional argument.
    args = [
        executable,
        "exec",
        "-",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        MODEL,
    ]
    if schema_path is not None:
        # Unlike Claude Code's inline --json-schema, Codex's --output-schema takes a file path
        # (runner-notes.md, not yet exercised live) - the caller (run(), below) writes the schema
        # to a temp file before calling this.
        args += ["--output-schema", str(schema_path)]
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


def _agent_text(events: list[dict[str, Any]]) -> str | None:
    """The last agent_message item's text - a turn can emit more than one item.completed event
    for intermediate reasoning, confirmed live (runner-notes.md)."""
    text: str | None = None
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            value = item.get("text")
            if isinstance(value, str):
                text = value
    return text


def _usage(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == "turn.completed":
            usage = event.get("usage")
            return usage if isinstance(usage, dict) else None
    return None


def _tokens(usage: dict[str, Any] | None, key: str) -> int | None:
    if usage is None:
        return None
    value = usage.get(key)
    return value if isinstance(value, int) else None


def _flatten_error_message(raw: object) -> str:
    """turn.failed's/error's own message is itself a JSON string, confirmed live - unwrap it to
    the inner error's own message when it parses, otherwise use the raw text as-is."""
    if not isinstance(raw, str):
        return str(raw)
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(parsed.get("message"), str):
            return str(parsed["message"])
    return raw


def _turn_failure_message(events: list[dict[str, Any]]) -> str | None:
    """The failure message, if the stream reports one (a fatal turn.failed, or a top-level error
    event with no following turn.completed). A non-fatal item.completed error (for example a
    model-metadata warning, confirmed live) is not a failure by itself."""
    message: object = None
    for event in events:
        if event.get("type") == "turn.failed":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else event.get("message")
        elif event.get("type") == "error":
            message = event.get("message")
    return _flatten_error_message(message) if message is not None else None


def parse_stream(stdout: str, exit_code: int, duration_ms: int) -> RunResult:
    """Read a codex exec --json run. Raises RateLimitError on a plan limit."""
    events = _events(stdout)
    failure = _turn_failure_message(events)
    if failure is not None:
        if any(marker in failure for marker in RATE_LIMIT_MARKERS):
            raise RateLimitError(f"The Codex plan limit was reached ({failure[:300]}).")
        return RunResult(
            ok=False, error=f"Codex run failed ({failure[:300]}).", duration_ms=duration_ms
        )
    if exit_code != 0:
        return RunResult(
            ok=False,
            error=f"Codex returned no result (exit {exit_code}).",
            duration_ms=duration_ms,
        )
    text = _agent_text(events)
    if text is None:
        return RunResult(
            ok=False, error="Codex returned no agent_message.", duration_ms=duration_ms
        )
    usage = _usage(events)
    return RunResult(
        ok=True,
        text=text,
        duration_ms=duration_ms,
        model=MODEL,
        input_tokens=_tokens(usage, "input_tokens"),
        output_tokens=_tokens(usage, "output_tokens"),
    )


def _cli_environment() -> dict[str, str]:
    """The environment for the CLI, without an API key. With neither key set, the CLI uses the
    ChatGPT login and its plan limits (D-188), the same reasoning claude_code_runner applies to
    ANTHROPIC_API_KEY (D-75)."""
    excluded = {"OPENAI_API_KEY", "CODEX_API_KEY"}
    return {name: value for name, value in os.environ.items() if name not in excluded}


class CodexRunner:
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
        executable = shutil.which("codex")
        if executable is None:
            return RunResult(ok=False, error="The codex command was not found on PATH.")
        self.workdir.mkdir(parents=True, exist_ok=True)
        schema_file: Path | None = None
        if json_schema is not None:
            handle = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", dir=self.workdir, delete=False
            )
            schema_file = Path(handle.name)
            with handle:
                json.dump(json_schema, handle)

        started = time.monotonic()
        process = subprocess.Popen(
            build_args(executable, schema_file),
            cwd=self.workdir,
            env=_cli_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert process.stdin is not None
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except BrokenPipeError:
                pass  # the CLI stopped reading early; its output below says why

            lines: list[str] = []

            def read_stdout() -> None:
                assert process.stdout is not None
                for line in process.stdout:
                    lines.append(line)

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
                        ok=False, error=f"Codex did not finish in {self.timeout_s:.0f} s."
                    )
                time.sleep(POLL_INTERVAL_S)

            stdout_thread.join(timeout=5.0)
            stderr_thread.join(timeout=5.0)
            duration_ms = int((time.monotonic() - started) * 1000)
            return parse_stream("".join(lines), process.returncode, duration_ms)
        finally:
            if schema_file is not None:
                schema_file.unlink(missing_ok=True)
