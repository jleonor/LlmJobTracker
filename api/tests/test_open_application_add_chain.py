"""Tests for queue_add_open_application_chain (D-296, Phase 17) and the two new Generate steps
it introduces, generate_open_application_sources and generate_open_application_relevance
(D-295, D-297, D-299, Agent/specs/open-application-llm-steps.md).
"""

import sqlite3
import threading
from pathlib import Path
from typing import Any

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.open_application_files import latest_open_application_file_of_kind
from llmjobtracker.open_application_pipeline import (
    ADD_OPEN_APPLICATION_WORKFLOWS,
    GEN_COVER_LETTER,
    GEN_CV,
    GEN_INTRODUCTION,
    GEN_RELEVANCE,
    GEN_SOURCES,
    build_relevance_prompt,
    create_open_application,
    make_pipeline,
    queue_add_open_application_chain,
)
from llmjobtracker.open_application_research import ResearchItemInput
from llmjobtracker.open_applications import get_open_application_detail, set_master_cv
from llmjobtracker.profile_files import store_profile_file
from llmjobtracker.profile_pipeline import store_output
from llmjobtracker.runner import FakeRunner, Runner, RunResult
from llmjobtracker.storage import connect

FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_documents"
)


def make_queue(db_path: Path, runner: Runner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


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


def add_open_application(db_path: Path, items: list[ResearchItemInput] | None = None) -> int:
    conn = connect(db_path)
    try:
        application_id = create_open_application(
            conn,
            {"target_name": "Acme Talent Pool", "target_type": "talent_pool"},
            items
            if items is not None
            else [ResearchItemInput(source_type="text", content="Acme is hiring data analysts.")],
        )
        conn.commit()
    finally:
        conn.close()
    return application_id


def add_profile_documents(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        for kind, text in (
            ("full_cv_history", "# Career history\n\nAnalyst with five years of SQL work."),
            ("questionnaire_analysis", "# Questionnaire analysis\n\nPrefers data roles."),
            ("strategy", "# Strategy\n\nLead with SQL and reporting."),
        ):
            store_output(conn, kind, text, None, [], source="generated")
        conn.commit()
    finally:
        conn.close()


def add_master_cv(db_path: Path, application_id: int) -> None:
    conn = connect(db_path)
    try:
        file = store_profile_file(
            conn, db_path.parent, "master_cv", "cv.docx", (FIXTURES / "master_cv.docx").read_bytes()
        )
        set_master_cv(conn, application_id, file.id)
        conn.commit()
    finally:
        conn.close()


def add_cover_letter_template(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        store_profile_file(
            conn,
            db_path.parent,
            "cover_letter_template",
            "template.docx",
            (FIXTURES / "cover_letter_template.docx").read_bytes(),
        )
        conn.commit()
    finally:
        conn.close()


class ScriptedRunner:
    """Mirrors test_add_job_chain.py's own ScriptedRunner: a different canned answer per
    `TASK: <kind>` line, so one queue run can exercise several Claude Job kinds in sequence."""

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


GOOD_RELEVANCE_ANSWER = """=== INDUSTRY ===
IT
=== END INDUSTRY ===

=== COMPANY TYPE ===
SaaS vendor
=== END COMPANY TYPE ===

=== SUMMARY ===
Acme is a data analytics vendor.
=== END SUMMARY ===

=== RELEVANCE ===
Matches your SQL and reporting background.
=== END RELEVANCE ===
"""

GOOD_CV_ANSWER = "=== EDIT ===\nID: B2\nTEXT: Data Analyst\n=== END EDIT ===\n"

GOOD_LETTER_ANSWER = (
    "=== EDIT ===\nID: B1\nTEXT: 9 October 2026\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B2\nTEXT: Application to Acme Talent Pool\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B3\nTEXT: Dear Acme Team,\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B4\nTEXT: " + " ".join(["word"] * 60) + "\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B5\nTEXT: " + " ".join(["word"] * 120) + "\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B6\nTEXT: " + " ".join(["word"] * 60) + "\n=== END EDIT ===\n"
)

GOOD_INTRODUCTION_ANSWER = (
    "=== SUBJECT ===\nFollowing up\n=== END SUBJECT ===\n\n"
    "=== MESSAGE ===\nHello, I would like to be considered. Thank you.\n=== END MESSAGE ===\n"
)


# --- Queuing: which kinds, in what order --------------------------------------------------------


def test_sources_workflow_queues_sources_only(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "sources")
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [GEN_SOURCES]


def test_relevance_workflow_adds_relevance(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "relevance")
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [GEN_SOURCES, GEN_RELEVANCE]


def test_cv_cover_letter_workflow_adds_cv_then_cover_letter(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "cv_cover_letter")
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [GEN_SOURCES, GEN_RELEVANCE, GEN_CV, GEN_COVER_LETTER]


def test_cv_introduction_workflow_adds_cv_then_introduction(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "cv_introduction")
        kinds = kinds_of(conn, job_ids)
    finally:
        conn.close()
    assert kinds == [GEN_SOURCES, GEN_RELEVANCE, GEN_CV, GEN_INTRODUCTION]


def test_every_queued_step_starts_staged_not_queued(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "cv_cover_letter")
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "staged"
        assert queue.process_next() is False  # nothing queued - every step is staged
    finally:
        conn.close()


def test_every_queued_step_is_linked_to_the_application(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "cv_introduction")
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.open_application_id == app_id
    finally:
        conn.close()


def test_unknown_workflow_raises(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    queue = make_queue(db_path, FakeRunner(text="x"))
    conn = connect(db_path)
    try:
        try:
            queue_add_open_application_chain(conn, queue, app_id, "deluxe")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        conn.close()
    assert "deluxe" not in ADD_OPEN_APPLICATION_WORKFLOWS


# --- Actually running the chain ------------------------------------------------------------------


def test_sources_workflow_runs_end_to_end(db_path: Path) -> None:
    items = [
        ResearchItemInput(source_type="text", content="Acme hires data analysts."),
        ResearchItemInput(source_type="text", content="Acme is a Series B fintech."),
    ]
    app_id = add_open_application(db_path, items)
    runner = ScriptedRunner(
        {
            "generate_open_application_sources": (
                "=== SOURCE 1 ===\nAcme hires data analysts.\n=== END SOURCE 1 ===\n\n"
                "=== SOURCE 2 ===\nAcme is a Series B fintech.\n=== END SOURCE 2 ==="
            )
        }
    )
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "sources")
        queue.trigger_staged(conn)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_ids[0])
        assert job is not None
        assert job.status == "done"
        detail = get_open_application_detail(conn, app_id)
        assert detail is not None
        source_files = [f for f in detail.files if f.kind == "source"]
        assert len(source_files) == 2
    finally:
        conn.close()


def test_sources_workflow_skips_a_failed_extraction_item(db_path: Path) -> None:
    """A research item with no extracted text (a failed URL fetch) is never sent to the model -
    only the usable item gets a Source file."""
    app_id = add_open_application(
        db_path,
        [
            ResearchItemInput(source_type="text", content="Acme hires data analysts."),
            ResearchItemInput(
                source_type="url", content="https://this-domain-does-not-exist-abc.test"
            ),
        ],
    )
    runner = ScriptedRunner(
        {
            "generate_open_application_sources": (
                "=== SOURCE 1 ===\nAcme hires data analysts.\n=== END SOURCE 1 ==="
            )
        }
    )
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "sources")
        queue.trigger_staged(conn)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_ids[0])
        assert job is not None
        assert job.status == "done"
        detail = get_open_application_detail(conn, app_id)
        assert detail is not None
        assert len([f for f in detail.files if f.kind == "source"]) == 1
    finally:
        conn.close()


def test_relevance_workflow_runs_end_to_end(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    add_profile_documents(db_path)
    runner = ScriptedRunner(
        {
            "generate_open_application_sources": (
                "=== SOURCE 1 ===\nAcme hires data analysts.\n=== END SOURCE 1 ==="
            ),
            "generate_open_application_relevance": GOOD_RELEVANCE_ANSWER,
        }
    )
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "relevance")
        queue.trigger_staged(conn)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "done"
        detail = get_open_application_detail(conn, app_id)
        assert detail is not None
        assert detail.industry == "IT"
        assert detail.company_type == "SaaS vendor"
        assert detail.summary == "Acme is a data analytics vendor."
        assert detail.relevance == "Matches your SQL and reporting background."
    finally:
        conn.close()


def test_relevance_prompt_fails_cleanly_with_no_source_files_yet(db_path: Path) -> None:
    """Proves build_relevance_prompt's own render-time PromptRejected is a real safety net: the
    chain always queues Sources ahead of Relevance (D-296), but calling Relevance's own prompt
    builder directly, before Sources has run, must not invent anything (D-85)."""
    app_id = add_open_application(db_path)
    conn = connect(db_path)
    try:
        raised = False
        try:
            build_relevance_prompt(conn, app_id)
        except PromptRejected:
            raised = True
        assert raised
    finally:
        conn.close()


def test_relevance_succeeds_with_no_profile_documents(db_path: Path) -> None:
    """Relevance has no hard gate on the three profile documents (D-297, D-85) - a run with none
    of them still succeeds, leaving RELEVANCE empty rather than failing the job."""
    app_id = add_open_application(db_path)
    runner = ScriptedRunner(
        {
            "generate_open_application_sources": (
                "=== SOURCE 1 ===\nAcme hires data analysts.\n=== END SOURCE 1 ==="
            ),
            "generate_open_application_relevance": (
                "=== INDUSTRY ===\nIT\n=== END INDUSTRY ===\n\n"
                "=== COMPANY TYPE ===\n=== END COMPANY TYPE ===\n\n"
                "=== SUMMARY ===\nAcme hires analysts.\n=== END SUMMARY ===\n\n"
                "=== RELEVANCE ===\n=== END RELEVANCE ==="
            ),
        }
    )
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        queue_add_open_application_chain(conn, queue, app_id, "relevance")
        queue.trigger_staged(conn)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        detail = get_open_application_detail(conn, app_id)
        assert detail is not None
        assert detail.industry == "IT"
        assert detail.relevance is None
    finally:
        conn.close()


def test_cv_cover_letter_workflow_runs_end_to_end(db_path: Path) -> None:
    app_id = add_open_application(db_path)
    add_profile_documents(db_path)
    add_master_cv(db_path, app_id)
    add_cover_letter_template(db_path)
    runner = ScriptedRunner(
        {
            "generate_open_application_sources": (
                "=== SOURCE 1 ===\nAcme hires data analysts.\n=== END SOURCE 1 ==="
            ),
            "generate_open_application_relevance": GOOD_RELEVANCE_ANSWER,
            "generate_open_application_cv": GOOD_CV_ANSWER,
            "generate_open_application_cover_letter": GOOD_LETTER_ANSWER,
        }
    )
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_ids = queue_add_open_application_chain(conn, queue, app_id, "cv_cover_letter")
        queue.trigger_staged(conn)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        for job_id in job_ids:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "done"
        assert latest_open_application_file_of_kind(conn, app_id, "tailored_cv") is not None
        assert latest_open_application_file_of_kind(conn, app_id, "cover_letter") is not None
    finally:
        conn.close()
