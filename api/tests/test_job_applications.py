import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker import seed
from localjobtracker.app import create_app
from localjobtracker.job_applications import count_job_applications, insert_job_application
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

FIXTURE = seed.DEFAULT_FIXTURE
FIXTURE_ROWS = json.loads(FIXTURE.read_text(encoding="utf-8"))


def seed_database(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["seed", "--db", str(db_path)])
    seed.main()


def test_list_is_empty_on_a_new_database(client: TestClient) -> None:
    response = client.get("/job-applications")
    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_the_d46_fields(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    seed_database(monkeypatch, db_path)
    rows = client.get("/job-applications").json()

    assert len(rows) == len(FIXTURE_ROWS)
    expected_keys = {
        "id",
        "company",
        "role_title",
        "lane",
        "location",
        "status",
        "last_updated",
        "match_score",
    }
    assert all(set(row) == expected_keys for row in rows)
    # The table no longer returns next action or due date (D-46).
    assert all("next_action" not in row and "due_date" not in row for row in rows)


def test_last_updated_is_the_newest_history_row(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    seed_database(monkeypatch, db_path)
    rows = client.get("/job-applications").json()
    tailspin = next(r for r in rows if r["company"] == "Tailspin Energy")
    assert tailspin["status"] == "Applied"
    assert tailspin["last_updated"] == "2026-10-01T09:00:00Z"
    fabrikam = next(r for r in rows if r["company"] == "Fabrikam Logistics")
    assert fabrikam["status"] == "Interview"
    assert fabrikam["last_updated"] == "2026-10-03T16:00:00Z"


def test_list_is_ordered_by_last_updated_newest_first(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    seed_database(monkeypatch, db_path)
    dates = [r["last_updated"] for r in client.get("/job-applications").json()]
    assert dates == sorted(dates, reverse=True)


def test_match_score_can_be_empty(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    seed_database(monkeypatch, db_path)
    rows = client.get("/job-applications").json()
    assert any(r["match_score"] is None for r in rows)
    assert any(isinstance(r["match_score"], float) for r in rows)


def test_seed_twice_adds_no_duplicates(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_database(monkeypatch, db_path)
    seed_database(monkeypatch, db_path)

    conn = connect(db_path)
    try:
        assert count_job_applications(conn) == len(FIXTURE_ROWS)
    finally:
        conn.close()
    assert "skipped" in capsys.readouterr().out


def test_insert_without_history_starts_as_not_started(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        from localjobtracker.migrations import migrate

        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        status = conn.execute(
            "SELECT status FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        history = conn.execute(
            "SELECT status FROM status_history WHERE job_application_id = ?", (app_id,)
        ).fetchall()
    finally:
        conn.close()
    assert status[0] == "Not Started"
    assert [h[0] for h in history] == ["Not Started"]


def test_insert_rejects_an_unknown_status(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        from localjobtracker.migrations import migrate

        migrate(conn)
        with pytest.raises(sqlite3.IntegrityError):
            insert_job_application(
                conn,
                {"company": "Bad Co", "role_title": "Analyst"},
                history=[("Hired", "2026-10-06T09:00:00Z")],
            )
    finally:
        conn.close()


def test_list_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.get("/job-applications").status_code == 401
