import json
import shutil
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest

from localjobtracker.claude_code_runner import (
    MAX_BUDGET_USD,
    ClaudeCodeRunner,
    build_args,
    parse_stream,
)
from localjobtracker.runner import FakeRunner, RateLimitError

REQUIRED_FLAGS = [
    "--restricted",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-prompts",
    "none",
    "--max-budget-usd",
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
    args = build_args("claude", "Reply with OK.")
    for flag in REQUIRED_FLAGS:
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--max-budget-usd") + 1] == MAX_BUDGET_USD
    assert args[1:3] == ["-p", "Reply with OK."]


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


class _RunningProcess:
    """Stands in for a CLI process that keeps running until it is terminated."""

    def __init__(self) -> None:
        self.terminated = False
        self.returncode: int | None = None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        if self.terminated:
            self.returncode = 143
            return "", ""
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


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
