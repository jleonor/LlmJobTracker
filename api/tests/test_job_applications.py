import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker import seed
from localjobtracker.app import create_app
from localjobtracker.job_applications import count_job_applications, insert_job_application
from localjobtracker.job_files import insert_job_file
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


def test_insert_without_history_starts_as_identified(db_path: Path) -> None:
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
    assert status[0] == "Identified"
    assert [h[0] for h in history] == ["Identified"]


def test_insert_stores_description_requirements_and_notes(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        from localjobtracker.migrations import migrate

        migrate(conn)
        app_id = insert_job_application(
            conn,
            {
                "company": "Solo Co",
                "role_title": "Analyst",
                "description": "What the role is.",
                "requirements": ["Python", "SQL"],
                "notes": "Keep an eye on the deadline.",
            },
        )
        row = conn.execute(
            "SELECT description, requirements, notes FROM job_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["description"] == "What the role is."
    assert json.loads(row["requirements"]) == ["Python", "SQL"]
    assert row["notes"] == "Keep an eye on the deadline."


def test_insert_defaults_requirements_to_an_empty_list(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        from localjobtracker.migrations import migrate

        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        row = conn.execute(
            "SELECT description, requirements, notes FROM job_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["description"] is None
    assert json.loads(row["requirements"]) == []
    assert row["notes"] is None


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


def test_detail_returns_404_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/job-applications/999")
    assert response.status_code == 404


def test_detail_includes_description_requirements_notes_and_history(
    db_path: Path, client: TestClient
) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(
            conn,
            {
                "company": "Solo Co",
                "role_title": "Analyst",
                "description": "What the role is.",
                "requirements": ["Python", "SQL"],
                "notes": "Keep an eye on the deadline.",
            },
            history=[
                ("Identified", "2026-09-28T09:00:00Z"),
                ("Applied", "2026-10-01T10:30:00Z"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    detail = client.get(f"/job-applications/{app_id}").json()
    assert detail["description"] == "What the role is."
    assert detail["requirements"] == ["Python", "SQL"]
    assert detail["notes"] == "Keep an eye on the deadline."
    assert detail["status"] == "Applied"
    assert detail["status_history"] == [
        {"status": "Identified", "changed_at": "2026-09-28T09:00:00Z"},
        {"status": "Applied", "changed_at": "2026-10-01T10:30:00Z"},
    ]
    assert detail["files"] == []


def test_detail_includes_job_files(db_path: Path, client: TestClient) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        insert_job_file(conn, app_id, kind="listing", name="Job Listing.pdf", stored_path="x/x.pdf")
        insert_job_file(
            conn,
            app_id,
            kind="eml",
            name="Confirmation.eml",
            stored_path="x/x.eml",
            date="2026-10-01T12:03:00Z",
        )
        conn.commit()
    finally:
        conn.close()

    detail = client.get(f"/job-applications/{app_id}").json()
    assert [{k: v for k, v in f.items() if k != "id"} for f in detail["files"]] == [
        {
            "kind": "listing",
            "name": "Job Listing.pdf",
            "date": None,
            "extraction_status": None,
            "extraction_message": None,
        },
        {
            "kind": "eml",
            "name": "Confirmation.eml",
            "date": "2026-10-01T12:03:00Z",
            "extraction_status": None,
            "extraction_message": None,
        },
    ]
    assert [f["id"] for f in detail["files"]] == sorted(f["id"] for f in detail["files"])


def test_detail_without_token_is_rejected(db_path: Path, token: str) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.get(f"/job-applications/{app_id}").status_code == 401


# --- Delete -------------------------------------------------------------------------------------


def test_delete_removes_the_row_and_its_managed_folder(db_path: Path, client: TestClient) -> None:
    files_root = db_path.parent / "files"
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        folder = files_root / "Solo Co" / "Analyst"
        folder.mkdir(parents=True)
        (folder / "Job Listing.md").write_text("Some listing text.", encoding="utf-8")
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Solo Co/Analyst/Job Listing.md",
        )
        conn.execute(
            "INSERT INTO claude_jobs (label, kind, job_application_id, status, created_at, "
            "updated_at) VALUES ('Generate: Listing', 'generate_job_listing', ?, 'done', "
            "'2026-10-11T00:00:00Z', '2026-10-11T00:00:00Z')",
            (app_id,),
        )
        conn.commit()
        assert folder.exists()
    finally:
        conn.close()

    response = client.delete(f"/job-applications/{app_id}")
    assert response.status_code == 204
    assert not folder.exists()

    conn = connect(db_path)
    try:
        assert (
            conn.execute("SELECT 1 FROM job_applications WHERE id = ?", (app_id,)).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT 1 FROM job_files WHERE job_application_id = ?", (app_id,)
            ).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT 1 FROM claude_jobs WHERE job_application_id = ?", (app_id,)
            ).fetchone()
            is None
        )
    finally:
        conn.close()

    assert client.get(f"/job-applications/{app_id}").status_code == 404


def test_delete_of_an_unknown_id_is_not_found(client: TestClient) -> None:
    assert client.delete("/job-applications/999").status_code == 404


def test_delete_without_token_is_rejected(db_path: Path, token: str) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Solo Co", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.delete(f"/job-applications/{app_id}").status_code == 401
