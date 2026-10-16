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
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llmjobtracker.cli_runner import events_from_stdout, parse_event_line, run_cli_process
from llmjobtracker.runner import AuthStatus, RateLimitError, RunResult

# A profile prompt can read every CV, so a run may take many minutes. The timeout is the
# only stop for a run that goes on too long (D-75).
DEFAULT_TIMEOUT_S = 15 * 60
# The model a run uses unless ClaudeCodeRunner is given another (D-74, extended by the
# selectable-model setting, D-206). The id is given in full, because the CLI's "sonnet" alias
# points at a newer model.
MODEL = "claude-sonnet-5"
# rate_limit_info.status values that mean the run may continue. Any other status is a limit.
ALLOWED_RATE_LIMIT_STATUSES = frozenset({"allowed", "allowed_warning"})
# A status/logout check is a local read, not a model call - a short timeout is plenty (D-203).
AUTH_TIMEOUT_S = 15


def auth_status() -> AuthStatus:
    """Confirmed live (2026-10-14): `claude auth status --json` prints
    `{"loggedIn": bool, "authMethod": ..., "email": ..., ...}` and exits 0 whether logged in or
    not - the JSON body, not the exit code, says which."""
    executable = shutil.which("claude")
    if executable is None:
        return AuthStatus(logged_in=False, detail="The claude command was not found on PATH.")
    try:
        completed = subprocess.run(
            [executable, "auth", "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=AUTH_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return AuthStatus(logged_in=False, detail="Timed out checking the login status.")
    try:
        data: Any = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = completed.stdout.strip() or completed.stderr.strip()
        return AuthStatus(logged_in=False, detail=detail or f"exit {completed.returncode}")
    logged_in = bool(isinstance(data, dict) and data.get("loggedIn"))
    email = data.get("email") if isinstance(data, dict) else None
    if logged_in:
        detail = f"Logged in as {email}" if isinstance(email, str) and email else "Logged in"
    else:
        detail = "Not logged in"
    return AuthStatus(logged_in=logged_in, detail=detail)


def logout() -> None:
    """Runs `claude auth logout` (confirmed live to need no flags). Does nothing if the CLI
    isn't on PATH - there is then nothing to log out of."""
    executable = shutil.which("claude")
    if executable is None:
        return
    subprocess.run(
        [executable, "auth", "logout"], capture_output=True, text=True, timeout=AUTH_TIMEOUT_S
    )


def login() -> None:
    """Runs `claude auth login`, which opens a browser window for the user to finish signing in
    there (the user's own action - nothing here enters a credential). Launched with Popen, not
    run with a timeout like auth_status/logout above: those are quick local reads, this blocks
    until the browser flow completes, which can take minutes. Given its own visible console
    window on Windows (D-213) - confirmed live to print the CLI's own login prompt there - so
    the user can see it and close it themselves, instead of it silently inheriting this
    backend's own (usually invisible) console. Does nothing if the CLI isn't on PATH."""
    executable = shutil.which("claude")
    if executable is None:
        return
    creation_flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    subprocess.Popen([executable, "auth", "login"], creationflags=creation_flags)


def build_args(
    executable: str, json_schema: dict[str, Any] | None = None, model: str = MODEL
) -> list[str]:
    # The prompt is not an argument. Windows limits a command line to about 32,000 characters,
    # and a profile prompt can hold every CV. The prompt goes to standard input instead.
    args = [
        executable,
        "-p",
        "--model",
        model,
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


def _tokens(message: dict[str, Any]) -> tuple[int | None, int | None]:
    """Input/output token counts from the result message's usage object (D-197).

    Confirmed live (runner-notes.md): Claude Code's usage.input_tokens excludes cache tokens,
    reported separately as cache_creation_input_tokens/cache_read_input_tokens (a run with most
    of its context served from cache showed input_tokens=2 alongside cache_creation_input_tokens
    in the thousands). Summing all three gives a total comparable to Codex's own input_tokens
    field, which is already a total (runner-notes.md) - without this, Claude's recorded input
    count would look implausibly small next to Codex's for a similarly-sized prompt.
    """
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None, None
    parts = (
        usage.get("input_tokens"),
        usage.get("cache_creation_input_tokens"),
        usage.get("cache_read_input_tokens"),
    )
    numeric = [part for part in parts if isinstance(part, int)]
    input_tokens = sum(numeric) if numeric else None
    output = usage.get("output_tokens")
    output_tokens = output if isinstance(output, int) else None
    return input_tokens, output_tokens


def _reset_time(value: object) -> datetime | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC)
    return None


def parse_stream(stdout: str, exit_code: int, duration_ms: int) -> RunResult:
    """Read a stream-json run. Raises RateLimitError on a plan limit.

    The final `result` message carries the text. A failure inside a run can print on stdout
    with exit 0, so the result's own flags are checked too.
    """
    events = events_from_stdout(stdout)
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
    input_tokens, output_tokens = _tokens(message)
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
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _cli_environment() -> dict[str, str]:
    """The environment for the CLI, without an API key. With no key set, the CLI uses the
    claude.ai login and its plan limits, as Claude Code does (D-75). A key would switch
    the run to per-token API billing, so it is removed."""
    return {name: value for name, value in os.environ.items() if name != "ANTHROPIC_API_KEY"}


class ClaudeCodeRunner:
    def __init__(
        self, workdir: Path, model: str = MODEL, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self.workdir = workdir
        self.model = model
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

        def on_line(line: str) -> None:
            if on_text is None:
                return
            event = parse_event_line(line)
            if event is None:
                return
            chunk = _partial_text(event)
            if chunk:
                on_text(chunk)

        return run_cli_process(
            build_args(executable, json_schema, self.model),
            cli_label="Claude Code",
            workdir=self.workdir,
            env=_cli_environment(),
            prompt=prompt,
            timeout_s=self.timeout_s,
            cancel=cancel,
            on_line=on_line,
            parse_stream=parse_stream,
        )
