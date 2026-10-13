"""Tests for the Listing's two Claude Job kinds (steps 26-27, job-llm-steps.md): the sanity
check, and the Generate (LLM) step that stores the result as the application's listing file.
"""

from pathlib import Path

from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import list_job_files, store_job_file
from llmjobtracker.job_pipeline import (
    JOB_KIND_CHECK,
    JOB_KIND_GENERATE,
    build_check_prompt,
    build_generate_prompt,
    make_pipeline,
    parse_check_answer,
    submit_check_job_listing_text,
    submit_generate_job_listing,
)
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


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


# --- Prompt building and answer parsing (no queue involved) ---------------------------------


def test_build_check_prompt_includes_the_task_and_the_text() -> None:
    prompt = build_check_prompt("Senior Data Analyst, must know SQL.")
    assert "TASK: check_job_listing_text" in prompt
    assert "Senior Data Analyst, must know SQL." in prompt
    assert "=== EXTRACTED TEXT ===" in prompt


def test_build_generate_prompt_names_the_method() -> None:
    prompt = build_generate_prompt("url", "Senior Data Analyst.")
    assert "TASK: generate_job_listing" in prompt
    assert "extracted from a URL" in prompt
    assert "Senior Data Analyst." in prompt


def test_build_generate_prompt_rejects_an_unknown_method() -> None:
    try:
        build_generate_prompt("carrier-pigeon", "x")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_parse_check_answer_reads_yes_and_no() -> None:
    assert parse_check_answer("LOOKS_LIKE_A_JOB_POSTING: yes\nIt names a role and requirements.")
    assert not parse_check_answer("LOOKS_LIKE_A_JOB_POSTING: no\nJust a cookie banner.")
    assert parse_check_answer("looks_like_a_job_posting: YES\nreason")  # case-insensitive


def test_parse_check_answer_fails_open_to_no_on_a_malformed_answer() -> None:
    assert not parse_check_answer("I'm not sure what this is.")
    assert not parse_check_answer("")


# --- The check job -----------------------------------------------------------------------------


def test_check_job_completes_with_a_yes_answer(db_path: Path) -> None:
    app_id = add_application(db_path)
    runner = FakeRunner(text="LOOKS_LIKE_A_JOB_POSTING: yes\nIt names a role and requirements.")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_check_job_listing_text(conn, queue, app_id, "Senior Data Analyst...")
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.job_application_id == app_id
        assert job.prompts[0].prompt_kind == JOB_KIND_CHECK
        row = conn.execute(
            "SELECT result_text FROM claude_job_prompts WHERE claude_job_id = ?", (job_id,)
        ).fetchone()
        assert parse_check_answer(row["result_text"])
    finally:
        conn.close()
    assert "Senior Data Analyst..." in runner.prompts[0]
    # Nothing is stored for a check - no job_files row appears from running it.
    conn = connect(db_path)
    try:
        assert list_job_files(conn, app_id) == []
    finally:
        conn.close()


def test_check_job_completes_with_a_no_or_malformed_answer_rather_than_failing(
    db_path: Path,
) -> None:
    for canned in ("LOOKS_LIKE_A_JOB_POSTING: no\nJust a cookie banner.", "garbled output"):
        app_id = add_application(db_path)
        queue = make_queue(db_path, FakeRunner(text=canned))
        conn = connect(db_path)
        try:
            job_id = submit_check_job_listing_text(conn, queue, app_id, "some text")
        finally:
            conn.close()
        run_all(queue)
        conn = connect(db_path)
        try:
            job = get_claude_job(conn, job_id)
            assert job is not None
            assert job.status == "done"
        finally:
            conn.close()


def test_check_job_runs_with_no_application_yet(db_path: Path) -> None:
    """Add Job runs this before a row exists (intake-steps.md) - the queue has always allowed a
    Claude Job linked to no application (D-49)."""
    runner = FakeRunner(text="LOOKS_LIKE_A_JOB_POSTING: yes\nIt names a role and requirements.")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_check_job_listing_text(conn, queue, None, "Senior Data Analyst...")
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.job_application_id is None
    finally:
        conn.close()


def test_submit_check_rejects_empty_text(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        try:
            submit_check_job_listing_text(conn, queue, app_id, "   ")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        conn.close()


# --- The generate job ---------------------------------------------------------------------------


def test_generate_job_stores_the_document_as_the_listing_file(db_path: Path) -> None:
    app_id = add_application(db_path)
    document = "# Senior Data Analyst\n\n## Requirements\n- Strong SQL\n"
    queue = make_queue(db_path, FakeRunner(text=document))
    conn = connect(db_path)
    try:
        job_id = submit_generate_job_listing(conn, queue, app_id, "paste", "Senior Data Analyst...")
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.prompts[0].prompt_kind == JOB_KIND_GENERATE

        files = list_job_files(conn, app_id)
        assert len(files) == 1
        assert files[0]["kind"] == "listing"
        assert files[0]["name"] == "Analyst - Listing.md"
        assert files[0]["extraction_status"] == "ok"
        stored_path = db_path.parent / "files" / str(files[0]["stored_path"])
        # clean_document strips surrounding whitespace, same as every other generated document.
        assert stored_path.read_text(encoding="utf-8") == document.strip()
    finally:
        conn.close()


def test_generate_job_replaces_an_existing_listing_file(db_path: Path) -> None:
    app_id = add_application(db_path)
    conn = connect(db_path)
    try:
        store_job_file(
            conn,
            db_path.parent / "files",
            app_id,
            "listing",
            "Job Listing.pdf",
            (LISTING_FIXTURES / "listing.pdf").read_bytes(),
        )
    finally:
        conn.close()

    document = "# Senior Data Analyst (regenerated)\n"
    queue = make_queue(db_path, FakeRunner(text=document))
    conn = connect(db_path)
    try:
        submit_generate_job_listing(conn, queue, app_id, "upload", "reviewed text")
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        files = list_job_files(conn, app_id)
        assert len(files) == 1  # the old PDF row and file are gone, not kept alongside the new one
        assert files[0]["name"] == "Analyst - Listing.md"
    finally:
        conn.close()
    assert not (db_path.parent / "files" / "Acme Inc" / "Analyst" / "Job Listing.pdf").exists()


def test_submit_generate_rejects_empty_text(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        try:
            submit_generate_job_listing(conn, queue, app_id, "paste", "   ")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        conn.close()
