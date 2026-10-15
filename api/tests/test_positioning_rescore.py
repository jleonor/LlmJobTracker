"""Tests for POST /positioning/rescore-all (D-218): the Settings "Re-score all positioning
analyses" action - clears and requeues Positioning analysis for every application that meets
positioning_ready, skipping (and counting) the rest.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.job_applications import (
    insert_job_application,
    set_master_cv,
    update_job_application,
)
from llmjobtracker.job_files import insert_job_file
from llmjobtracker.profile_pipeline import store_output
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"


def add_profile_documents(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        for kind in ("full_cv_history", "questionnaire_analysis", "strategy"):
            store_output(conn, kind, f"# {kind}", None, [], source="generated")
        conn.commit()
    finally:
        conn.close()


def make_positioning_ready(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            extraction_status="ok",
            extracted_text="Senior Data Analyst, must know SQL.",
        )
        update_job_application(
            conn, app_id, {"description": "Role summary.", "requirements": ["Strong SQL"]}
        )
        file_id = conn.execute(
            "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
            "VALUES ('master_cv', 'cv.pdf', 'profile/cv.pdf', 'abc', 10)"
        ).lastrowid
        set_master_cv(conn, app_id, file_id)
        # A pre-existing positioning result, to prove the rescore clears it before requeuing.
        update_job_application(conn, app_id, {"fit": ["Old fit"], "gaps": ["Old gap"]})
        conn.execute("UPDATE job_applications SET match_score = 42.0 WHERE id = ?", (app_id,))
        conn.commit()
    finally:
        conn.close()
    add_profile_documents(db_path)
    return app_id


def test_rescore_all_route_skips_an_application_with_nothing_set_up(
    client: TestClient, db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        insert_job_application(conn, {"company": "Bare Co", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()

    response = client.post("/positioning/rescore-all")
    assert response.status_code == 200
    assert response.json() == {"queued": 0, "skipped": 1}


def test_rescore_all_route_clears_and_requeues_a_ready_application(db_path: Path) -> None:
    app_id = make_positioning_ready(db_path)

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post("/positioning/rescore-all")
        assert response.status_code == 200
        assert response.json() == {"queued": 1, "skipped": 0}

        detail = client.get(f"/job-applications/{app_id}").json()
        assert detail["match_score"] is None
        assert detail["fit"] == []
        assert detail["gaps"] == []

        jobs = client.get("/claude-jobs").json()
        positioning_jobs = [job for job in jobs if job["kind"] == "generate_positioning"]
        assert len(positioning_jobs) == 1
        assert positioning_jobs[0]["job_application_id"] == app_id


def test_rescore_all_route_counts_ready_and_not_ready_applications_together(
    db_path: Path,
) -> None:
    make_positioning_ready(db_path)
    conn = connect(db_path)
    try:
        insert_job_application(conn, {"company": "Bare Co", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post("/positioning/rescore-all")
        assert response.status_code == 200
        assert response.json() == {"queued": 1, "skipped": 1}
