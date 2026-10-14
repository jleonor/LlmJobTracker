"""D-195: one global backend switch for the whole app."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue, RenderedPrompt
from llmjobtracker.claude_jobs import PromptRow
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"


def queue_of(client: TestClient) -> ClaudeJobQueue:
    app = client.app
    assert isinstance(app, FastAPI)
    queue: ClaudeJobQueue = app.state.queue
    return queue


@pytest.fixture
def claude_runner() -> FakeRunner:
    return FakeRunner(text="claude answer")


@pytest.fixture
def codex_runner() -> FakeRunner:
    return FakeRunner(text="codex answer")


@pytest.fixture
def two_backend_client(
    db_path: Path, claude_runner: FakeRunner, codex_runner: FakeRunner
) -> Iterator[TestClient]:
    app = create_app(TOKEN, db_path, claude_runner, codex_runner=codex_runner)
    with TestClient(app) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def test_a_new_job_starts_on_claude_code_by_default(
    db_path: Path, claude_runner: FakeRunner, two_backend_client: TestClient
) -> None:
    queue = queue_of(two_backend_client)
    conn = connect(db_path)
    queue.submit(conn, "first", "profile", [("step", "hi")])
    conn.close()

    queue.process_next()

    assert claude_runner.prompts == ["hi"]


def test_switching_the_backend_moves_the_next_job_to_codex(
    db_path: Path,
    claude_runner: FakeRunner,
    codex_runner: FakeRunner,
    two_backend_client: TestClient,
) -> None:
    queue = queue_of(two_backend_client)

    saved = two_backend_client.put("/settings", json={"user_name": "YourName", "backend": "codex"})
    assert saved.status_code == 200
    assert saved.json()["backend"] == "codex"

    conn = connect(db_path)
    queue.submit(conn, "first", "profile", [("step", "hi")])
    conn.close()
    queue.process_next()

    assert codex_runner.prompts == ["hi"]
    assert claude_runner.prompts == []


def test_switching_to_an_unregistered_backend_keeps_the_app_running(
    db_path: Path, claude_runner: FakeRunner, two_backend_client: TestClient
) -> None:
    # create_app's single-runner fixtures elsewhere never register "codex" - saving that
    # backend still works (it's just a stored preference), and the queue quietly keeps using
    # its one known runner rather than crashing.
    app = create_app(TOKEN, db_path, claude_runner)  # no codex_runner this time
    with TestClient(app) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        saved = client.put("/settings", json={"user_name": "YourName", "backend": "codex"})
        assert saved.status_code == 200
        assert saved.json()["backend"] == "codex"

        queue: ClaudeJobQueue = app.state.queue
        conn = connect(db_path)
        queue.submit(conn, "first", "profile", [("step", "hi")])
        conn.close()
        queue.process_next()

        assert claude_runner.prompts == ["hi"]  # fell back, not crashed


def test_a_running_job_keeps_the_runner_it_started_with(db_path: Path) -> None:
    claude = FakeRunner(text="claude answer")
    codex = FakeRunner(text="codex answer")

    def render(_conn: object, prompt: PromptRow) -> RenderedPrompt:
        if prompt.position == 1:
            # Simulate a Settings change landing mid-job (D-195's own guarantee): the job
            # already dispatching must finish on the runner it started with.
            queue.set_runner(codex)
        return RenderedPrompt(text=prompt.prompt_text)

    queue = ClaudeJobQueue(db_path, claude, render=render)
    conn = connect(db_path)
    queue.submit(conn, "first", "profile", [("step", "one"), ("step", "two")])
    conn.close()

    queue.process_next()

    assert claude.prompts == ["one", "two"]  # both prompts, despite the mid-job switch
    assert codex.prompts == []
