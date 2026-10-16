"""Tests for Add Job's identity step (step 5, Agent/specs/intake-steps.md): company/role/lane/
location/portal, extracted from reviewed text before a row exists. Lane is matched against the
approved catalog (Agent/specs/lane-steps.md §2, D-215), not the strategy document's prose.
"""

from pathlib import Path

import pytest

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job, prompt_exchange
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_pipeline import (
    JOB_KIND_IDENTITY,
    build_identity_prompt,
    make_pipeline,
    parse_identity_answer,
    submit_extract_job_identity,
)
from llmjobtracker.lanes import create_lane
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


GOOD_ANSWER = (
    "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
    "=== ROLE TITLE ===\nSenior Data Analyst\n=== END ROLE TITLE ===\n\n"
    "=== LANE ===\nData & Analytics\n=== END LANE ===\n\n"
    "=== LOCATION ===\nGeneva\n=== END LOCATION ===\n\n"
    "=== PORTAL NAME ===\nLinkedIn\n=== END PORTAL NAME ===\n\n"
    "=== PORTAL URL ===\nhttps://example.com/jobs/123\n=== END PORTAL URL ==="
)


# --- Building the prompt -------------------------------------------------------------------


def test_build_identity_prompt_includes_the_task_and_text(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        prompt = build_identity_prompt(conn, "Senior Data Analyst at Acme Inc.")
    finally:
        conn.close()
    assert "TASK: extract_job_identity" in prompt
    assert "Senior Data Analyst at Acme Inc." in prompt
    assert "- Other: Roles that don't clearly fit any of the lanes above." in prompt
    assert "(none yet)" in prompt  # no location values stored anywhere yet


def test_build_identity_prompt_includes_the_lanes_and_existing_locations(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Data & Analytics", "Reporting and dashboard roles.", None)
        insert_job_application(conn, {"company": "Co", "role_title": "A", "location": "Geneva"})
        insert_job_application(conn, {"company": "Co", "role_title": "B", "location": "Zurich"})
        conn.commit()
        prompt = build_identity_prompt(conn, "some listing text")
    finally:
        conn.close()
    assert "Data & Analytics: Reporting and dashboard roles." in prompt
    assert "- Geneva" in prompt
    assert "- Zurich" in prompt


# --- Parsing the answer --------------------------------------------------------------------


def test_parse_identity_answer_reads_every_field(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Data & Analytics", None, None)
        conn.commit()
        answer = parse_identity_answer(conn, GOOD_ANSWER)
    finally:
        conn.close()
    assert answer.company == "Acme Inc"
    assert answer.role_title == "Senior Data Analyst"
    assert answer.lane == "Data & Analytics"
    assert answer.location == "Geneva"
    assert answer.portal_name == "LinkedIn"
    assert answer.portal_url == "https://example.com/jobs/123"


def test_parse_identity_answer_matches_a_lane_case_insensitively(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Data & Analytics", None, None)
        conn.commit()
        lowercased = GOOD_ANSWER.replace("Data & Analytics", "data & analytics")
        answer = parse_identity_answer(conn, lowercased)
    finally:
        conn.close()
    # Resolves to the catalog's own stored casing, not whatever the model answered with.
    assert answer.lane == "Data & Analytics"


def test_parse_identity_answer_falls_back_to_none_for_a_lane_not_in_the_catalog(
    db_path: Path,
) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Product Analytics", None, None)
        conn.commit()
        answer = parse_identity_answer(conn, GOOD_ANSWER)
    finally:
        conn.close()
    assert answer.lane is None


def test_parse_identity_answer_rejects_a_missing_company(db_path: Path) -> None:
    bad = GOOD_ANSWER.replace("Acme Inc", "Unknown")
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="company"):
            parse_identity_answer(conn, bad)
    finally:
        conn.close()


def test_parse_identity_answer_rejects_a_missing_role_title(db_path: Path) -> None:
    bad = (
        "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
        "=== ROLE TITLE ===\nUnknown\n=== END ROLE TITLE ==="
    )
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="role"):
            parse_identity_answer(conn, bad)
    finally:
        conn.close()


def test_parse_identity_answer_treats_unknown_and_empty_optional_fields_as_none(
    db_path: Path,
) -> None:
    conn = connect(db_path)
    try:
        answer = parse_identity_answer(
            conn,
            "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
            "=== ROLE TITLE ===\nSenior Data Analyst\n=== END ROLE TITLE ===\n\n"
            "=== LANE ===\nUnknown\n=== END LANE ===\n\n"
            "=== LOCATION ===\n\n=== END LOCATION ===\n\n"
            "=== PORTAL NAME ===\nUnknown\n=== END PORTAL NAME ===\n\n"
            "=== PORTAL URL ===\n\n=== END PORTAL URL ===",
        )
    finally:
        conn.close()
    assert answer.lane is None
    assert answer.location is None
    assert answer.portal_name is None
    assert answer.portal_url is None


# --- The queued job -------------------------------------------------------------------------


def test_identity_job_runs_with_no_application_and_its_answer_is_readable(
    db_path: Path,
) -> None:
    runner = FakeRunner(text=GOOD_ANSWER)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        create_lane(conn, "Data & Analytics", None, None)
        conn.commit()
        job_id = submit_extract_job_identity(conn, queue, "Senior Data Analyst at Acme Inc.")
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.job_application_id is None
        assert job.prompts[0].prompt_kind == JOB_KIND_IDENTITY

        exchange = prompt_exchange(conn, job_id, 0)
        assert exchange is not None
        answer = parse_identity_answer(conn, exchange.result_text or "")
        assert answer.company == "Acme Inc"
        assert answer.lane == "Data & Analytics"
    finally:
        conn.close()


def test_submit_identity_rejects_empty_text(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_ANSWER))
    conn = connect(db_path)
    try:
        with pytest.raises(ValueError):
            submit_extract_job_identity(conn, queue, "   ")
    finally:
        conn.close()
