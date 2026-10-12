"""Tests for the Listing's extraction routes (step 25, job-llm-steps.md): a URL, pasted text, or
an uploaded file, turned into reviewable text by code - nothing saved, no Claude involved.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.job_applications import insert_job_application
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"
LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def add_application(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    return app_id


# --- URL ------------------------------------------------------------------------------------


@respx.mock
def test_extract_from_url_returns_the_readable_text(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    html = (LISTING_FIXTURES / "listing.html").read_text(encoding="utf-8")
    respx.get("https://example.com/job/123").mock(
        return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )

    response = client.post(
        f"/job-applications/{app_id}/listing/extract-url",
        json={"url": "https://example.com/job/123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "url"
    assert body["status"] == "ok"
    assert "Senior Data Analyst" in body["text"]
    assert "Accept all" not in body["text"]


@respx.mock
def test_extract_from_url_reports_a_blocked_page(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    respx.get("https://example.com/blocked").mock(return_value=httpx.Response(403))

    response = client.post(
        f"/job-applications/{app_id}/listing/extract-url",
        json={"url": "https://example.com/blocked"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "403" in (body["message"] or "")


@respx.mock
def test_extract_from_url_reports_a_page_with_no_readable_content(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    junk = (LISTING_FIXTURES / "junk_only.html").read_text(encoding="utf-8")
    respx.get("https://example.com/junk").mock(
        return_value=httpx.Response(200, text=junk, headers={"content-type": "text/html"})
    )

    response = client.post(
        f"/job-applications/{app_id}/listing/extract-url",
        json={"url": "https://example.com/junk"},
    )

    assert response.json()["status"] == "no_text"


@respx.mock
def test_extract_from_url_reports_an_unreachable_host(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    respx.get("https://example.com/down").mock(side_effect=httpx.ConnectError("no route"))

    response = client.post(
        f"/job-applications/{app_id}/listing/extract-url",
        json={"url": "https://example.com/down"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_extract_from_url_rejects_an_empty_url(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(f"/job-applications/{app_id}/listing/extract-url", json={"url": "   "})
    assert response.status_code == 400


def test_extract_from_url_for_an_unknown_application_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/job-applications/999/listing/extract-url", json={"url": "https://example.com"}
    )
    assert response.status_code == 404


# --- Paste ------------------------------------------------------------------------------------


def test_extract_from_paste_cleans_and_returns_the_text(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-paste",
        json={"text": "Senior Data Analyst\r\n\r\nRequirements: SQL.  "},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "paste"
    assert body["status"] == "ok"
    assert body["text"] == "Senior Data Analyst\n\nRequirements: SQL."


def test_extract_from_paste_rejects_empty_text(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-paste", json={"text": "   "}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_text"


# --- Upload -----------------------------------------------------------------------------------


def test_extract_from_upload_reads_an_html_file(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-upload",
        headers={"X-File-Name": "listing.html"},
        content=(LISTING_FIXTURES / "listing.html").read_bytes(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "upload"
    assert body["source"] == "listing.html"
    assert body["status"] == "ok"
    assert "Senior Data Analyst" in body["text"]


def test_extract_from_upload_reads_a_pdf_file(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-upload",
        headers={"X-File-Name": "listing.pdf"},
        content=(LISTING_FIXTURES / "listing.pdf").read_bytes(),
    )
    assert response.status_code == 200
    assert "Senior Data Analyst" in response.json()["text"]


def test_extract_from_upload_rejects_an_unsupported_extension(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-upload",
        headers={"X-File-Name": "listing.png"},
        content=b"\x89PNG",
    )
    assert response.status_code == 415


def test_extract_from_upload_rejects_an_empty_file(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/extract-upload",
        headers={"X-File-Name": "listing.txt"},
        content=b"",
    )
    assert response.status_code == 400


def test_extract_from_upload_does_not_save_anything(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    client.post(
        f"/job-applications/{app_id}/listing/extract-upload",
        headers={"X-File-Name": "listing.txt"},
        content=b"Senior Data Analyst",
    )
    detail = client.get(f"/job-applications/{app_id}").json()
    assert detail["files"] == []


# --- Check and Generate routes (steps 26-27) --------------------------------------------------


def test_check_route_queues_and_runs_the_sanity_check(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    created = client.post(
        f"/job-applications/{app_id}/listing/check", json={"text": "Senior Data Analyst..."}
    )
    assert created.status_code == 201
    job = created.json()
    assert job["kind"] == "check_job_listing_text"
    assert job["job_application_id"] == app_id
    assert job["status"] == "queued"

    client.app.state.queue.process_next()  # type: ignore[attr-defined]
    done = client.get("/claude-jobs").json()[0]
    assert done["id"] == job["id"]
    assert done["status"] == "done"


def test_check_route_rejects_empty_text(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(f"/job-applications/{app_id}/listing/check", json={"text": "  "})
    assert response.status_code == 400


def test_check_route_for_an_unknown_application_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/job-applications/999/listing/check", json={"text": "Senior Data Analyst"}
    )
    assert response.status_code == 404


def test_generate_route_queues_and_stores_the_listing_file(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    created = client.post(
        f"/job-applications/{app_id}/listing/generate",
        json={"method": "paste", "text": "Senior Data Analyst..."},
    )
    assert created.status_code == 201
    job = created.json()
    assert job["kind"] == "generate_job_listing"

    client.app.state.queue.process_next()  # type: ignore[attr-defined]
    detail = client.get(f"/job-applications/{app_id}").json()
    assert len(detail["files"]) == 1
    assert detail["files"][0]["kind"] == "listing"
    assert detail["files"][0]["name"] == "Analyst - Listing.md"


def test_generate_route_rejects_an_unknown_method(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/listing/generate",
        json={"method": "telepathy", "text": "Senior Data Analyst..."},
    )
    assert response.status_code == 400
