import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from localjobtracker.claude_jobs import get_claude_job, job_status
from localjobtracker.runner import FakeRunner, Runner, RunResult
from localjobtracker.storage import connect

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
