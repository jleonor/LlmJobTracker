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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from llmjobtracker.claude_jobs import (
    PromptRow,
    bump_retry_attempts,
    cancel_job,
    create_claude_job,
    job_status,
    next_queued_job_id,
    pause_job,
    prompt_rows,
    reset_retry_attempts,
    resume_due_jobs,
    resume_job,
    set_prompt_status,
    set_prompt_text,
    store_answer,
    transition,
    trigger_staged_jobs,
)
from llmjobtracker.pricing import compute_cost_usd
from llmjobtracker.runner import RateLimitError, Runner, RunResult
from llmjobtracker.settings import get_settings
from llmjobtracker.storage import connect

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
    skip_message: str = "Skipped: already in place."


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


def _fixed_interval_resume_at(interval_minutes: int) -> str:
    deadline = datetime.now(UTC) + timedelta(minutes=interval_minutes)
    return deadline.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fixed_interval_message(interval_minutes: int, attempt: int, max_attempts: int) -> str:
    return (
        f"Paused at a plan limit. Retrying automatically in {interval_minutes} minutes "
        f"(attempt {attempt} of {max_attempts}), or click Resume."
    )


def _gave_up_message(max_attempts: int) -> str:
    return (
        f"Paused at a plan limit. Stopped retrying automatically after {max_attempts} attempts "
        "with no success. Click Resume to try again."
    )


def _manual_only_message() -> str:
    return "Paused at a plan limit. Click Resume when you want the job to continue."


class ClaudeJobQueue:
    def __init__(
        self,
        db_path: Path,
        runner: Runner,
        on_result: OnResult | None = None,
        render: Renderer | None = None,
        runner_overrides: Mapping[str, Runner] | None = None,
    ) -> None:
        self._db_path = db_path
        self._runner = runner
        self._on_result = on_result
        self._render = render
        # A prompt kind in here runs against its own Runner instead of the default one (D-191's
        # LangGraph proof of concept uses this to route one job kind through a graph without
        # touching how every other kind is dispatched).
        self._runner_overrides = dict(runner_overrides) if runner_overrides else {}
        self._lock = threading.Lock()
        self._current: tuple[int, threading.Event] | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # The answer text streamed so far for the one prompt currently running (D-105), keyed
        # by (claude_job_id, position). Cleared once that prompt's run call returns, however it
        # ends — the prompt's own row is the record after that, not this.
        self._live: dict[tuple[int, int], str] = {}

    # Calls from the API, or from code that starts work.

    def submit(
        self,
        conn: sqlite3.Connection,
        label: str,
        kind: str,
        prompts: Sequence[tuple[str, str]],
        job_application_id: int | None = None,
        lane_id: int | None = None,
        open_application_id: int | None = None,
        status: str = "queued",
    ) -> int:
        job_id = create_claude_job(
            conn,
            label,
            kind,
            prompts,
            job_application_id,
            lane_id,
            open_application_id,
            status=status,
        )
        if status == "queued":
            self.wake()
        return job_id

    def resume(self, conn: sqlite3.Connection, job_id: int) -> bool:
        resumed = resume_job(conn, job_id)
        if resumed:
            self.wake()
        return resumed

    def trigger_staged(self, conn: sqlite3.Connection) -> list[int]:
        """Start every staged Claude Job at once (D-286/D-288's header button)."""
        triggered = trigger_staged_jobs(conn)
        if triggered:
            self.wake()
        return triggered

    def cancel(self, conn: sqlite3.Connection, job_id: int) -> bool:
        cancelled = cancel_job(conn, job_id)
        with self._lock:
            if cancelled and self._current is not None and self._current[0] == job_id:
                self._current[1].set()
        return cancelled

    def wake(self) -> None:
        self._wake.set()

    def set_runner(self, runner: Runner) -> None:
        """Switch the default runner (D-195: one global backend for the whole app).

        A job already dispatching (`_run_job`) snapshots the default runner it started with, so
        an in-flight job finishes on that runner even if this is called mid-job; only the next
        job to start picks up the new one.
        """
        with self._lock:
            self._runner = runner

    def live_text(self, job_id: int, position: int) -> str | None:
        """The answer text streamed so far for a running prompt, or None if it isn't live."""
        with self._lock:
            return self._live.get((job_id, position))

    def _pause_plan(
        self, conn: sqlite3.Connection, job_id: int, limit: RateLimitError
    ) -> tuple[str, str | None]:
        """What to tell the user and when to auto-resume, per the selected retry policy
        (D-201). Returns (message, resume_at) for `pause_job`."""
        settings = get_settings(conn)
        if settings.retry_policy == "manual_only":
            return _manual_only_message(), None
        if settings.retry_policy == "fixed_interval":
            attempt = bump_retry_attempts(conn, job_id)
            if attempt > settings.retry_max_attempts:
                return _gave_up_message(settings.retry_max_attempts), None
            resume_at = _fixed_interval_resume_at(settings.retry_interval_minutes)
            message = _fixed_interval_message(
                settings.retry_interval_minutes, attempt, settings.retry_max_attempts
            )
            return message, resume_at
        # "reset_time": today's D-75 default, unchanged.
        return _paused_message(limit), _resume_time(limit)

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
        # Snapshotted once per job, not re-read per prompt: a backend switch (set_runner) mid-job
        # must not change which runner an already-running job uses (D-195).
        with self._lock:
            default_runner = self._runner
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
                        result_text=rendered.skip_message,
                    )
                    continue
                text, schema = rendered.text, rendered.json_schema
                set_prompt_text(conn, prompt.id, text)

            key = (job_id, prompt.position)

            def on_text(chunk: str, key: tuple[int, int] = key) -> None:
                with self._lock:
                    self._live[key] = self._live.get(key, "") + chunk

            with self._lock:
                self._live[key] = ""
            runner = self._runner_overrides.get(prompt.prompt_kind, default_runner)
            try:
                try:
                    result = runner.run(text, cancel=cancel, json_schema=schema, on_text=on_text)
                except RateLimitError as limit:
                    if self._stop.is_set():
                        return
                    set_prompt_status(conn, prompt.id, ("running",), "queued")
                    message, resume_at = self._pause_plan(conn, job_id, limit)
                    pause_job(conn, job_id, message, resume_at)
                    return
                except Exception as error:
                    if self._stop.is_set():
                        return
                    self._fail_prompt(
                        conn, job_id, prompt.id, f"The run failed: {error}", None, None
                    )
                    return
            finally:
                with self._lock:
                    self._live.pop(key, None)
            if result.text:
                store_answer(conn, prompt.id, result.text)
            if self._stop.is_set():
                return
            if cancel.is_set():
                set_prompt_status(conn, prompt.id, ("running",), "cancelled", error="Cancelled.")
                return
            # The runner's own cost if it gave one (Claude Code), else computed from its tokens
            # and the stored price table (Codex, D-197/D-198) - never a guess either way.
            cost_usd = compute_cost_usd(conn, result)
            if not result.ok:
                self._fail_prompt(
                    conn,
                    job_id,
                    prompt.id,
                    result.error,
                    cost_usd,
                    result.duration_ms,
                    result.input_tokens,
                    result.output_tokens,
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
                    cost_usd,
                    result.duration_ms,
                    result.input_tokens,
                    result.output_tokens,
                )
                return
            set_prompt_status(
                conn,
                prompt.id,
                ("running",),
                "done",
                result_text=result.text,
                cost_usd=cost_usd,
                duration_ms=result.duration_ms,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            # A successful prompt breaks the fixed_interval policy's consecutive-pause streak
            # (D-201), the same as a manual Resume does.
            reset_retry_attempts(conn, job_id)
        transition(conn, job_id, ("processing",), "done")

    def _fail_prompt(
        self,
        conn: sqlite3.Connection,
        job_id: int,
        prompt_id: int,
        message: str | None,
        cost_usd: float | None,
        duration_ms: int | None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        set_prompt_status(
            conn,
            prompt_id,
            ("running", "queued"),
            "failed",
            error=message,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        transition(conn, job_id, ("processing",), "failed", error=message)
