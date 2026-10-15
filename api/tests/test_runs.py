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


def test_check_uses_whichever_backend_is_currently_selected(db_path: Path, token: str) -> None:
    claude_code = FakeRunner(text="OK from Claude Code")
    codex = FakeRunner(text="OK from Codex")
    with TestClient(create_app(token, db_path, claude_code, codex_runner=codex)) as app_client:
        app_client.headers["X-Launch-Token"] = token
        app_client.put("/settings", json={"user_name": "YourName", "backend": "codex"})

        response = app_client.post("/runs/check")

        assert response.status_code == 200
        assert response.json()["text"] == "OK from Codex"
        assert codex.prompts == [CHECK_PROMPT]
        assert claude_code.prompts == []


def test_check_is_rejected_when_codex_is_selected_but_not_installed(
    client: TestClient,
) -> None:
    client.put("/settings", json={"user_name": "YourName", "backend": "codex"})

    response = client.post("/runs/check")

    assert response.status_code == 400
