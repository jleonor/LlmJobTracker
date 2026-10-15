import webbrowser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import llmjobtracker.app as app_module
from llmjobtracker.app import create_app
from llmjobtracker.export_llm_bundle import LlmAppStatus
from llmjobtracker.runner import FakeRunner

_BOTH_INSTALLED = {
    "claude_code": LlmAppStatus(installed=True, detail="Installed."),
    "codex": LlmAppStatus(installed=True, detail="Installed."),
}


def _assume_both_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "llm_app_status", lambda: _BOTH_INSTALLED)


def test_open_llm_app_exports_and_launches_claude_by_default(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assume_both_installed(monkeypatch)
    export_target = db_path.parent / "export-target"
    client.put("/settings", json={"user_name": "YourName", "llm_export_path": str(export_target)})
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)

    response = client.post("/llm-app/open")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "claude_code"
    bundle_path = Path(body["bundle_path"])
    assert bundle_path == export_target
    assert (bundle_path / "seed.md").exists()
    assert (bundle_path / "tracker.db").exists()
    assert len(opened) == 1
    assert opened[0].startswith("claude://code/new?q=")
    assert "folder=" in opened[0]


def test_open_llm_app_launches_codex_when_selected(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assume_both_installed(monkeypatch)
    export_target = db_path.parent / "export-target"
    client.put(
        "/settings",
        json={
            "user_name": "YourName",
            "backend": "codex",
            "llm_export_path": str(export_target),
        },
    )
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)

    response = client.post("/llm-app/open")

    assert response.status_code == 200
    assert response.json()["backend"] == "codex"
    assert opened[0].startswith("codex://new?prompt=")
    assert "path=" in opened[0]


def test_open_llm_app_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.post("/llm-app/open").status_code == 401


def test_open_llm_app_is_rejected_when_the_selected_backends_app_is_not_installed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module,
        "llm_app_status",
        lambda: {
            "claude_code": LlmAppStatus(installed=False, detail="Not installed."),
            "codex": LlmAppStatus(installed=True, detail="Installed."),
        },
    )
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)

    response = client.post("/llm-app/open")

    assert response.status_code == 400
    assert opened == []


def test_llm_app_status_route_reports_both_backends(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module,
        "llm_app_status",
        lambda: {
            "claude_code": LlmAppStatus(installed=True, detail="Installed."),
            "codex": LlmAppStatus(installed=False, detail="Not installed."),
        },
    )

    response = client.get("/llm-app/status")

    assert response.status_code == 200
    body = response.json()
    assert body["claude_code"] == {"installed": True, "detail": "Installed."}
    assert body["codex"] == {"installed": False, "detail": "Not installed."}


def test_llm_app_status_route_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.get("/llm-app/status").status_code == 401
