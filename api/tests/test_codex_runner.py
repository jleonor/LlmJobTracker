import json
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from llmjobtracker.codex_runner import (
    MODEL,
    CodexRunner,
    auth_status,
    build_args,
    logout,
    parse_stream,
)
from llmjobtracker.runner import RateLimitError

REQUIRED_FLAGS = ["--skip-git-repo-check", "--sandbox", "read-only", "--json"]

# Real event shapes, codex-cli 0.162.1 (planning/runner-notes.md's Phase 7 section).
THREAD_STARTED = {"type": "thread.started", "thread_id": "01a1391b-4a74-75f0-8515-5cd28b400a1c"}
TURN_STARTED = {"type": "turn.started"}
AGENT_MESSAGE = {
    "type": "item.completed",
    "item": {"id": "item_0", "type": "agent_message", "text": "OK"},
}
TURN_COMPLETED = {
    "type": "turn.completed",
    "usage": {
        "input_tokens": 16106,
        "cached_input_tokens": 13440,
        "cache_write_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 0,
    },
}
TURN_FAILED = {
    "type": "turn.failed",
    "error": {
        "message": (
            '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
            '"message":"The \'not-a-real-model\' model is not supported when using '
            'Codex with a ChatGPT account."}}'
        )
    },
}


def stream(*events: Mapping[str, object]) -> str:
    return "\n".join(json.dumps(event) for event in events)


def test_build_args_keeps_every_run_sandboxed() -> None:
    args = build_args("codex")
    for flag in REQUIRED_FLAGS:
        assert flag in args
    assert args[1] == "exec"
    assert args[2] == "-"
    assert "Reply with OK." not in args  # the prompt goes through stdin


def test_the_runner_asks_for_the_codex_model() -> None:
    args = build_args("codex")
    assert args[args.index("--model") + 1] == MODEL == "gpt-6.1-sol"


def test_build_args_accepts_a_model_override() -> None:
    args = build_args("codex", model="gpt-5-codex")
    assert args[args.index("--model") + 1] == "gpt-5-codex"


def test_a_json_schema_file_path_is_passed_to_the_cli(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    args = build_args("codex", schema_path)
    assert args[args.index("--output-schema") + 1] == str(schema_path)
    assert "--output-schema" not in build_args("codex")


def test_parse_success_reads_the_last_agent_message_and_tokens() -> None:
    parsed = parse_stream(
        stream(THREAD_STARTED, TURN_STARTED, AGENT_MESSAGE, TURN_COMPLETED),
        exit_code=0,
        duration_ms=6265,
    )
    assert parsed.ok is True
    assert parsed.text == "OK"
    assert parsed.model == MODEL
    assert parsed.cost_usd is None  # Codex never reports a dollar cost (runner-notes.md)
    assert parsed.input_tokens == 16106
    assert parsed.output_tokens == 5


def test_parse_success_records_the_model_actually_requested() -> None:
    parsed = parse_stream(
        stream(THREAD_STARTED, TURN_STARTED, AGENT_MESSAGE, TURN_COMPLETED),
        exit_code=0,
        duration_ms=1,
        model="gpt-5-codex",
    )
    assert parsed.model == "gpt-5-codex"


def test_a_turn_can_emit_more_than_one_agent_message_item() -> None:
    first = {
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "Draft"},
    }
    second = {
        "type": "item.completed",
        "item": {"id": "item_1", "type": "agent_message", "text": "Final"},
    }
    parsed = parse_stream(
        stream(THREAD_STARTED, TURN_STARTED, first, second, TURN_COMPLETED),
        exit_code=0,
        duration_ms=1,
    )
    assert parsed.text == "Final"  # the last one wins


def test_a_non_fatal_error_item_does_not_fail_the_run() -> None:
    warning = {
        "type": "item.completed",
        "item": {"id": "item_0", "type": "error", "message": "Defaulting to fallback metadata."},
    }
    parsed = parse_stream(
        stream(THREAD_STARTED, warning, TURN_STARTED, AGENT_MESSAGE, TURN_COMPLETED),
        exit_code=0,
        duration_ms=1,
    )
    assert parsed.ok is True


def test_turn_failed_fails_the_run_with_the_unwrapped_message() -> None:
    parsed = parse_stream(stream(THREAD_STARTED, TURN_FAILED), exit_code=1, duration_ms=1)
    assert parsed.ok is False
    assert "not supported when using Codex with a ChatGPT account" in (parsed.error or "")


def test_a_rate_limit_marker_in_the_error_raises_rate_limit() -> None:
    limited = {
        "type": "turn.failed",
        "error": {"message": '{"error":{"message":"rate_limit_exceeded: try again later"}}'},
    }
    with pytest.raises(RateLimitError):
        parse_stream(stream(THREAD_STARTED, limited), exit_code=1, duration_ms=1)


def test_parse_output_without_a_result_fails() -> None:
    parsed = parse_stream("not json at all", exit_code=0, duration_ms=5)
    assert parsed.ok is False
    assert "returned no agent_message" in (parsed.error or "")


def test_non_zero_exit_without_an_explicit_error_event_still_fails() -> None:
    parsed = parse_stream(stream(THREAD_STARTED, TURN_STARTED), exit_code=1, duration_ms=5)
    assert parsed.ok is False
    assert "exit 1" in (parsed.error or "")


def test_missing_executable_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = CodexRunner(workdir=tmp_path).run("Reply with OK.")
    assert result.ok is False
    assert "not found on PATH" in (result.error or "")


@pytest.mark.live
@pytest.mark.skipif(shutil.which("codex") is None, reason="codex is not installed")
def test_live_run_replies_ok(tmp_path: Path) -> None:
    result = CodexRunner(workdir=tmp_path).run("Reply with exactly the word OK and nothing else.")
    assert result.ok is True, result.error
    assert "OK" in result.text
    assert result.input_tokens is not None
    assert result.cost_usd is None


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.closed = False

    def write(self, text: str) -> None:
        self.written.append(text)

    def close(self) -> None:
        self.closed = True


class _RunningProcess:
    def __init__(
        self, stdout_lines: list[str] | None = None, returncode: int | None = None
    ) -> None:
        self.stdin = _FakeStdin()
        self.stdout = iter(stdout_lines or [])
        self.stderr = iter(())
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 143

    def kill(self) -> None:
        self.terminated = True
        self.returncode = 137


def test_cancel_terminates_the_cli_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _RunningProcess()
    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    cancel = threading.Event()
    cancel.set()

    result = CodexRunner(workdir=tmp_path).run("Reply with OK.", cancel=cancel)

    assert process.terminated is True
    assert result.ok is False
    assert result.error == "Cancelled."


def test_the_prompt_is_written_to_standard_input_not_the_command_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _RunningProcess()
    commands: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> _RunningProcess:
        commands.append(args)
        process.returncode = 0
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    long_prompt = "x" * 40_000

    CodexRunner(workdir=tmp_path).run(long_prompt)

    assert process.stdin.written == [long_prompt]
    assert process.stdin.closed is True
    assert long_prompt not in commands[0]


def test_a_json_schema_is_written_to_a_temp_file_and_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = (THREAD_STARTED, TURN_STARTED, AGENT_MESSAGE, TURN_COMPLETED)
    lines = [json.dumps(event) + "\n" for event in events]
    process = _RunningProcess(stdout_lines=lines, returncode=0)
    commands: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> _RunningProcess:
        commands.append(args)
        # The schema file must exist (and hold the schema) at the moment the CLI is launched.
        schema_path = Path(args[args.index("--output-schema") + 1])
        assert json.loads(schema_path.read_text()) == schema
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    schema: dict[str, Any] = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    result = CodexRunner(workdir=tmp_path).run("Reply with OK.", json_schema=schema)

    assert result.ok is True
    schema_path = Path(commands[0][commands[0].index("--output-schema") + 1])
    assert not schema_path.exists()  # cleaned up after the run


def test_a_run_may_take_up_to_fifteen_minutes() -> None:
    assert CodexRunner(workdir=Path(".")).timeout_s == 15 * 60


def test_the_runner_defaults_to_the_module_model() -> None:
    assert CodexRunner(workdir=Path(".")).model == MODEL


def test_the_runner_accepts_a_model_override() -> None:
    assert CodexRunner(workdir=Path("."), model="gpt-5-codex").model == "gpt-5-codex"


def test_a_selected_model_reaches_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = _RunningProcess()
    commands: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> _RunningProcess:
        commands.append(args)
        process.returncode = 0
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    CodexRunner(workdir=tmp_path, model="gpt-5-codex").run("Reply with OK.")

    assert commands[0][commands[0].index("--model") + 1] == "gpt-5-codex"


class _CompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_auth_status_reads_the_real_text_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Confirmed live (2026-10-14): `codex login status` prints plain text, not JSON.
    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: _CompletedProcess(stdout="Logged in using ChatGPT\n", returncode=0),
    )

    status = auth_status()

    assert status.logged_in is True
    assert status.detail == "Logged in using ChatGPT"


def test_auth_status_a_nonzero_exit_is_not_logged_in(monkeypatch: pytest.MonkeyPatch) -> None:
    # The not-logged-in text shape is unconfirmed live (runner-notes.md) - built defensively.
    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: _CompletedProcess(stdout="Not logged in.\n", returncode=1),
    )

    status = auth_status()

    assert status.logged_in is False


def test_auth_status_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    status = auth_status()

    assert status.logged_in is False
    assert "not found on PATH" in status.detail


def test_logout_runs_the_cli_logout_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> _CompletedProcess:
        calls.append(args)
        return _CompletedProcess()

    monkeypatch.setattr(shutil, "which", lambda _name: "codex")
    monkeypatch.setattr(subprocess, "run", fake_run)

    logout()

    assert calls == [["codex", "logout"]]


def test_logout_does_nothing_without_the_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(subprocess, "run", lambda args, **_k: calls.append(args))

    logout()

    assert calls == []
