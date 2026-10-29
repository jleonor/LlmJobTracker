"""Tests for queue_add_job_chain (step 6, Agent/specs/intake-steps.md): once a row exists,
queuing the rest of Add Job's chosen workflow as ordered Claude Jobs.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any

from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_pipeline import (
    JOB_KIND_COVER_LETTER,
    JOB_KIND_DETAILS,
    JOB_KIND_GENERATE,
    JOB_KIND_POSITIONING,
    JOB_KIND_TAILORED_CV,
    make_pipeline,
    queue_add_job_chain,
)
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.runner import FakeRunner, Runner, RunResult
from llmjobtracker.storage import connect

LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


def make_queue(db_path: Path, runner: Runner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def add_application(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    return app_id


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def kinds_of(conn: sqlite3.Connection, job_ids: list[int]) -> list[str]:
    kinds = []
    for job_id in job_ids:
        job = get_claude_job(conn, job_id)
        assert job is not None
        kinds.append(job.kind)
    return kinds


class ScriptedRunner:
    """Returns a different canned answer per `TASK: <kind>` line, so one queue run can exercise
    several different Claude Job kinds in sequence, each with the answer shape its own parser
    needs."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Any = None,
    ) -> RunResult:
        self.prompts.append(prompt)
        for task, text in self.answers.items():
            if f"TASK: {task}" in prompt:
                return RunResult(ok=True, text=text, duration_ms=0, cost_usd=0.0, model="fake")
        raise AssertionError(f"No scripted answer for this prompt: {prompt[:200]!r}")


# --- Queuing: which kinds, in what order ------------------------------------------------------


def test_basic_workflow_queues_listing_then_job_details(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", "Some listing text", "basic")
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [JOB_KIND_GENERATE, JOB_KIND_DETAILS]


def test_positioning_workflow_adds_positioning(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(
            conn, queue, app_id, "paste", "Some listing text", "positioning"
        )
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [JOB_KIND_GENERATE, JOB_KIND_DETAILS, JOB_KIND_POSITIONING]


def test_full_workflow_adds_tailored_cv_and_cover_letter(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", "Some listing text", "full")
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [
        JOB_KIND_GENERATE,
        JOB_KIND_DETAILS,
        JOB_KIND_POSITIONING,
        JOB_KIND_TAILORED_CV,
        JOB_KIND_COVER_LETTER,
    ]


def test_every_queued_job_is_linked_to_the_new_application(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", "Some listing text", "full")
    finally:
        conn.close()

    conn = connect(db_path)
    try:
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.job_application_id == app_id
    finally:
        conn.close()


def test_every_queued_job_starts_staged_not_queued(db_path: Path) -> None:
    """D-286/D-287: Add Job's own chain is staged, so it doesn't run until the header's Trigger
    workflows button triggers it - unlike a manual Generate (LLM) button elsewhere, which still
    queues immediately (not exercised here, since this module is only Add Job's own chain)."""
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", "Some listing text", "full")
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "staged"
        assert queue.process_next() is False  # nothing queued - every step is staged
    finally:
        conn.close()


def test_unknown_workflow_raises(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        try:
            queue_add_job_chain(conn, queue, app_id, "paste", "Some listing text", "deluxe")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        conn.close()


# --- Actually running the chain ---------------------------------------------------------------


def test_basic_workflow_runs_end_to_end(db_path: Path) -> None:
    listing_text = "Senior Data Analyst at Acme Inc. Must know SQL and Python."
    details_answer = (
        "=== DESCRIPTION ===\nA data analyst role at Acme Inc.\n=== END DESCRIPTION ===\n\n"
        "=== REQUIREMENT ===\nMust know SQL and Python.\n=== END REQUIREMENT ==="
    )
    runner = ScriptedRunner(
        {"generate_job_listing": listing_text, "generate_job_details": details_answer}
    )
    app_id = add_application(db_path)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", listing_text, "basic")
        queue.trigger_staged(conn)  # the chain is staged (D-286) - nothing runs until triggered
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "done"
        row = conn.execute(
            "SELECT description, requirements FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["description"] == "A data analyst role at Acme Inc."
        assert "Must know SQL and Python." in row["requirements"]
    finally:
        conn.close()


def test_positioning_workflow_fails_cleanly_with_no_profile_documents(db_path: Path) -> None:
    """The chain is queued before Positioning analysis's own gate could possibly be met - this
    proves build_positioning_prompt's own render-time PromptRejected is a real safety net, not
    just a bypassed check: Job details still succeeds, and Positioning fails with a clear reason
    rather than inventing a score (D-85)."""
    listing_text = "Senior Data Analyst at Acme Inc. Must know SQL."
    details_answer = (
        "=== DESCRIPTION ===\nA data analyst role.\n=== END DESCRIPTION ===\n\n"
        "=== REQUIREMENT ===\nMust know SQL.\n=== END REQUIREMENT ==="
    )
    runner = ScriptedRunner(
        {"generate_job_listing": listing_text, "generate_job_details": details_answer}
    )
    app_id = add_application(db_path)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_job_chain(conn, queue, app_id, "paste", listing_text, "positioning")
        queue.trigger_staged(conn)  # the chain is staged (D-286) - nothing runs until triggered
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        listing_job = get_claude_job(conn, job_ids[0])
        details_job = get_claude_job(conn, job_ids[1])
        positioning_job = get_claude_job(conn, job_ids[2])
        assert listing_job is not None and listing_job.status == "done"
        assert details_job is not None and details_job.status == "done"
        assert positioning_job is not None and positioning_job.status == "failed"
        assert positioning_job.error is not None
    finally:
        conn.close()
