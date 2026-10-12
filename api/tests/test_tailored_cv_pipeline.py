"""Tests for the Tailored CV and Cover letter Claude Jobs (steps 36-37, job-llm-steps.md §5-6,
D-129 to D-131): the shared EDIT/INSERT AFTER/REMOVE/ADD ROW AFTER answer vocabulary, the cover
letter's punctuation/length checks, and the two steps end to end.
"""

from pathlib import Path

import docx
import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from localjobtracker.claude_jobs import get_claude_job
from localjobtracker.job_applications import (
    insert_job_application,
    set_master_cv,
    update_job_application,
)
from localjobtracker.job_files import insert_job_file, list_job_files
from localjobtracker.job_pipeline import (
    JobStepNotReady,
    build_cover_letter_prompt,
    check_cover_letter_style,
    cover_letter_ready,
    make_pipeline,
    parse_docx_edit_answer,
    submit_generate_cover_letter,
    submit_generate_tailored_cv,
    tailored_cv_ready,
)
from localjobtracker.profile_files import store_profile_file
from localjobtracker.profile_pipeline import DEFAULT_RULES_PATH, store_output
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"
FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_documents"
)

GOOD_CV_ANSWER = """=== EDIT ===
ID: B2
TEXT: Marketing Automation Engineer
=== END EDIT ===

=== INSERT AFTER ===
ID: B3
TEXT: Direct analyst with five years in SaaS data roles.
=== END INSERT AFTER ===

=== REMOVE ===
ID: B7
=== END REMOVE ===

=== ADD ROW AFTER ===
ID: T1R2
CELLS: Python | Intermediate
=== END ADD ROW AFTER ===
"""

GOOD_LETTER_ANSWER = (
    "=== EDIT ===\n"
    "ID: B1\n"
    "TEXT: 9 October 2026\n"
    "=== END EDIT ===\n\n"
    "=== EDIT ===\n"
    "ID: B2\n"
    "TEXT: Application for Marketing Automation Engineer\n"
    "=== END EDIT ===\n\n"
    "=== EDIT ===\n"
    "ID: B3\n"
    "TEXT: Dear Acme Inc Team,\n"
    "=== END EDIT ===\n\n"
    "=== EDIT ===\n"
    "ID: B4\n"
    "TEXT: " + " ".join(["word"] * 60) + "\n"
    "=== END EDIT ===\n\n"
    "=== EDIT ===\n"
    "ID: B5\n"
    "TEXT: " + " ".join(["word"] * 120) + "\n"
    "=== END EDIT ===\n\n"
    "=== EDIT ===\n"
    "ID: B6\n"
    "TEXT: " + " ".join(["word"] * 60) + "\n"
    "=== END EDIT ===\n"
)


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def add_application(db_path: Path) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    return app_id


def fill_job_details(db_path: Path, app_id: int) -> None:
    conn = connect(db_path)
    try:
        update_job_application(
            conn, app_id, {"description": "A role description.", "requirements": ["Strong SQL"]}
        )
    finally:
        conn.close()


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


def add_master_cv(db_path: Path, app_id: int) -> None:
    conn = connect(db_path)
    try:
        file = store_profile_file(
            conn, db_path.parent, "master_cv", "cv.docx", (FIXTURES / "master_cv.docx").read_bytes()
        )
        set_master_cv(conn, app_id, file.id)
        conn.commit()
    finally:
        conn.close()


def add_pdf_master_cv(db_path: Path, app_id: int) -> None:
    """A Master CV may legitimately be a PDF (profile_files.ALLOWED_EXTENSIONS) - regression
    test for a real bug found live (2026-10-09): docx_editor can only read a real .docx, and the
    first live Tailored CV run failed with a cryptic zipfile error against a PDF master."""
    pdf_fixtures = (
        Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"
    )
    conn = connect(db_path)
    try:
        file = store_profile_file(
            conn, db_path.parent, "master_cv", "cv.pdf", (pdf_fixtures / "cv_en.pdf").read_bytes()
        )
        set_master_cv(conn, app_id, file.id)
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


def add_breakdown(db_path: Path, app_id: int) -> None:
    conn = connect(db_path)
    try:
        insert_job_file(
            conn,
            app_id,
            kind="positioning_breakdown",
            name="Positioning breakdown.md",
            stored_path="x/breakdown.md",
            extraction_status="ok",
            extracted_text="| Requirement | Weight | Match | Reasoning |\n|---|---|---|---|\n",
        )
        conn.commit()
    finally:
        conn.close()


def make_tailored_cv_ready(db_path: Path) -> int:
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id)
    add_profile_documents(db_path)
    add_master_cv(db_path, app_id)
    add_breakdown(db_path, app_id)
    return app_id


def add_company_application(db_path: Path, company: str) -> int:
    """A second application with its own company, for the reference-cover-letter tests (D-161) -
    `add_application` always uses "Acme Inc", which is deliberately reused there for the
    same-company case."""
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": company, "role_title": "Analyst"})
        conn.commit()
    finally:
        conn.close()
    return app_id


def add_generated_cover_letter(db_path: Path, app_id: int, paragraph_text: str) -> None:
    """A previously-generated cover letter `.docx` for another application, filed the same way
    `_store_cover_letter_result` files a real one - read back as reference material (D-161)."""
    document = docx.Document()
    document.add_paragraph(paragraph_text)
    folder = db_path.parent / "files" / "reference"
    folder.mkdir(parents=True, exist_ok=True)
    stored_path = folder / f"letter-{app_id}.docx"
    document.save(str(stored_path))
    conn = connect(db_path)
    try:
        insert_job_file(
            conn,
            app_id,
            kind="cover_letter",
            name="Cover Letter.docx",
            stored_path=str(stored_path.relative_to(db_path.parent / "files")),
        )
        conn.commit()
    finally:
        conn.close()


def add_tailored_cv_stub(db_path: Path, app_id: int) -> None:
    conn = connect(db_path)
    try:
        insert_job_file(
            conn, app_id, kind="tailored_cv", name="Tailored CV.docx", stored_path="x/cv.docx"
        )
        conn.commit()
    finally:
        conn.close()


def make_cover_letter_ready(db_path: Path) -> int:
    app_id = make_tailored_cv_ready(db_path)
    add_tailored_cv_stub(db_path, app_id)
    add_cover_letter_template(db_path)
    return app_id


# --- parse_docx_edit_answer ------------------------------------------------------------------


def test_parse_docx_edit_answer_reads_all_four_operation_kinds() -> None:
    operations = parse_docx_edit_answer(GOOD_CV_ANSWER)
    kinds = {type(op).__name__ for op in operations}
    assert kinds == {"EditOp", "InsertAfterOp", "RemoveOp", "AddRowAfterOp"}


def test_parse_docx_edit_answer_tolerates_missing_closing_tags() -> None:
    text = "=== EDIT ===\nID: B2\nTEXT: New tagline\n\n=== REMOVE ===\nID: B7\n"
    operations = parse_docx_edit_answer(text)
    assert len(operations) == 2


def test_parse_docx_edit_answer_rejects_an_empty_answer() -> None:
    with pytest.raises(PromptRejected, match="did not include any edit blocks"):
        parse_docx_edit_answer("Nothing useful here.")


def test_parse_docx_edit_answer_rejects_a_block_missing_its_field() -> None:
    with pytest.raises(PromptRejected, match="missing ID or TEXT"):
        parse_docx_edit_answer("=== EDIT ===\nTEXT: no id given\n=== END EDIT ===\n")


# --- check_cover_letter_style -----------------------------------------------------------------


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def test_check_cover_letter_style_passes_a_clean_letter() -> None:
    check_cover_letter_style(_words(250))


def test_check_cover_letter_style_rejects_a_colon() -> None:
    with pytest.raises(PromptRejected, match="punctuation"):
        check_cover_letter_style(_words(100) + " role: data analyst " + _words(100))


def test_check_cover_letter_style_rejects_a_semicolon() -> None:
    with pytest.raises(PromptRejected, match="punctuation"):
        check_cover_letter_style(_words(100) + " roles; I apply " + _words(100))


def test_check_cover_letter_style_rejects_an_em_dash() -> None:
    with pytest.raises(PromptRejected, match="dash"):
        check_cover_letter_style(_words(100) + " roles — I apply " + _words(100))


def test_check_cover_letter_style_rejects_a_spaced_hyphen() -> None:
    with pytest.raises(PromptRejected, match="dash"):
        check_cover_letter_style(_words(100) + " roles - I apply " + _words(100))


def test_check_cover_letter_style_allows_a_compound_word_hyphen() -> None:
    check_cover_letter_style(_words(100) + " a multi-tenant platform " + _words(100))


def test_check_cover_letter_style_rejects_too_short() -> None:
    with pytest.raises(PromptRejected, match="words"):
        check_cover_letter_style(_words(20))


def test_check_cover_letter_style_rejects_too_long() -> None:
    with pytest.raises(PromptRejected, match="words"):
        check_cover_letter_style(_words(500))


# --- Gates ------------------------------------------------------------------------------------


def test_tailored_cv_ready_requires_every_input(db_path: Path) -> None:
    app_id = add_application(db_path)
    conn = connect(db_path)
    try:
        assert not tailored_cv_ready(conn, app_id)
    finally:
        conn.close()
    fill_job_details(db_path, app_id)
    add_profile_documents(db_path)
    add_master_cv(db_path, app_id)
    conn = connect(db_path)
    try:
        assert not tailored_cv_ready(conn, app_id)  # no positioning breakdown yet
    finally:
        conn.close()
    add_breakdown(db_path, app_id)
    conn = connect(db_path)
    try:
        assert tailored_cv_ready(conn, app_id)
    finally:
        conn.close()


def test_tailored_cv_ready_rejects_a_non_docx_master_cv(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id)
    add_profile_documents(db_path)
    add_pdf_master_cv(db_path, app_id)
    add_breakdown(db_path, app_id)
    conn = connect(db_path)
    try:
        assert not tailored_cv_ready(conn, app_id)
    finally:
        conn.close()


def test_generate_tailored_cv_rejects_a_non_docx_master_cv_with_a_clear_message(
    db_path: Path,
) -> None:
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id)
    add_profile_documents(db_path)
    add_pdf_master_cv(db_path, app_id)
    add_breakdown(db_path, app_id)
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    conn = connect(db_path)
    try:
        # The gate already refuses this (previous test), but submit directly to confirm the
        # defence inside render() itself is also clear, not a raw zipfile error.
        job_id = queue.submit(
            conn,
            "Generate: Tailored CV",
            "generate_tailored_cv",
            [("generate_tailored_cv", "")],
            job_application_id=app_id,
        )
    finally:
        conn.close()
    run_all(queue)
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "must be a .docx file" in (job.error or "")
    finally:
        conn.close()


def test_cover_letter_ready_requires_the_tailored_cv_and_a_template(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    conn = connect(db_path)
    try:
        assert not cover_letter_ready(conn, app_id)
    finally:
        conn.close()
    add_tailored_cv_stub(db_path, app_id)
    conn = connect(db_path)
    try:
        assert not cover_letter_ready(conn, app_id)  # no template yet
    finally:
        conn.close()
    add_cover_letter_template(db_path)
    conn = connect(db_path)
    try:
        assert cover_letter_ready(conn, app_id)
    finally:
        conn.close()


# --- Tailored CV: end to end -------------------------------------------------------------------


def test_generate_tailored_cv_end_to_end(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    conn = connect(db_path)
    try:
        job_id = submit_generate_tailored_cv(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        files = list_job_files(conn, app_id)
        tailored = [f for f in files if f["kind"] == "tailored_cv"]
        assert len(tailored) == 1
        assert tailored[0]["name"] == "Tailored CV.docx"
        stored_path = db_path.parent / "files" / str(tailored[0]["stored_path"])
    finally:
        conn.close()

    document = docx.Document(str(stored_path))
    texts = [p.text for p in document.paragraphs]
    assert "Marketing Automation Engineer" in texts
    assert "Direct analyst with five years in SaaS data roles." in texts
    assert "Maintained the CRM data pipeline" not in texts  # removed
    table = document.tables[0]
    assert [c.text for c in table.rows[-1].cells] == ["Python", "Intermediate"]


def test_generate_tailored_cv_fails_the_job_on_an_unknown_block_id(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    bad_answer = "=== EDIT ===\nID: B999\nTEXT: anything\n=== END EDIT ===\n"
    queue = make_queue(db_path, FakeRunner(text=bad_answer))
    conn = connect(db_path)
    try:
        job_id = submit_generate_tailored_cv(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "Unknown block id" in (job.error or "")
        assert [f for f in list_job_files(conn, app_id) if f["kind"] == "tailored_cv"] == []
    finally:
        conn.close()


def test_generate_tailored_cv_replaces_a_previous_version(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)
    for answer in (GOOD_CV_ANSWER, GOOD_CV_ANSWER):
        queue = make_queue(db_path, FakeRunner(text=answer))
        conn = connect(db_path)
        try:
            submit_generate_tailored_cv(conn, queue, app_id)
        finally:
            conn.close()
        run_all(queue)
    conn = connect(db_path)
    try:
        tailored = [f for f in list_job_files(conn, app_id) if f["kind"] == "tailored_cv"]
        assert len(tailored) == 1  # D-115: at most one current file, not two versions
    finally:
        conn.close()


def test_submit_generate_tailored_cv_rejects_when_not_ready(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_tailored_cv(conn, queue, app_id)
    finally:
        conn.close()


# --- Cover letter: end to end -------------------------------------------------------------------


def test_generate_cover_letter_end_to_end(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    queue = make_queue(db_path, FakeRunner(text=GOOD_LETTER_ANSWER))
    conn = connect(db_path)
    try:
        job_id = submit_generate_cover_letter(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        files = list_job_files(conn, app_id)
        letters = [f for f in files if f["kind"] == "cover_letter"]
        assert len(letters) == 1
        assert letters[0]["name"] == "Cover Letter.docx"
        stored_path = db_path.parent / "files" / str(letters[0]["stored_path"])
    finally:
        conn.close()

    document = docx.Document(str(stored_path))
    texts = [p.text for p in document.paragraphs]
    assert "Dear Acme Inc Team," in texts
    assert "Application for Marketing Automation Engineer" in texts


def test_generate_cover_letter_fails_the_job_on_a_punctuation_violation(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    bad_answer = GOOD_LETTER_ANSWER.replace("Dear Acme Inc Team,", "Dear Acme Inc Team: hello")
    queue = make_queue(db_path, FakeRunner(text=bad_answer))
    conn = connect(db_path)
    try:
        job_id = submit_generate_cover_letter(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "punctuation" in (job.error or "")
        assert [f for f in list_job_files(conn, app_id) if f["kind"] == "cover_letter"] == []
    finally:
        conn.close()


def test_submit_generate_cover_letter_rejects_when_not_ready(db_path: Path) -> None:
    app_id = make_tailored_cv_ready(db_path)  # no tailored CV or template yet
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_cover_letter(conn, queue, app_id)
    finally:
        conn.close()


# --- Cover letter: reference letter in the prompt (D-161) ------------------------------------
#
# Live bug (2026-10-12): the user's own writing rules say to read 1-2 existing cover letters
# before drafting, calibrating voice, preferring one for the same company. But every Claude run
# here has no tools (claude_code_runner.py), so the model tried a Bash call to go look for one on
# disk, which has nothing to call, and the whole answer was that failed attempt - no edit blocks
# at all. Fixed by giving the model the most relevant existing letter directly in the prompt.


def prompt_text(db_path: Path, app_id: int) -> str:
    conn = connect(db_path)
    try:
        return build_cover_letter_prompt(
            conn, db_path.parent, db_path.parent / "files", DEFAULT_RULES_PATH, app_id
        )
    finally:
        conn.close()


def test_cover_letter_prompt_says_none_written_yet_with_no_prior_letters(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    text = prompt_text(db_path, app_id)
    assert "(none written yet)" in text


def test_cover_letter_prompt_uses_the_most_recent_letter_with_no_same_company_one(
    db_path: Path,
) -> None:
    app_id = make_cover_letter_ready(db_path)
    other_id = add_company_application(db_path, "Other Co")
    add_generated_cover_letter(db_path, other_id, "Dear Other Co, an older reference letter.")
    text = prompt_text(db_path, app_id)
    assert "Dear Other Co, an older reference letter." in text


def test_cover_letter_prompt_prefers_a_same_company_letter_over_a_more_recent_one(
    db_path: Path,
) -> None:
    app_id = make_cover_letter_ready(db_path)  # company "Acme Inc" (add_application)
    other_id = add_company_application(db_path, "Other Co")
    same_company_id = add_company_application(db_path, "Acme Inc")
    add_generated_cover_letter(db_path, other_id, "Dear Other Co, the most recently written one.")
    add_generated_cover_letter(db_path, same_company_id, "Dear Acme Inc, the same-company one.")
    text = prompt_text(db_path, app_id)
    assert "Dear Acme Inc, the same-company one." in text
    assert "Dear Other Co, the most recently written one." not in text


def test_cover_letter_prompt_never_references_the_applications_own_letter(db_path: Path) -> None:
    app_id = make_cover_letter_ready(db_path)
    add_generated_cover_letter(db_path, app_id, "Dear Acme Inc, this application's own letter.")
    text = prompt_text(db_path, app_id)
    assert "(none written yet)" in text
    assert "this application's own letter" not in text


# --- Routes -------------------------------------------------------------------------------


def test_tailored_cv_route_201_when_ready_400_when_not(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        app_id = add_application(db_path)
        route = f"/job-applications/{app_id}/tailored-cv/generate"
        assert client.post(route).status_code == 400

    ready_id = make_tailored_cv_ready(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post(f"/job-applications/{ready_id}/tailored-cv/generate")
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_tailored_cv"


def test_tailored_cv_route_for_unknown_application_is_not_found(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.post("/job-applications/999/tailored-cv/generate").status_code == 404


def test_cover_letter_route_201_when_ready_400_when_not(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        app_id = add_application(db_path)
        route = f"/job-applications/{app_id}/cover-letter/generate"
        assert client.post(route).status_code == 400

    ready_id = make_cover_letter_ready(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post(f"/job-applications/{ready_id}/cover-letter/generate")
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_cover_letter"
