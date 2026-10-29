"""Tests for POST /job-applications (step 6, Agent/specs/intake-steps.md): creating a new row
from Add Job's confirmed fields and queuing the rest of the chosen workflow.
"""

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.job_files import listing_text_sha256
from llmjobtracker.runner import FakeRunner, RunResult
from llmjobtracker.storage import connect

TOKEN = "test-token"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def basic_request(**overrides: Any) -> dict[str, Any]:
    body = {
        "company": "Acme Inc",
        "role_title": "Senior Data Analyst",
        "lane": None,
        "location": "Geneva",
        "portal_name": "LinkedIn",
        "portal_url": "https://example.com/jobs/123",
        "listing_method": "paste",
        "listing_text": "Senior Data Analyst at Acme Inc. Must know SQL.",
        "listing_source_url": None,
        "workflow": "basic",
        "master_cv_profile_file_id": None,
    }
    body.update(overrides)
    return body


# --- Creation and validation -------------------------------------------------------------------


def test_create_basic_workflow_creates_the_row_and_queues_two_jobs(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request())
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["application_id"], int)
    assert len(body["claude_job_ids"]) == 2

    detail = client.get(f"/job-applications/{body['application_id']}").json()
    assert detail["company"] == "Acme Inc"
    assert detail["role_title"] == "Senior Data Analyst"
    assert detail["location"] == "Geneva"
    assert detail["status"] == "Identified"


def test_create_positioning_workflow_queues_three_jobs(client: TestClient) -> None:
    master_cv_id = _seed_master_cv(client)
    response = client.post(
        "/job-applications",
        json=basic_request(workflow="positioning", master_cv_profile_file_id=master_cv_id),
    )
    assert response.status_code == 201
    assert len(response.json()["claude_job_ids"]) == 3


def test_create_full_workflow_queues_five_jobs(client: TestClient) -> None:
    master_cv_id = _seed_master_cv(client)
    response = client.post(
        "/job-applications",
        json=basic_request(workflow="full", master_cv_profile_file_id=master_cv_id),
    )
    assert response.status_code == 201
    assert len(response.json()["claude_job_ids"]) == 5


def test_create_rejects_a_blank_company(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request(company="   "))
    assert response.status_code == 400


def test_create_rejects_a_blank_role_title(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request(role_title="  "))
    assert response.status_code == 400


def test_create_rejects_empty_listing_text(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request(listing_text="   "))
    assert response.status_code == 400


def test_create_rejects_an_unknown_workflow(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request(workflow="deluxe"))
    assert response.status_code == 400


def test_create_rejects_positioning_with_no_master_cv(client: TestClient) -> None:
    response = client.post("/job-applications", json=basic_request(workflow="positioning"))
    assert response.status_code == 400


def test_create_rejects_a_master_cv_id_that_is_not_a_master_cv(client: TestClient) -> None:
    response = client.post(
        "/job-applications",
        json=basic_request(workflow="positioning", master_cv_profile_file_id=999),
    )
    assert response.status_code == 404


def _seed_master_cv(client: TestClient) -> int:
    upload = client.post(
        "/profile/files/master_cv",
        headers={"X-File-Name": "Master CV.txt"},
        content=b"A master CV in plain text.",
    )
    assert upload.status_code == 201, upload.text
    return int(upload.json()["id"])


# --- Duplicate fingerprint carried forward from the very start --------------------------------


def test_the_new_rows_listing_is_a_duplicate_match_immediately(client: TestClient) -> None:
    """The placeholder listing row (inserted before any Claude Job runs) already carries the
    dedup fingerprint D-146's duplicate-check endpoint compares against - a second Add Job
    attempt with the same text is caught even before generate_job_listing has run."""
    text = "Senior Data Analyst at Acme Inc. Must know SQL."
    created = client.post("/job-applications", json=basic_request(listing_text=text))
    assert created.status_code == 201

    duplicate = client.post("/job-applications/intake/duplicate-check", json={"text": text})
    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body is not None
    assert body["application_id"] == created.json()["application_id"]
    assert body["matched_by"] == "content"


def test_a_url_sourced_listing_is_matched_by_source_url(client: TestClient) -> None:
    created = client.post(
        "/job-applications",
        json=basic_request(listing_method="url", listing_source_url="https://example.com/jobs/123"),
    )
    assert created.status_code == 201

    duplicate = client.post(
        "/job-applications/intake/duplicate-check",
        json={
            "text": "A different rewording of the same posting.",
            "source_url": "https://example.com/jobs/123",
        },
    )
    body = duplicate.json()
    assert body is not None
    assert body["matched_by"] == "url"


# --- The dedup fingerprint survives Generate replacing the placeholder -------------------------


class ScriptedRunner:
    """Returns a different canned answer per `TASK: <kind>` line - see test_add_job_chain.py."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Any = None,
    ) -> RunResult:
        for task, text in self.answers.items():
            if f"TASK: {task}" in prompt:
                return RunResult(ok=True, text=text, duration_ms=0, cost_usd=0.0, model="fake")
        raise AssertionError(f"No scripted answer for this prompt: {prompt[:200]!r}")


def test_duplicate_fingerprint_survives_generate_replacing_the_placeholder(
    db_path: Path,
) -> None:
    text = "Senior Data Analyst at Acme Inc. Must know SQL."
    details_answer = (
        "=== DESCRIPTION ===\nA data analyst role.\n=== END DESCRIPTION ===\n\n"
        "=== REQUIREMENT ===\nMust know SQL.\n=== END REQUIREMENT ==="
    )
    # generate_job_listing's own answer is deliberately *different* text from the reviewed
    # original, the way a real Claude cleanup would reword it - proving the stored sha256 still
    # reflects the *reviewed* text, not this generated rewrite.
    runner = ScriptedRunner(
        {
            "generate_job_listing": "# Senior Data Analyst\n\nAt Acme Inc. Requires SQL skills.",
            "generate_job_details": details_answer,
        }
    )
    with TestClient(create_app(TOKEN, db_path, runner)) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        created = client.post("/job-applications", json=basic_request(listing_text=text))
        application_id = created.json()["application_id"]

        queue = client.app.state.queue  # type: ignore[attr-defined]
        conn = connect(db_path)
        try:
            queue.trigger_staged(conn)  # the chain is staged (D-286) - trigger it to run
        finally:
            conn.close()
        assert queue.process_next()  # generate_job_listing
        assert queue.process_next()  # generate_job_details
        assert not queue.process_next()

        duplicate = client.post("/job-applications/intake/duplicate-check", json={"text": text})
    body = duplicate.json()
    assert body is not None
    assert body["application_id"] == application_id
    assert body["matched_by"] == "content"

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT sha256 FROM job_files WHERE job_application_id = ? AND kind = 'listing'",
            (application_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["sha256"] == listing_text_sha256(text)
