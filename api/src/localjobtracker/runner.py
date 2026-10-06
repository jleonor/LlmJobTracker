"""The runner seam. The app talks to a Runner. Only ClaudeCodeRunner knows Claude Code (D-20)."""

import threading
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel


class RunResult(BaseModel):
    ok: bool
    text: str = ""
    error: str | None = None
    duration_ms: int = 0
    cost_usd: float | None = None
    # The model the run used, as the CLI reports it.
    model: str | None = None


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
    ) -> RunResult:
        """Run one prompt. Raise RateLimitError when the plan's limit is hit.

        When `cancel` is set during the run, the runner stops the run and returns a failed
        RunResult (SIGTERM for the CLI, runner-notes.md). `json_schema` asks for an answer that
        follows the schema (the CLI's --json-schema flag).
        """
        ...


class FakeRunner:
    """Returns a fixed answer without calling a model. Used by tests and offline development."""

    def __init__(self, text: str = "OK") -> None:
        self.text = text
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any] | None] = []
        self._rate_limits_left = 0

    def rate_limit_next(self, times: int = 1) -> None:
        """Make the next `times` calls raise RateLimitError, as a plan limit would."""
        self._rate_limits_left = times

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> RunResult:
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        if self._rate_limits_left > 0:
            self._rate_limits_left -= 1
            raise RateLimitError("Simulated plan limit (fake runner).")
        return RunResult(ok=True, text=self.text, duration_ms=0, cost_usd=0.0, model="fake-model")
