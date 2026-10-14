"""Wraps any Runner so its call runs inside a one-node LangGraph graph (D-191, D-196).

Phase 6 built this for one job kind only, as a proof of concept (LangGraphCheckRunner). Phase 7
generalizes it - nothing about it was ever kind-specific - and uses it for every job kind: `app.py`
wraps the queue's default runner itself (`LangGraphRunner(runner)`), for whichever backend is
selected, rather than listing job kinds one at a time in `claude_job_queue.py`'s
`runner_overrides`. A node is a plain Python callable that calls Runner.run() directly, so nothing
here depends on LangChain's model or prompt classes (D-191); `Runner` stays the only Claude-Code/
Codex-aware seam (D-19/D-20).

No checkpointer: a job kind's own pause/resume/interrupt need, if it has one, is already owned by
ClaudeJobQueue's pause-on-rate-limit around whatever Runner it calls (D-63), so the graph is built
and run fresh on each call rather than persisted across one. A persisted, multi-node graph is a
later question, once an actual multi-step/agentic need exists - not before.
"""

from collections.abc import Callable
from threading import Event
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from llmjobtracker.runner import Runner, RunResult


class _GraphState(TypedDict):
    prompt: str
    result: RunResult | None


class LangGraphRunner:
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
        def call_runner(state: _GraphState) -> dict[str, RunResult]:
            result = self._inner.run(
                state["prompt"], cancel=cancel, json_schema=json_schema, on_text=on_text
            )
            return {"result": result}

        graph = StateGraph(_GraphState)
        graph.add_node("call_runner", call_runner)
        graph.add_edge(START, "call_runner")
        graph.add_edge("call_runner", END)
        compiled = graph.compile()

        output = compiled.invoke({"prompt": prompt, "result": None})
        result = output["result"]
        assert isinstance(result, RunResult), "the graph's only node always sets result"
        return result
