import sqlite3
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job, job_status
from llmjobtracker.runner import FakeRunner, Runner, RunResult
from llmjobtracker.settings import get_settings, save_settings
from llmjobtracker.storage import connect

TOKEN = "test-token"


def submit(db_path: Path, queue: ClaudeJobQueue, label: str, prompts: list[str]) -> int:
    conn = connect(db_path)
    try:
        return queue.submit(conn, label, "profile", [("step", text) for text in prompts])
    finally:
        conn.close()


def client_for(db_path: Path, runner: Runner) -> TestClient:
    test_client = TestClient(create_app(TOKEN, db_path, runner))
    test_client.headers[TOKEN_HEADER] = TOKEN
    return test_client


def queue_of(client: TestClient) -> ClaudeJobQueue:
    app = client.app
    assert isinstance(app, FastAPI)
    queue: ClaudeJobQueue = app.state.queue
    return queue


def read_job(db_path: Path, job_id: int) -> tuple[str, list[str]]:
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        return job.status, [prompt.status for prompt in job.prompts]
    finally:
        conn.close()


@pytest.fixture
def fake_client(db_path: Path, runner: FakeRunner) -> Iterator[TestClient]:
    with client_for(db_path, runner) as test_client:
        yield test_client


def test_queued_prompts_run_in_order_and_the_job_is_done(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "first", ["one", "two", "three"])

    assert queue.process_next() is True
    assert runner.prompts == ["one", "two", "three"]
    assert read_job(db_path, job_id) == ("done", ["done", "done", "done"])
    assert queue.process_next() is False


def test_jobs_run_one_at_a_time_in_creation_order(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    first = submit(db_path, queue, "first", ["a1", "a2"])
    second = submit(db_path, queue, "second", ["b1"])

    while queue.process_next():
        pass

    assert runner.prompts == ["a1", "a2", "b1"]
    assert read_job(db_path, first)[0] == "done"
    assert read_job(db_path, second)[0] == "done"


def test_a_plan_limit_pauses_the_job_and_resume_runs_the_prompt_again(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "limited", ["one", "two"])
    runner.rate_limit_next(times=1)

    queue.process_next()
    status, prompt_statuses = read_job(db_path, job_id)
    assert status == "paused"
    assert prompt_statuses == ["queued", "queued"]
    assert queue.process_next() is False
    assert runner.prompts == ["one"]

    resumed = fake_client.post(f"/claude-jobs/{job_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"

    while queue.process_next():
        pass
    assert runner.prompts == ["one", "one", "two"]
    assert read_job(db_path, job_id) == ("done", ["done", "done"])


def test_paused_job_message_says_it_is_paused_at_a_limit(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "limited", ["one"])
    runner.rate_limit_next(times=1)
    queue.process_next()

    job = fake_client.get("/claude-jobs").json()[0]
    assert job["id"] == job_id
    assert job["status"] == "paused"
    assert "Paused at a plan limit" in job["error"]


def test_resume_is_refused_unless_the_job_is_paused(db_path: Path, fake_client: TestClient) -> None:
    job_id = submit(db_path, queue_of(fake_client), "queued", ["one"])
    assert fake_client.post(f"/claude-jobs/{job_id}/resume").status_code == 409


def test_a_failed_prompt_fails_the_job_and_skips_the_rest(db_path: Path) -> None:
    class FailingRunner:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            self.prompts.append(prompt)
            return RunResult(ok=False, error="Claude Code run failed (error_max_budget).")

    failing = FailingRunner()
    queue = ClaudeJobQueue(db_path, failing)
    job_id = submit(db_path, queue, "broken", ["one", "two"])

    queue.process_next()
    assert failing.prompts == ["one"]
    status, prompt_statuses = read_job(db_path, job_id)
    assert status == "failed"
    assert prompt_statuses == ["failed", "queued"]


def test_a_rejected_output_fails_its_prompt(db_path: Path, runner: FakeRunner) -> None:
    def reject(_conn: sqlite3.Connection, _prompt: object, _result: RunResult) -> None:
        raise PromptRejected("A fact has no source.")

    queue = ClaudeJobQueue(db_path, runner, on_result=reject)
    job_id = submit(db_path, queue, "checked", ["one"])
    queue.process_next()

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "failed"
    assert job.error == "A fact has no source."
    assert job.prompts[0].status == "failed"


def test_a_job_paused_before_a_restart_is_still_paused_after_it(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "limited", ["one", "two"])
    runner.rate_limit_next(times=1)
    queue.process_next()
    fake_client.close()

    with client_for(db_path, FakeRunner()) as restarted:
        assert restarted.get("/claude-jobs").json()[0]["status"] == "paused"
    assert read_job(db_path, job_id)[0] == "paused"


def test_a_job_interrupted_mid_prompt_is_queued_again_after_a_restart(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "interrupted", ["one", "two"])
    queue.process_next()  # prompt one is done, the job is done
    # Simulate a stop in the middle of prompt two: prompt one stays done, prompt two is running.
    conn = connect(db_path)
    try:
        conn.execute("UPDATE claude_jobs SET status = 'processing' WHERE id = ?", (job_id,))
        conn.execute(
            "UPDATE claude_job_prompts SET status = 'running' WHERE claude_job_id = ? "
            "AND position = 1",
            (job_id,),
        )
        conn.commit()
    finally:
        conn.close()
    fake_client.close()

    restarted_runner = FakeRunner()
    with client_for(db_path, restarted_runner) as restarted:
        assert read_job(db_path, job_id) == ("queued", ["done", "queued"])
        queue_of(restarted).process_next()
    assert restarted_runner.prompts == ["two"]
    assert read_job(db_path, job_id) == ("done", ["done", "done"])


def test_cancel_a_queued_job_marks_its_prompts_cancelled(
    db_path: Path, runner: FakeRunner, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    job_id = submit(db_path, queue, "not yet", ["one", "two"])

    cancelled = fake_client.post(f"/claude-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert read_job(db_path, job_id) == ("cancelled", ["cancelled", "cancelled"])
    assert fake_client.post(f"/claude-jobs/{job_id}/cancel").status_code == 409
    assert queue.process_next() is False
    assert runner.prompts == []


def test_cancel_during_a_run_stops_the_prompt_and_keeps_the_job_cancelled(
    db_path: Path,
) -> None:
    class BlockingRunner:
        def __init__(self) -> None:
            self.started = threading.Event()

        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            self.started.set()
            assert cancel is not None
            cancel.wait(5)
            return RunResult(ok=False, error="Cancelled.")

    blocking = BlockingRunner()
    with client_for(db_path, blocking) as client:
        queue = queue_of(client)
        job_id = submit(db_path, queue, "running", ["one", "two"])
        worker = threading.Thread(target=queue.process_next)
        worker.start()
        assert blocking.started.wait(5)

        assert client.post(f"/claude-jobs/{job_id}/cancel").status_code == 200
        worker.join(5)

    assert not worker.is_alive()
    assert read_job(db_path, job_id) == ("cancelled", ["cancelled", "cancelled"])


def test_live_text_is_visible_while_running_and_clears_once_it_is_not(db_path: Path) -> None:
    class StreamingRunner:
        def __init__(self) -> None:
            self.chunks_sent = threading.Event()
            self.release = threading.Event()

        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            assert on_text is not None
            on_text("Hel")
            on_text("lo")
            self.chunks_sent.set()
            self.release.wait(5)
            return RunResult(ok=True, text="Hello", duration_ms=1, cost_usd=0.0, model="fake")

    streaming = StreamingRunner()
    queue = ClaudeJobQueue(db_path, streaming)
    job_id = submit(db_path, queue, "live", ["one"])
    assert queue.live_text(job_id, 0) is None  # not running yet

    worker = threading.Thread(target=queue.process_next)
    worker.start()
    assert streaming.chunks_sent.wait(5)

    assert queue.live_text(job_id, 0) == "Hello"

    streaming.release.set()
    worker.join(5)
    assert queue.live_text(job_id, 0) is None  # cleared once the prompt is done
    assert read_job(db_path, job_id) == ("done", ["done"])


def test_the_claude_jobs_list_carries_live_text_for_the_running_prompt(
    db_path: Path,
) -> None:
    class StreamingRunner:
        def __init__(self) -> None:
            self.chunk_sent = threading.Event()
            self.release = threading.Event()

        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            assert on_text is not None
            on_text("Streaming")
            self.chunk_sent.set()
            self.release.wait(5)
            return RunResult(ok=True, text="Streaming answer", duration_ms=1, cost_usd=0.0)

    streaming = StreamingRunner()
    with client_for(db_path, streaming) as client:
        queue = queue_of(client)
        job_id = submit(db_path, queue, "live", ["one"])
        worker = threading.Thread(target=queue.process_next)
        worker.start()
        assert streaming.chunk_sent.wait(5)

        prompt = client.get("/claude-jobs").json()[0]["prompts"][0]
        assert prompt["status"] == "running"
        assert prompt["live_text"] == "Streaming"

        streaming.release.set()
        worker.join(5)

        prompt = client.get("/claude-jobs").json()[0]["prompts"][0]
        assert prompt["live_text"] is None
    assert read_job(db_path, job_id) == ("done", ["done"])


def test_list_is_in_creation_order_and_hides_prompt_text(
    db_path: Path, fake_client: TestClient
) -> None:
    queue = queue_of(fake_client)
    submit(db_path, queue, "first", ["secret text"])
    submit(db_path, queue, "second", ["more"])

    jobs = fake_client.get("/claude-jobs").json()
    assert [job["label"] for job in jobs] == ["first", "second"]
    assert "secret text" not in str(jobs)
    conn = connect(db_path)
    try:
        assert job_status(conn, jobs[0]["id"]) == "queued"
    finally:
        conn.close()


def test_an_unexpected_runner_error_fails_the_job_with_a_message(db_path: Path) -> None:
    class BrokenRunner:
        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            raise OSError("The filename or extension is too long")

    queue = ClaudeJobQueue(db_path, BrokenRunner())
    job_id = submit(db_path, queue, "broken", ["one"])

    queue.process_next()

    status, prompt_statuses = read_job(db_path, job_id)
    assert status == "failed"
    assert prompt_statuses == ["failed"]
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None and job.error is not None
    assert "The run failed" in job.error and "too long" in job.error


def test_a_finished_prompt_records_its_model_and_times(db_path: Path, runner: FakeRunner) -> None:
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "timed", ["one", "two"])

    queue.process_next()

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    first = job.prompts[0]
    assert first.model == "fake-model"
    assert first.started_at is not None and first.finished_at is not None
    assert first.skipped is False


def test_a_limit_with_a_reset_time_resumes_the_job_by_itself(db_path: Path) -> None:
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=1, resets_at=datetime.now(UTC) - timedelta(minutes=5))
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "auto", ["one"])

    queue.process_next()  # paused at the limit, with a reset time already past
    assert read_job(db_path, job_id)[0] == "paused"
    queue.process_next()  # the worker resumes it, and it runs

    assert read_job(db_path, job_id) == ("done", ["done"])


def test_a_limit_with_a_future_reset_waits_and_records_the_time(db_path: Path) -> None:
    runner = FakeRunner(text="done")
    reset = datetime.now(UTC) + timedelta(hours=2)
    runner.rate_limit_next(times=1, resets_at=reset)
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "waiting", ["one"])

    queue.process_next()
    queue.process_next()

    assert read_job(db_path, job_id)[0] == "paused"
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None and job.resume_at is not None
    assert job.resume_at > datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_manual_resume_clears_the_reset_time(db_path: Path) -> None:
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=1, resets_at=datetime.now(UTC) + timedelta(hours=1))
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "manual", ["one"])
    queue.process_next()

    conn = connect(db_path)
    try:
        assert queue.resume(conn, job_id) is True
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None and job.resume_at is None


def _set_retry_policy(
    db_path: Path,
    retry_policy: str,
    *,
    retry_interval_minutes: int = 60,
    retry_max_attempts: int = 24,
) -> None:
    conn = connect(db_path)
    try:
        save_settings(
            conn,
            "YourName",
            "claude_code",
            retry_policy,
            retry_interval_minutes,
            retry_max_attempts,
            "claude-sonnet-5",
            "gpt-6.1-sol",
            None,
        )
        conn.commit()
    finally:
        conn.close()


def _force_resume_at_the_past(db_path: Path, job_id: int) -> None:
    """Makes a job's scheduled auto-resume due right now, without a real wait (D-201 tests)."""
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE claude_jobs SET resume_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_manual_only_policy_never_schedules_an_auto_resume(db_path: Path) -> None:
    _set_retry_policy(db_path, "manual_only")
    runner = FakeRunner(text="done")
    # Even a reset time already in the past (reset_time's own policy would auto-resume on this).
    runner.rate_limit_next(times=1, resets_at=datetime.now(UTC) - timedelta(minutes=5))
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "manual-only", ["one"])

    queue.process_next()
    assert queue.process_next() is False  # nothing due - no job was auto-resumed

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "paused"
    assert job.resume_at is None
    assert "Click Resume" in (job.error or "")


def test_fixed_interval_policy_schedules_a_resume_at_the_configured_interval(
    db_path: Path,
) -> None:
    _set_retry_policy(db_path, "fixed_interval", retry_interval_minutes=30, retry_max_attempts=5)
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=1)  # no resets_at at all - fixed_interval ignores it either way
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "fixed", ["one"])

    queue.process_next()

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "paused"
    assert job.retry_attempts == 1
    assert job.resume_at is not None
    expected = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
    assert job.resume_at.startswith(expected)
    assert "attempt 1 of 5" in (job.error or "")


def test_fixed_interval_policy_gives_up_after_max_attempts(db_path: Path) -> None:
    _set_retry_policy(db_path, "fixed_interval", retry_interval_minutes=1, retry_max_attempts=2)
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=3)
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "gives-up", ["one"])

    queue.process_next()  # attempt 1, paused with a resume_at
    _force_resume_at_the_past(db_path, job_id)
    queue.process_next()  # auto-resumed, hits the limit again: attempt 2, still allowed
    _force_resume_at_the_past(db_path, job_id)
    queue.process_next()  # auto-resumed, hits the limit a third time: attempt 3, gives up

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "paused"
    assert job.retry_attempts == 3
    assert job.resume_at is None  # no more auto-resume scheduled
    assert "Stopped retrying automatically after 2 attempts" in (job.error or "")

    # Still stuck, since there is nothing left to auto-resume.
    assert queue.process_next() is False


def test_a_successful_prompt_resets_the_retry_attempts_counter(db_path: Path) -> None:
    _set_retry_policy(db_path, "fixed_interval", retry_interval_minutes=1, retry_max_attempts=5)
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=1)
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "recovers", ["one"])

    queue.process_next()  # attempt 1, paused
    _force_resume_at_the_past(db_path, job_id)
    queue.process_next()  # auto-resumed, this time it succeeds

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "done"
    assert job.retry_attempts == 0


def test_a_manual_resume_resets_retry_attempts_but_an_auto_resume_does_not(
    db_path: Path,
) -> None:
    _set_retry_policy(db_path, "fixed_interval", retry_interval_minutes=1, retry_max_attempts=5)
    runner = FakeRunner(text="done")
    runner.rate_limit_next(times=2)
    queue = ClaudeJobQueue(db_path, runner)
    job_id = submit(db_path, queue, "manual-reset", ["one"])

    queue.process_next()  # attempt 1
    _force_resume_at_the_past(db_path, job_id)
    # Auto-resumed, hits the limit again: attempt 2, not reset by the auto-resume itself.
    queue.process_next()

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None and job.retry_attempts == 2

        assert queue.resume(conn, job_id) is True
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.retry_attempts == 0  # the manual Resume broke the streak


def test_reset_time_is_still_the_default_policy(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        settings = get_settings(conn)
    finally:
        conn.close()
    assert settings.retry_policy == "reset_time"


def test_a_rejected_answer_is_still_kept_with_the_prompt(db_path: Path, runner: FakeRunner) -> None:
    from llmjobtracker.claude_job_queue import PromptRejected
    from llmjobtracker.claude_jobs import prompt_exchange

    runner.text = "a wrong answer"

    def reject(_conn: sqlite3.Connection, _prompt: object, _result: RunResult) -> None:
        raise PromptRejected("history item: id must look like H-.")

    queue = ClaudeJobQueue(db_path, runner, on_result=reject)
    job_id = submit(db_path, queue, "rejected", ["the sent text"])
    queue.process_next()

    conn = connect(db_path)
    try:
        exchange = prompt_exchange(conn, job_id, 0)
    finally:
        conn.close()
    assert exchange is not None
    assert exchange.prompt_text == "the sent text"
    assert exchange.result_text == "a wrong answer"
    assert exchange.error == "history item: id must look like H-."


def test_runner_overrides_routes_one_prompt_kind_to_its_own_runner(db_path: Path) -> None:
    """D-191: a prompt kind registered in `runner_overrides` runs against its own Runner, every
    other kind keeps using the default one, unchanged."""

    class RecordingRunner:
        def __init__(self, name: str) -> None:
            self.name = name
            self.prompts: list[str] = []

        def run(
            self,
            prompt: str,
            cancel: threading.Event | None = None,
            json_schema: dict[str, Any] | None = None,
            on_text: Any = None,
        ) -> RunResult:
            self.prompts.append(prompt)
            return RunResult(ok=True, text=f"{self.name}: {prompt}")

    default_runner = RecordingRunner("default")
    override_runner = RecordingRunner("override")
    queue = ClaudeJobQueue(db_path, default_runner, runner_overrides={"special": override_runner})
    conn = connect(db_path)
    try:
        job_id = queue.submit(
            conn,
            "mixed kinds",
            "profile",
            [("ordinary", "goes to default"), ("special", "goes to override")],
        )
    finally:
        conn.close()

    while queue.process_next():
        pass

    assert default_runner.prompts == ["goes to default"]
    assert override_runner.prompts == ["goes to override"]
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "done"
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT result_text FROM claude_job_prompts WHERE claude_job_id = ? ORDER BY position",
            (job_id,),
        ).fetchall()
    finally:
        conn.close()
    assert [row["result_text"] for row in rows] == [
        "default: goes to default",
        "override: goes to override",
    ]
