"""The runner seam. The app talks to a Runner. Only ClaudeCodeRunner knows Claude Code (D-20)."""

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel


class RunResult(BaseModel):
    ok: bool
    text: str = ""
    error: str | None = None
    duration_ms: int = 0
    # A dollar figure only when the backend hands one back directly (Claude Code's CLI does;
    # Codex and a future direct provider API don't - runner-backends.md). Left None otherwise;
    # the queue computes a cost from the token fields below and the price table (pricing.md).
    cost_usd: float | None = None
    # The model the run used. When a backend's own output doesn't say which model served the
    # request (confirmed true of Codex - runner-notes.md), this is the model explicitly
    # requested, not a value parsed from nothing.
    model: str | None = None
    # Token counts (D-197), when the backend reports them. Unlike cost_usd, every backend is
    # expected to supply these.
    input_tokens: int | None = None
    output_tokens: int | None = None


class AuthStatus(BaseModel):
    """Whether a backend's CLI is currently logged in (D-203), and a short human-readable detail
    (e.g. the account email, or why the check couldn't run). Checked by running the CLI's own
    status command - never by reading its credential files directly."""

    logged_in: bool
    detail: str


class RateLimitError(Exception):
    """The plan's limit was hit. The queue pauses on this error, not on RunResult (D-51, D-63).

    `resets_at` is the time the CLI reports for the limit window to end, when it reports one.
    """

    def __init__(self, message: str, resets_at: datetime | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.resets_at = resets_at


class Runner(Protocol):
    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Run one prompt. Raise RateLimitError when the plan's limit is hit.

        When `cancel` is set during the run, the runner stops the run and returns a failed
        RunResult (SIGTERM for the CLI, runner-notes.md). `json_schema` asks for an answer that
        follows the schema (the CLI's --json-schema flag). `on_text`, when given, is called with
        each chunk of the answer's text as it streams in (D-105) — a runner that cannot stream
        simply never calls it.
        """
        ...


class FakeRunner:
    """Returns a fixed answer without calling a model. Used by tests and offline development."""

    def __init__(
        self,
        text: str = "OK",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any] | None] = []
        # Chunks replayed through on_text before the result is returned, so tests can simulate
        # a streamed answer without knowing anything about Claude Code's own event shape.
        self.stream_chunks: list[str] = []
        self._rate_limits_left = 0
        self._resets_at: datetime | None = None

    def rate_limit_next(self, times: int = 1, resets_at: datetime | None = None) -> None:
        """Make the next `times` calls raise RateLimitError, as a plan limit would."""
        self._rate_limits_left = times
        self._resets_at = resets_at

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> RunResult:
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        if self._rate_limits_left > 0:
            self._rate_limits_left -= 1
            raise RateLimitError("Simulated plan limit (fake runner).", self._resets_at)
        if on_text is not None:
            for chunk in self.stream_chunks:
                on_text(chunk)
        return RunResult(
            ok=True,
            text=self.text,
            duration_ms=0,
            cost_usd=0.0,
            model="fake-model",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )
