"""Shared subprocess plumbing for the CLI-backed runners (D-20, D-225).

ClaudeCodeRunner and CodexRunner each spawn their own CLI as a subprocess with an identical
lifecycle: write the prompt to stdin, drain stdout/stderr in background threads, and poll for a
cancel request or a timeout. This module owns that lifecycle and the generic JSONL-event reading
every stream-based CLI output shares. Each runner's own module keeps only what's genuinely its
own: `build_args`, interpreting its event stream (`parse_stream`), and `auth_status`/`login`/
`logout` (different CLI commands and output shapes) - so `Runner` stays the only Claude-Code/
Codex-aware seam from the rest of the app's point of view (D-19/D-20), unaffected by this split.
"""

import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llmjobtracker.runner import RunResult

# How often a running CLI is checked for a cancel request or a timeout.
POLL_INTERVAL_S = 0.2


def parse_event_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        event: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


def events_from_stdout(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        event = parse_event_line(line)
        if event is not None:
            events.append(event)
    return events


def run_cli_process(
    args: list[str],
    *,
    cli_label: str,
    workdir: Path,
    env: dict[str, str],
    prompt: str,
    timeout_s: float,
    cancel: threading.Event | None,
    on_line: Callable[[str], None] | None,
    parse_stream: Callable[[str, int, int], RunResult],
) -> RunResult:
    """Spawn `args`, write `prompt` to stdin, and drain stdout/stderr while watching `cancel` and
    `timeout_s`. `on_line`, when given, is called with each raw stdout line as it arrives (a
    runner that cannot stream simply passes None); an exception from it never breaks the run. On
    a clean exit, hands the joined stdout, exit code and duration to `parse_stream`. `cli_label`
    names the CLI in the timeout message only (e.g. "Claude Code", "Codex").
    """
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = subprocess.Popen(
        args,
        cwd=workdir,
        env=env,
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

    # stdout is drained continuously in a thread, not read at exit, so on_line (and a rate-limit
    # event) is visible before the CLI finishes. stderr is drained too, only so its pipe never
    # fills and blocks the CLI; nothing currently reads it.
    lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if on_line is None:
                continue
            try:
                on_line(line)
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

    deadline = started + timeout_s
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
            return RunResult(ok=False, error=f"{cli_label} did not finish in {timeout_s:.0f} s.")
        time.sleep(POLL_INTERVAL_S)

    stdout_thread.join(timeout=5.0)
    stderr_thread.join(timeout=5.0)
    duration_ms = int((time.monotonic() - started) * 1000)
    return parse_stream("".join(lines), process.returncode, duration_ms)
