"""Tests for Add Job's identity step (step 5, Agent/specs/intake-steps.md): company/role/lane/
location/portal, extracted from reviewed text before a row exists.
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
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.profile_pipeline import store_output
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
    assert "(none written yet)" in prompt  # no strategy document stored
    assert "(none yet)" in prompt  # no location values stored anywhere yet


def test_build_identity_prompt_includes_the_strategy_and_existing_locations(
    db_path: Path,
) -> None:
    conn = connect(db_path)
    try:
        store_output(
            conn, "strategy", "# Strategy\n\nLead with data work.", None, [], source="generated"
        )
        insert_job_application(conn, {"company": "Co", "role_title": "A", "location": "Geneva"})
        insert_job_application(conn, {"company": "Co", "role_title": "B", "location": "Zurich"})
        conn.commit()
        prompt = build_identity_prompt(conn, "some listing text")
    finally:
        conn.close()
    assert "Lead with data work." in prompt
    assert "- Geneva" in prompt
    assert "- Zurich" in prompt


# --- Parsing the answer --------------------------------------------------------------------


def test_parse_identity_answer_reads_every_field() -> None:
    answer = parse_identity_answer(GOOD_ANSWER)
    assert answer.company == "Acme Inc"
    assert answer.role_title == "Senior Data Analyst"
    assert answer.lane == "Data & Analytics"
    assert answer.location == "Geneva"
    assert answer.portal_name == "LinkedIn"
    assert answer.portal_url == "https://example.com/jobs/123"


def test_parse_identity_answer_rejects_a_missing_company() -> None:
    bad = GOOD_ANSWER.replace("Acme Inc", "Unknown")
    with pytest.raises(PromptRejected, match="company"):
        parse_identity_answer(bad)


def test_parse_identity_answer_rejects_a_missing_role_title() -> None:
    bad = (
        "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
        "=== ROLE TITLE ===\nUnknown\n=== END ROLE TITLE ==="
    )
    with pytest.raises(PromptRejected, match="role"):
        parse_identity_answer(bad)


def test_parse_identity_answer_treats_unknown_and_empty_optional_fields_as_none() -> None:
    answer = parse_identity_answer(
        "=== COMPANY ===\nAcme Inc\n=== END COMPANY ===\n\n"
        "=== ROLE TITLE ===\nSenior Data Analyst\n=== END ROLE TITLE ===\n\n"
        "=== LANE ===\nUnknown\n=== END LANE ===\n\n"
        "=== LOCATION ===\n\n=== END LOCATION ===\n\n"
        "=== PORTAL NAME ===\nUnknown\n=== END PORTAL NAME ===\n\n"
        "=== PORTAL URL ===\n\n=== END PORTAL URL ==="
    )
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
        answer = parse_identity_answer(exchange.result_text or "")
        assert answer.company == "Acme Inc"
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
