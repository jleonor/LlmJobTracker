"""Tests for Tailored CV's and Cover letter's chat-revise (D-141,
Agent/specs/job-revise-steps.md): reuses D-130's EDIT/INSERT AFTER/REMOVE/ADD ROW AFTER
operations, built against the *current* tailored CV/cover letter instead of the master CV/
template.
"""

from pathlib import Path

import docx
import pytest
from test_tailored_cv_pipeline import (  # noqa: F401  (imported for fixtures reuse, not direct use)
    GOOD_CV_ANSWER,
    GOOD_LETTER_ANSWER,
    add_application,
    make_cover_letter_ready,
    make_tailored_cv_ready,
)

from llmjobtracker import docx_editor
from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.job_files import list_job_files
from llmjobtracker.job_pipeline import submit_generate_cover_letter, submit_generate_tailored_cv
from llmjobtracker.job_revise_pipeline import (
    JobReviseNotReady,
    make_pipeline,
    submit_job_revise_turn,
)
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def submit(
    db_path: Path, queue: ClaudeJobQueue, app_id: int, section_kind: str, message: str
) -> int:
    conn = connect(db_path)
    try:
        return submit_job_revise_turn(conn, queue, app_id, section_kind, message)
    finally:
        conn.close()


def generate_tailored_cv(db_path: Path, app_id: int) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    conn = connect(db_path)
    try:
        submit_generate_tailored_cv(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)


def generate_cover_letter(db_path: Path, app_id: int) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_LETTER_ANSWER))
    conn = connect(db_path)
    try:
        submit_generate_cover_letter(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)


def stored_docx_path(db_path: Path, app_id: int, kind: str) -> Path:
    conn = connect(db_path)
    try:
        files = [f for f in list_job_files(conn, app_id) if f["kind"] == kind]
    finally:
        conn.close()
    assert len(files) == 1
    return db_path.parent / "files" / str(files[0]["stored_path"])


def current_blocks(db_path: Path, app_id: int, kind: str) -> list[docx_editor.Block]:
    path = stored_docx_path(db_path, app_id, kind)
    return docx_editor.list_blocks(docx_editor.read_document(path.read_bytes()))


# --- Tailored CV ---------------------------------------------------------------------------


def test_a_turn_edits_the_current_tailored_cv_not_the_master(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    generate_tailored_cv(db_path, app_id)
    # The inserted block from the one-shot generate is now part of the current document - find
    # its id fresh, rather than assuming the master CV's own numbering still applies.
    target = next(
        b for b in current_blocks(db_path, app_id, "tailored_cv") if "SaaS data roles" in b.text
    )
    answer = (
        f"=== EDIT ===\nID: {target.id}\n"
        "TEXT: Direct analyst with six years in SaaS data roles.\n=== END EDIT ===\n"
    )
    queue = make_queue(db_path, FakeRunner(text=answer))

    submit(db_path, queue, app_id, "tailored_cv", "Make it six years, not five.")
    run_all(queue)

    document = docx.Document(str(stored_docx_path(db_path, app_id, "tailored_cv")))
    texts = [p.text for p in document.paragraphs]
    assert "Direct analyst with six years in SaaS data roles." in texts
    assert "Direct analyst with five years in SaaS data roles." not in texts


def test_a_turns_prompt_is_built_from_the_current_file(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    generate_tailored_cv(db_path, app_id)
    runner = FakeRunner(text="=== EDIT ===\nID: B1\nTEXT: x\n=== END EDIT ===\n")
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "tailored_cv", "Tweak the first line.")
    run_all(queue)

    # The one-shot generate's own insert/removal are already reflected in what gets sent.
    assert "Direct analyst with five years in SaaS data roles." in runner.prompts[0]
    assert "Maintained the CRM data pipeline" not in runner.prompts[0]
    assert "TASK: revise_tailored_cv" in runner.prompts[0]


def test_a_turn_fails_on_an_unknown_block_id_and_leaves_the_file_unchanged(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    generate_tailored_cv(db_path, app_id)
    before = stored_docx_path(db_path, app_id, "tailored_cv").read_bytes()
    bad_answer = "=== EDIT ===\nID: B999\nTEXT: anything\n=== END EDIT ===\n"
    queue = make_queue(db_path, FakeRunner(text=bad_answer))

    submit(db_path, queue, app_id, "tailored_cv", "Change something that doesn't exist.")
    run_all(queue)

    after = stored_docx_path(db_path, app_id, "tailored_cv").read_bytes()
    assert before == after


def test_submit_rejects_when_tailored_cv_has_nothing_to_revise(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="no Tailored CV yet"):
        submit(db_path, queue, app_id, "tailored_cv", "Reword the tagline.")


# --- Cover letter ---------------------------------------------------------------------------


def test_a_turn_edits_the_current_cover_letter(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    generate_tailored_cv(db_path, app_id)
    generate_cover_letter(db_path, app_id)
    target = next(
        b
        for b in current_blocks(db_path, app_id, "cover_letter")
        if b.text == "Dear Acme Inc Team,"
    )
    answer = f"=== EDIT ===\nID: {target.id}\nTEXT: Dear Hiring Team,\n=== END EDIT ===\n"
    queue = make_queue(db_path, FakeRunner(text=answer))

    submit(db_path, queue, app_id, "cover_letter", "Use a more generic greeting.")
    run_all(queue)

    document = docx.Document(str(stored_docx_path(db_path, app_id, "cover_letter")))
    texts = [p.text for p in document.paragraphs]
    assert "Dear Hiring Team," in texts
    assert "Dear Acme Inc Team," not in texts


def test_a_cover_letter_turn_rejects_a_punctuation_violation(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    generate_tailored_cv(db_path, app_id)
    generate_cover_letter(db_path, app_id)
    before = stored_docx_path(db_path, app_id, "cover_letter").read_bytes()
    target = next(
        b
        for b in current_blocks(db_path, app_id, "cover_letter")
        if b.text == "Dear Acme Inc Team,"
    )
    bad_answer = (
        f"=== EDIT ===\nID: {target.id}\nTEXT: Dear Acme Inc Team: hello\n=== END EDIT ===\n"
    )
    queue = make_queue(db_path, FakeRunner(text=bad_answer))

    submit(db_path, queue, app_id, "cover_letter", "Add a colon after the greeting.")
    run_all(queue)

    after = stored_docx_path(db_path, app_id, "cover_letter").read_bytes()
    assert before == after


def test_submit_rejects_when_cover_letter_has_nothing_to_revise(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="no Cover letter yet"):
        submit(db_path, queue, app_id, "cover_letter", "Shorten the closing paragraph.")
