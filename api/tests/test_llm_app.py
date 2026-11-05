import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

import llmjobtracker.app as app_module
from llmjobtracker.app import create_app
from llmjobtracker.export_llm_bundle import LlmAppStatus
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.open_application_pipeline import create_open_application
from llmjobtracker.open_application_research import ResearchItemInput
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

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


def test_export_data_builds_the_bundle_without_opening_anything(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_target = db_path.parent / "export-target"
    client.put("/settings", json={"user_name": "YourName", "llm_export_path": str(export_target)})
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)

    response = client.post("/data/export")

    assert response.status_code == 200
    bundle_path = Path(response.json()["bundle_path"])
    assert bundle_path == export_target
    assert (bundle_path / "seed.md").exists()
    assert (bundle_path / "tracker.db").exists()
    assert opened == []


def test_export_data_works_regardless_of_whether_any_llm_app_is_installed(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_target = db_path.parent / "export-target"
    client.put("/settings", json={"user_name": "YourName", "llm_export_path": str(export_target)})
    monkeypatch.setattr(
        app_module,
        "llm_app_status",
        lambda: {
            "claude_code": LlmAppStatus(installed=False, detail="Not installed."),
            "codex": LlmAppStatus(installed=False, detail="Not installed."),
        },
    )

    response = client.post("/data/export")

    assert response.status_code == 200


def test_export_data_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.post("/data/export").status_code == 401


# --- D-293/D-294: the live folder, and the per-application prompt ------------------------------


def _deep_link_params(url: str) -> dict[str, str]:
    query = parse_qs(urlparse(url).query)
    return {key: unquote(values[0]) for key, values in query.items()}


def test_open_llm_app_points_the_deep_link_at_the_live_folder_not_the_export(
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
    assert body["bundle_path"] == str(export_target)  # the backup still goes there
    assert body["opened_path"] == str(db_path.parent)  # but this is what's opened
    params = _deep_link_params(opened[0])
    assert params["folder"] == str(db_path.parent)
    assert (db_path.parent / "seed.md").exists()
    assert "live data folder" in (db_path.parent / "seed.md").read_text(encoding="utf-8")
    assert "close LlmJobTracker" in params["q"]


def test_open_llm_app_for_a_job_application_names_its_url_and_asks_to_browse(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assume_both_installed(monkeypatch)
    # An isolated export target (same as every other test here) - without one, export_llm_bundle
    # defaults to the real ~/Downloads/LlmJobTrackerExport on whatever machine runs this suite.
    client.put(
        "/settings",
        json={"user_name": "YourName", "llm_export_path": str(db_path.parent / "export-target")},
    )
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    conn = connect(db_path)
    try:
        application_id = insert_job_application(
            conn,
            {
                "company": "Acme Inc",
                "role_title": "Senior Data Analyst",
                "portal_url": "https://example.com/jobs/123",
            },
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/llm-app/open", json={"job_application_id": application_id})

    assert response.status_code == 200
    params = _deep_link_params(opened[0])
    assert "Acme Inc - Senior Data Analyst" in params["q"]
    assert "https://example.com/jobs/123" in params["q"]
    assert "browser tool" in params["q"]


def test_open_llm_app_for_an_open_application_lists_its_research_urls(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assume_both_installed(monkeypatch)
    client.put(
        "/settings",
        json={"user_name": "YourName", "llm_export_path": str(db_path.parent / "export-target")},
    )
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    conn = connect(db_path)
    try:
        application_id = create_open_application(
            conn,
            {"company_name": "Acme Talent Pool"},
            [
                ResearchItemInput(source_type="url", content="https://acme.example/careers"),
                ResearchItemInput(source_type="text", content="Pasted notes, not a URL."),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/llm-app/open", json={"open_application_id": application_id})

    assert response.status_code == 200
    params = _deep_link_params(opened[0])
    assert "Acme Talent Pool" in params["q"]
    assert "https://acme.example/careers" in params["q"]


def test_open_llm_app_rejects_both_ids_given(client: TestClient) -> None:
    response = client.post(
        "/llm-app/open", json={"job_application_id": 1, "open_application_id": 1}
    )
    assert response.status_code == 400


def test_open_llm_app_404s_for_an_unknown_job_application_id(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assume_both_installed(monkeypatch)
    client.put(
        "/settings",
        json={"user_name": "YourName", "llm_export_path": str(db_path.parent / "export-target")},
    )
    monkeypatch.setattr(webbrowser, "open", lambda url: None)
    response = client.post("/llm-app/open", json={"job_application_id": 999})
    assert response.status_code == 404
