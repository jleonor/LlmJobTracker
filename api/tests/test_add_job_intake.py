"""Tests for Add Job's intake routes (step 3, Agent/specs/intake-steps.md): the same extraction
and sanity check as the existing-application Listing routes (test_listing_intake.py), run with no
application yet.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.runner import FakeRunner

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
