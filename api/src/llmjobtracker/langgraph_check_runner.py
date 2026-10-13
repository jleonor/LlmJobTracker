"""Proof-of-concept LangGraph wrapper for the listing sanity-check step (D-191, Phase 6).

Wraps a real Runner so its call runs inside a one-node LangGraph graph instead of being called
directly, proving a graph node can call Runner.run() on its own, with nothing here depending on
LangChain's model or prompt classes (D-191). Wired in only for JOB_KIND_CHECK, through
claude_job_queue.py's `runner_overrides` - every other job kind still calls its Runner directly,
unchanged.

No checkpointer: this step has no pause/resume/interrupt need of its own - ClaudeJobQueue already
owns pause-on-rate-limit around whatever Runner it calls (D-63) - so the graph is built and run
fresh on each call rather than persisted across one. A persisted, multi-node graph is a Phase 7
question, once the remaining pipelines migrate alongside a second runner (Codex).
"""

from collections.abc import Callable
from threading import Event
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from llmjobtracker.runner import Runner, RunResult


class _CheckGraphState(TypedDict):
    prompt: str
    result: RunResult | None


class LangGraphCheckRunner:
    """A Runner that routes its call through a single-node LangGraph graph."""

    def __init__(self, inner: Runner) -> None:
        self._inner = inner

    def run(
        self,
        prompt: str,
        cancel: Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> RunResult:
        def call_runner(state: _CheckGraphState) -> dict[str, RunResult]:
            result = self._inner.run(
                state["prompt"], cancel=cancel, json_schema=json_schema, on_text=on_text
            )
            return {"result": result}

        graph = StateGraph(_CheckGraphState)
        graph.add_node("call_runner", call_runner)
        graph.add_edge(START, "call_runner")
        graph.add_edge("call_runner", END)
        compiled = graph.compile()

        output = compiled.invoke({"prompt": prompt, "result": None})
        result = output["result"]
        assert isinstance(result, RunResult), "the graph's only node always sets result"
        return result
