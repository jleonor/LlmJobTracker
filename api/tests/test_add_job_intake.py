"""Tests for Add Job's intake routes (steps 3-5, Agent/specs/intake-steps.md): the same
extraction and sanity check as the existing-application Listing routes (test_listing_intake.py),
run with no application yet, plus the duplicate-check and identity-extraction endpoints.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file, listing_text_sha256
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"
LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


# --- URL ----------------------------------------------------------------------------------------


@respx.mock
def test_intake_extract_from_url_returns_the_readable_text(client: TestClient) -> None:
    html = (LISTING_FIXTURES / "listing.html").read_text(encoding="utf-8")
    respx.get("https://example.com/job/123").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )

    response = client.post(
        "/job-applications/intake/extract-url", json={"url": "https://example.com/job/123"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "url"
    assert body["status"] == "ok"
    assert "Senior Data Analyst" in body["text"]


def test_intake_extract_from_url_rejects_an_empty_url(client: TestClient) -> None:
    response = client.post("/job-applications/intake/extract-url", json={"url": "   "})
    assert response.status_code == 400


# --- Paste ----------------------------------------------------------------------------------


def test_intake_extract_from_paste_cleans_and_returns_the_text(client: TestClient) -> None:
    response = client.post(
        "/job-applications/intake/extract-paste",
        json={"text": "  Senior Data Analyst, must know SQL.  "},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "paste"
    assert body["status"] == "ok"
    assert body["text"] == "Senior Data Analyst, must know SQL."


# --- Upload -----------------------------------------------------------------------------------


def test_intake_extract_from_upload_reads_a_pdf_file(client: TestClient) -> None:
    response = client.post(
        "/job-applications/intake/extract-upload",
        headers={"X-File-Name": "listing.pdf"},
        content=(LISTING_FIXTURES / "listing.pdf").read_bytes(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "upload"
    assert "Senior Data Analyst" in body["text"]


def test_intake_extract_from_upload_rejects_an_unsupported_extension(client: TestClient) -> None:
    response = client.post(
        "/job-applications/intake/extract-upload",
        headers={"X-File-Name": "listing.png"},
        content=b"\x89PNG",
    )
    assert response.status_code == 415


# --- Check --------------------------------------------------------------------------------------


def test_intake_check_queues_and_runs_with_no_application_yet(client: TestClient) -> None:
    created = client.post("/job-applications/intake/check", json={"text": "Senior Data Analyst..."})
    assert created.status_code == 201
    job = created.json()
    assert job["kind"] == "check_job_listing_text"
    assert job["job_application_id"] is None
    assert job["status"] == "queued"

    client.app.state.queue.process_next()  # type: ignore[attr-defined]
    done = client.get("/claude-jobs").json()[0]
    assert done["id"] == job["id"]
    assert done["status"] == "done"


def test_intake_check_rejects_empty_text(client: TestClient) -> None:
    response = client.post("/job-applications/intake/check", json={"text": "  "})
    assert response.status_code == 400


# --- Duplicate check (step 4) -------------------------------------------------------------------


def test_duplicate_check_finds_no_match_against_an_empty_tracker(client: TestClient) -> None:
    response = client.post(
        "/job-applications/intake/duplicate-check", json={"text": "Senior Data Analyst..."}
    )
    assert response.status_code == 200
    assert response.json() is None


def test_duplicate_check_matches_by_content(client: TestClient, db_path: Path) -> None:
    text = "Senior Data Analyst at Acme Inc. Must know SQL."
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            sha256=listing_text_sha256(text),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post("/job-applications/intake/duplicate-check", json={"text": text})
    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["application_id"] == app_id
    assert body["matched_by"] == "content"


def test_duplicate_check_matches_by_source_url(client: TestClient, db_path: Path) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            sha256="unrelated-hash",
            source_url="https://example.com/jobs/123",
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/job-applications/intake/duplicate-check",
        json={
            "text": "A different rewording of the same posting.",
            "source_url": "https://example.com/jobs/123",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["application_id"] == app_id
    assert body["matched_by"] == "url"


# --- Identity (step 5) ----------------------------------------------------------------------

GOOD_IDENTITY_ANSWER = (
    "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
    "=== ROLE TITLE ===\nSenior Data Analyst\n=== END ROLE TITLE ===\n\n"
    "=== LANE ===\nUnknown\n=== END LANE ===\n\n"
    "=== LOCATION ===\nGeneva\n=== END LOCATION ===\n\n"
    "=== PORTAL NAME ===\nUnknown\n=== END PORTAL NAME ===\n\n"
    "=== PORTAL URL ===\n\n=== END PORTAL URL ==="
)


@pytest.fixture
def identity_client(db_path: Path) -> Iterator[TestClient]:
    runner = FakeRunner(text=GOOD_IDENTITY_ANSWER)
    with TestClient(create_app(TOKEN, db_path, runner)) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def test_identity_route_queues_and_the_result_is_readable(identity_client: TestClient) -> None:
    created = identity_client.post(
        "/job-applications/intake/identity", json={"text": "Senior Data Analyst at Acme Inc."}
    )
    assert created.status_code == 201
    job = created.json()
    assert job["kind"] == "extract_job_identity"
    assert job["job_application_id"] is None

    identity_client.app.state.queue.process_next()  # type: ignore[attr-defined]

    result = identity_client.get(f"/job-applications/intake/identity/{job['id']}")
    assert result.status_code == 200
    body = result.json()
    assert body["company"] == "Acme Inc"
    assert body["role_title"] == "Senior Data Analyst"
    assert body["lane"] is None
    assert body["location"] == "Geneva"


def test_identity_route_rejects_empty_text(identity_client: TestClient) -> None:
    response = identity_client.post("/job-applications/intake/identity", json={"text": "  "})
    assert response.status_code == 400


def test_identity_result_for_an_unknown_job_is_not_found(identity_client: TestClient) -> None:
    response = identity_client.get("/job-applications/intake/identity/999")
    assert response.status_code == 404


def test_identity_result_surfaces_a_rejected_answer(db_path: Path) -> None:
    bad_answer = (
        "=== COMPANY ===\nUnknown\n=== END COMPANY ===\n\n"
        "=== ROLE TITLE ===\nUnknown\n=== END ROLE TITLE ==="
    )
    with TestClient(create_app(TOKEN, db_path, FakeRunner(text=bad_answer))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        created = client.post(
            "/job-applications/intake/identity", json={"text": "A vague page with no company."}
        )
        client.app.state.queue.process_next()  # type: ignore[attr-defined]
        response = client.get(f"/job-applications/intake/identity/{created.json()['id']}")
    assert response.status_code == 400
