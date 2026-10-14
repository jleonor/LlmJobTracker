import json
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from llmjobtracker.claude_code_runner import (
    MODEL,
    ClaudeCodeRunner,
    build_args,
    parse_stream,
)
from llmjobtracker.runner import FakeRunner, RateLimitError

REQUIRED_FLAGS = [
    "--restricted",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-prompts",
    "none",
]

RESULT_OK = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": "OK",
    "total_cost_usd": 0.0106,
    "api_error_status": None,
}

# Shape of a real rate_limit_event from Claude Code 2.1.289 (a run that was allowed).
ALLOWED_EVENT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1791286200,
        "rateLimitType": "five_hour",
    },
}


def stream(*events: Mapping[str, object]) -> str:
    return "\n".join(json.dumps(event) for event in events)


def test_build_args_keeps_every_run_restricted() -> None:
    args = build_args("claude")
    for flag in REQUIRED_FLAGS:
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[1] == "-p"
    assert "Reply with OK." not in args  # the prompt goes through stdin


def test_parse_success_reads_result_text_and_cost() -> None:
    parsed = parse_stream(stream(ALLOWED_EVENT, RESULT_OK), exit_code=0, duration_ms=12)
    assert parsed.ok is True
    assert parsed.text == "OK"
    assert parsed.cost_usd == pytest.approx(0.0106)
    assert parsed.duration_ms == 12


def test_parse_error_flag_fails_even_with_exit_zero() -> None:
    failed = {**RESULT_OK, "subtype": "error_max_budget", "is_error": True, "result": ""}
    parsed = parse_stream(stream(failed), exit_code=0, duration_ms=5)
    assert parsed.ok is False
    assert parsed.error == "Claude Code run failed (error_max_budget)."


def test_parse_non_zero_exit_fails() -> None:
    parsed = parse_stream(stream(RESULT_OK), exit_code=1, duration_ms=5)
    assert parsed.ok is False


def test_parse_output_without_a_result_fails() -> None:
    parsed = parse_stream("not json at all", exit_code=0, duration_ms=5)
    assert parsed.ok is False
    assert "returned no result" in (parsed.error or "")


def test_allowed_status_is_not_a_limit() -> None:
    warning = {**ALLOWED_EVENT, "rate_limit_info": {"status": "allowed_warning"}}
    assert parse_stream(stream(warning, RESULT_OK), exit_code=0, duration_ms=1).ok is True


def test_rejected_status_raises_rate_limit_with_reset_time() -> None:
    rejected = {
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "rejected", "resetsAt": 1791286200},
    }
    with pytest.raises(RateLimitError) as raised:
        parse_stream(stream(rejected), exit_code=0, duration_ms=1)
    assert raised.value.resets_at is not None
    assert raised.value.resets_at.timestamp() == 1791286200


def test_rate_limit_retry_event_raises_without_reset_time() -> None:
    retry = {"type": "system", "subtype": "api_retry", "error_category": "rate_limit"}
    with pytest.raises(RateLimitError) as raised:
        parse_stream(stream(retry, RESULT_OK), exit_code=0, duration_ms=1)
    assert raised.value.resets_at is None


def test_429_in_the_result_raises_rate_limit() -> None:
    limited = {**RESULT_OK, "is_error": True, "subtype": "error", "api_error_status": 429}
    with pytest.raises(RateLimitError):
        parse_stream(stream(limited), exit_code=1, duration_ms=1)


def test_fake_runner_raises_rate_limit_then_recovers() -> None:
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=1)
    with pytest.raises(RateLimitError):
        runner.run("first")
    assert runner.run("second").text == "done"


def test_missing_executable_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = ClaudeCodeRunner(workdir=tmp_path).run("Reply with OK.")
    assert result.ok is False
    assert "not found on PATH" in (result.error or "")


@pytest.mark.live
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude is not installed")
def test_live_run_replies_ok(tmp_path: Path) -> None:
    result = ClaudeCodeRunner(workdir=tmp_path).run("Reply with the single word OK.")
    assert result.ok is True, result.error
    assert "OK" in result.text


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.closed = False

    def write(self, text: str) -> None:
        self.written.append(text)

    def close(self) -> None:
        self.closed = True


class _RunningProcess:
    """Stands in for a Popen process. `returncode` controls what poll() reports.

    Left as None (the default), the process looks like it is still running, the way the cancel
    and timeout tests below need. Set up front, it looks like it already exited, so the run
    reads `stdout_lines` and returns at once — what the streaming tests need.
    """

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
    monkeypatch.setattr(shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    cancel = threading.Event()
    cancel.set()

    result = ClaudeCodeRunner(workdir=tmp_path).run("Reply with OK.", cancel=cancel)

    assert process.terminated is True
    assert result.ok is False
    assert result.error == "Cancelled."


def test_a_json_schema_is_passed_to_the_cli() -> None:
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    args = build_args("claude", schema)
    assert args[args.index("--json-schema") + 1] == json.dumps(schema)
    assert "--json-schema" not in build_args("claude")


def test_structured_output_is_used_as_the_answer() -> None:
    answered = {**RESULT_OK, "result": "", "structured_output": {"ok": True}}
    parsed = parse_stream(stream(answered), exit_code=0, duration_ms=1)
    assert parsed.ok is True
    assert json.loads(parsed.text) == {"ok": True}


def test_an_api_error_shows_its_text_instead_of_the_subtype() -> None:
    overloaded = {
        **RESULT_OK,
        "subtype": "success",
        "is_error": True,
        "result": "API Error: 529 Overloaded. Try again in a moment.",
        "api_error_status": 529,
    }
    parsed = parse_stream(stream(overloaded), exit_code=1, duration_ms=1)
    assert parsed.ok is False
    assert (
        parsed.error
        == "Claude Code run failed (API Error: 529 Overloaded. Try again in a moment.)."
    )


def test_the_prompt_is_written_to_standard_input_not_the_command_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _RunningProcess()
    commands: list[list[str]] = []

    def fake_popen(args: list[str], **_kwargs: object) -> _RunningProcess:
        commands.append(args)
        process.returncode = 0  # ends the run at once; the output is not the point here
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    long_prompt = "x" * 40_000

    ClaudeCodeRunner(workdir=tmp_path).run(long_prompt)

    assert process.stdin.written == [long_prompt]
    assert process.stdin.closed is True
    assert long_prompt not in commands[0]


def test_the_model_is_read_from_the_start_event() -> None:
    start = {"type": "system", "subtype": "init", "model": "claude-sonnet-5"}
    parsed = parse_stream(stream(start, RESULT_OK), exit_code=0, duration_ms=1)
    assert parsed.model == "claude-sonnet-5"


def test_input_tokens_sum_the_fresh_and_cached_fields() -> None:
    # Confirmed live (runner-notes.md): usage.input_tokens alone excludes cache tokens, so the
    # three fields are summed into one comparable total (D-197).
    answered = {
        **RESULT_OK,
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 3143,
            "cache_read_input_tokens": 100,
            "output_tokens": 4,
        },
    }
    parsed = parse_stream(stream(answered), exit_code=0, duration_ms=1)
    assert parsed.input_tokens == 2 + 3143 + 100
    assert parsed.output_tokens == 4


def test_missing_usage_leaves_tokens_as_none() -> None:
    parsed = parse_stream(stream(RESULT_OK), exit_code=0, duration_ms=1)
    assert parsed.input_tokens is None
    assert parsed.output_tokens is None


def test_the_runner_asks_for_the_profile_model() -> None:
    args = build_args("claude")
    assert args[args.index("--model") + 1] == MODEL == "claude-sonnet-5"


def test_no_budget_cap_is_passed_to_the_cli() -> None:
    assert "--max-budget-usd" not in build_args("claude")


def test_a_run_may_take_up_to_fifteen_minutes() -> None:
    assert ClaudeCodeRunner(workdir=Path(".")).timeout_s == 15 * 60


def test_build_args_requests_partial_messages() -> None:
    # Needed for on_text to see any text before the CLI exits (D-105).
    assert "--include-partial-messages" in build_args("claude")


def test_on_text_receives_each_chunk_as_the_cli_streams_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Shape assumed in _partial_text, not yet confirmed against a real run (see
    # planning/runner-notes.md).
    chunks = [
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hel"},
            },
        },
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "lo"},
            },
        },
    ]
    lines = [json.dumps(event) + "\n" for event in (*chunks, RESULT_OK)]
    process = _RunningProcess(stdout_lines=lines, returncode=0)
    monkeypatch.setattr(shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    seen: list[str] = []

    result = ClaudeCodeRunner(workdir=tmp_path).run("Reply with OK.", on_text=seen.append)

    assert seen == ["Hel", "lo"]
    assert result.ok is True
    assert result.text == "OK"


def test_on_text_is_not_called_for_non_text_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lines = [json.dumps(event) + "\n" for event in (ALLOWED_EVENT, RESULT_OK)]
    process = _RunningProcess(stdout_lines=lines, returncode=0)
    monkeypatch.setattr(shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    seen: list[str] = []

    ClaudeCodeRunner(workdir=tmp_path).run("Reply with OK.", on_text=seen.append)

    assert seen == []


def test_the_api_key_is_removed_from_the_environment_of_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    process = _RunningProcess()
    seen: dict[str, dict[str, str]] = {}

    def fake_popen(_args: list[str], **kwargs: Any) -> _RunningProcess:
        seen["env"] = kwargs["env"]
        process.returncode = 0
        return process

    monkeypatch.setattr(shutil, "which", lambda _name: "claude")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    ClaudeCodeRunner(workdir=tmp_path).run("Reply OK.")

    assert "ANTHROPIC_API_KEY" not in seen["env"]
