"""The runner seam. The app talks to a Runner. Only ClaudeCodeRunner knows Claude Code (D-20)."""

from typing import Protocol

from pydantic import BaseModel


class RunResult(BaseModel):
    ok: bool
    text: str = ""
    error: str | None = None
    duration_ms: int = 0
    cost_usd: float | None = None


class Runner(Protocol):
    def run(self, prompt: str) -> RunResult: ...


class FakeRunner:
    """Returns a fixed answer without calling a model. Used by tests and offline development."""

    def __init__(self, text: str = "OK") -> None:
        self.text = text
        self.prompts: list[str] = []

    def run(self, prompt: str) -> RunResult:
        self.prompts.append(prompt)
        return RunResult(ok=True, text=self.text, duration_ms=0, cost_usd=0.0)
