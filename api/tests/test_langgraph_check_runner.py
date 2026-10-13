"""Tests for the Phase 6 LangGraph proof of concept (D-191): LangGraphCheckRunner must behave
exactly like the Runner it wraps - same result, same rate-limit behaviour, same streaming - since
it is a drop-in replacement wired in only for JOB_KIND_CHECK (claude_job_queue.py).
"""

import threading

import pytest

from llmjobtracker.langgraph_check_runner import LangGraphCheckRunner
from llmjobtracker.runner import FakeRunner, RateLimitError, RunResult


def test_the_graph_s_node_calls_the_wrapped_runner_and_returns_its_result() -> None:
    inner = FakeRunner(text="LOOKS_LIKE_A_JOB_POSTING: yes\nreason")
    graph_runner = LangGraphCheckRunner(inner)

    result = graph_runner.run("Senior Data Analyst, must know SQL.")

    assert result.ok
    assert result.text == "LOOKS_LIKE_A_JOB_POSTING: yes\nreason"
    assert inner.prompts == ["Senior Data Analyst, must know SQL."]


def test_a_rate_limit_from_the_wrapped_runner_propagates_through_the_graph() -> None:
    inner = FakeRunner()
    inner.rate_limit_next(times=1)
    graph_runner = LangGraphCheckRunner(inner)

    with pytest.raises(RateLimitError):
        graph_runner.run("some text")


def test_streaming_is_passed_through_to_the_wrapped_runner() -> None:
    inner = FakeRunner(text="done")
    inner.stream_chunks = ["chunk one", "chunk two"]
    graph_runner = LangGraphCheckRunner(inner)
    seen: list[str] = []

    result = graph_runner.run("some text", on_text=seen.append)

    assert result.text == "done"
    assert seen == ["chunk one", "chunk two"]


def test_cancel_and_json_schema_reach_the_wrapped_runner_unchanged() -> None:
    received: dict[str, object] = {}

    class RecordingRunner:
        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, object] | None = None,
            on_text: object = None,
        ) -> RunResult:
            received["prompt"] = prompt
            received["cancel"] = cancel
            received["json_schema"] = json_schema
            return RunResult(ok=True, text="ok")

    cancel = threading.Event()
    schema = {"type": "object"}
    graph_runner = LangGraphCheckRunner(RecordingRunner())

    graph_runner.run("some text", cancel=cancel, json_schema=schema)

    assert received == {"prompt": "some text", "cancel": cancel, "json_schema": schema}
