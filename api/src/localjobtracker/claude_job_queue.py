"""The Claude Jobs queue: one worker that runs queued jobs in creation order (D-50, D-51).

The queue sits between the app and the Runner. It knows the Runner interface, never the CLI
(D-20). The runner reports a plan limit as RateLimitError, and the queue pauses the job on it
(D-63). A job stays paused until the user resumes it.

Every database change is a conditional update (see claude_jobs.transition), so a cancel that
lands during a run wins over the worker's own update.
"""

import logging
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

from localjobtracker.claude_jobs import (
    PromptRow,
    cancel_job,
    create_claude_job,
    job_status,
    next_queued_job_id,
    pause_job,
    prompt_rows,
    resume_due_jobs,
    resume_job,
    set_prompt_status,
    set_prompt_text,
    transition,
)
from localjobtracker.runner import RateLimitError, Runner, RunResult
from localjobtracker.storage import connect

logger = logging.getLogger(__name__)

# How long the idle worker waits before checking again. A submit or resume wakes it sooner.
IDLE_POLL_S = 5.0


class PromptRejected(Exception):
    """Raised by an `on_result` handler when a prompt's output fails its checks."""


OnResult = Callable[[sqlite3.Connection, PromptRow, RunResult], None]


@dataclass(frozen=True)
class RenderedPrompt:
    """A prompt built just before it runs, with the schema its answer must follow."""

    text: str
    json_schema: dict[str, Any] | None = None
    # True when the output is already in place. The prompt is then not sent (D-69).
    skip: bool = False


# Builds a prompt from what earlier prompts have stored. Raise PromptRejected if it cannot.
Renderer = Callable[[sqlite3.Connection, PromptRow], RenderedPrompt]


# A job resumes a little after the reset the CLI reports, so the limit is clear by then.
RESUME_MARGIN = timedelta(minutes=2)


def _paused_message(limit: RateLimitError) -> str:
    if limit.resets_at is None:
        return "Paused at a plan limit. Resume when you want the job to continue."
    reset = limit.resets_at.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"Paused at a plan limit. It resumes by itself after the limit resets at {reset}, "
        "or click Resume."
    )


def _resume_time(limit: RateLimitError) -> str | None:
    if limit.resets_at is None:
        return None
    return (limit.resets_at + RESUME_MARGIN).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ClaudeJobQueue:
    def __init__(
        self,
        db_path: Path,
        runner: Runner,
        on_result: OnResult | None = None,
        render: Renderer | None = None,
    ) -> None:
        self._db_path = db_path
        self._runner = runner
        self._on_result = on_result
        self._render = render
        self._lock = threading.Lock()
        self._current: tuple[int, threading.Event] | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # Calls from the API, or from code that starts work.

    def submit(
        self,
        conn: sqlite3.Connection,
        label: str,
        kind: str,
        prompts: Sequence[tuple[str, str]],
        job_application_id: int | None = None,
    ) -> int:
        job_id = create_claude_job(conn, label, kind, prompts, job_application_id)
        self.wake()
        return job_id

    def resume(self, conn: sqlite3.Connection, job_id: int) -> bool:
        resumed = resume_job(conn, job_id)
        if resumed:
            self.wake()
        return resumed

    def cancel(self, conn: sqlite3.Connection, job_id: int) -> bool:
        cancelled = cancel_job(conn, job_id)
        with self._lock:
            if cancelled and self._current is not None and self._current[0] == job_id:
                self._current[1].set()
        return cancelled

    def wake(self) -> None:
        self._wake.set()

    # The worker thread.

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="claude-job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 10.0) -> None:
        """Stop the worker. A running prompt is terminated, and its job stays processing.

        The next start turns that job back into a queued job (claude_jobs.recover_interrupted).
        """
        self._stop.set()
        with self._lock:
            if self._current is not None:
                self._current[1].set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                worked = self.process_next()
            except Exception:
                logger.exception("The Claude Job worker stopped one step with an error.")
                worked = False
            if not worked:
                self._wake.wait(IDLE_POLL_S)

    def process_next(self) -> bool:
        """Run the oldest queued job, if there is one. Returns True if a job was looked at.

        The loop calls this. Tests call it directly, so they can step through the queue.
        """
        conn = connect(self._db_path)
        try:
            resume_due_jobs(conn)
            job_id = next_queued_job_id(conn)
            if job_id is None:
                return False
            if not transition(conn, job_id, ("queued",), "processing"):
                return True
            cancel = threading.Event()
            with self._lock:
                self._current = (job_id, cancel)
            try:
                self._run_job(conn, job_id, cancel)
            finally:
                with self._lock:
                    self._current = None
            return True
        finally:
            conn.close()

    def _run_job(self, conn: sqlite3.Connection, job_id: int, cancel: threading.Event) -> None:
        for prompt in prompt_rows(conn, job_id):
            if prompt.status == "done":
                continue
            if self._stop.is_set() or job_status(conn, job_id) != "processing":
                return
            set_prompt_status(conn, prompt.id, ("queued",), "running")
            text, schema = prompt.prompt_text, None
            if self._render is not None:
                try:
                    rendered = self._render(conn, prompt)
                except PromptRejected as rejected:
                    self._fail_prompt(conn, job_id, prompt.id, str(rejected), None, None)
                    return
                except Exception as error:
                    # Any other failure still ends the job with a message, not in processing.
                    self._fail_prompt(
                        conn, job_id, prompt.id, f"Could not build the prompt: {error}", None, None
                    )
                    return
                if rendered.skip:
                    set_prompt_status(
                        conn,
                        prompt.id,
                        ("running",),
                        "done",
                        result_text="Skipped: already in place.",
                    )
                    continue
                text, schema = rendered.text, rendered.json_schema
                set_prompt_text(conn, prompt.id, text)
            try:
                result = self._runner.run(text, cancel=cancel, json_schema=schema)
            except RateLimitError as limit:
                if self._stop.is_set():
                    return
                set_prompt_status(conn, prompt.id, ("running",), "queued")
                pause_job(conn, job_id, _paused_message(limit), _resume_time(limit))
                return
            except Exception as error:
                if self._stop.is_set():
                    return
                self._fail_prompt(conn, job_id, prompt.id, f"The run failed: {error}", None, None)
                return
            if self._stop.is_set():
                return
            if cancel.is_set():
                set_prompt_status(conn, prompt.id, ("running",), "cancelled", error="Cancelled.")
                return
            if not result.ok:
                self._fail_prompt(
                    conn, job_id, prompt.id, result.error, result.cost_usd, result.duration_ms
                )
                return
            try:
                if self._on_result is not None:
                    self._on_result(conn, prompt, result)
            except PromptRejected as rejected:
                self._fail_prompt(
                    conn,
                    job_id,
                    prompt.id,
                    str(rejected),
                    result.cost_usd,
                    result.duration_ms,
                )
                return
            set_prompt_status(
                conn,
                prompt.id,
                ("running",),
                "done",
                result_text=result.text,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                model=result.model,
            )
        transition(conn, job_id, ("processing",), "done")

    def _fail_prompt(
        self,
        conn: sqlite3.Connection,
        job_id: int,
        prompt_id: int,
        message: str | None,
        cost_usd: float | None,
        duration_ms: int | None,
    ) -> None:
        set_prompt_status(
            conn,
            prompt_id,
            ("running", "queued"),
            "failed",
            error=message,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
        )
        transition(conn, job_id, ("processing",), "failed", error=message)
