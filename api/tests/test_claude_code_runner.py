import json
import shutil
from pathlib import Path

import pytest

from localjobtracker.claude_code_runner import (
    MAX_BUDGET_USD,
    ClaudeCodeRunner,
    build_args,
    parse_output,
)

REQUIRED_FLAGS = [
    "--restricted",
    "--strict-mcp-config",
    "--no-session-persistence",
    "--output-format",
    "json",
    "--permission-prompts",
    "none",
    "--max-budget-usd",
]


def test_build_args_keeps_every_run_restricted() -> None:
    args = build_args("claude", "Reply with OK.")
    for flag in REQUIRED_FLAGS:
        assert flag in args
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--max-budget-usd") + 1] == MAX_BUDGET_USD
    assert args[1:3] == ["-p", "Reply with OK."]


def test_parse_success_reads_result_text_and_cost() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "OK",
            "total_cost_usd": 0.0106,
        }
    )
    parsed = parse_output(stdout, exit_code=0, duration_ms=12)
    assert parsed.ok is True
    assert parsed.text == "OK"
    assert parsed.cost_usd == pytest.approx(0.0106)
    assert parsed.duration_ms == 12


def test_parse_error_flag_fails_even_with_exit_zero() -> None:
    stdout = json.dumps(
        {
            "type": "result",
            "subtype": "error_max_budget",
            "is_error": True,
            "result": "",
            "total_cost_usd": 0.3,
        }
    )
    parsed = parse_output(stdout, exit_code=0, duration_ms=5)
    assert parsed.ok is False
    assert parsed.error == "Claude Code run failed (error_max_budget)."


def test_parse_non_zero_exit_fails() -> None:
    parsed = parse_output("{}", exit_code=1, duration_ms=5)
    assert parsed.ok is False


def test_parse_non_json_output_fails() -> None:
    parsed = parse_output("not json at all", exit_code=0, duration_ms=5)
    assert parsed.ok is False
    assert "did not return JSON" in (parsed.error or "")


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
