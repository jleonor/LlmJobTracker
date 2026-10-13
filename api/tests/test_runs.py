from pathlib import Path

from fastapi.testclient import TestClient

from llmjobtracker.app import CHECK_PROMPT, create_app
from llmjobtracker.runner import FakeRunner


def test_check_returns_runner_text(client: TestClient, runner: FakeRunner) -> None:
    response = client.post("/runs/check")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["text"] == "OK"
    assert runner.prompts == [CHECK_PROMPT]


def test_check_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.post("/runs/check").status_code == 401
