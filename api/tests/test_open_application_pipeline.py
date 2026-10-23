"""Tests for Open Applications' four Generate/Revise (LLM) sections (Agent/specs/
open-application-llm-steps.md): Company details, Tailored CV, Cover letter, Introduction
message.
"""

from pathlib import Path

from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.claude_jobs import get_claude_job, prompt_exchange
from llmjobtracker.open_application_files import latest_open_application_file_of_kind
from llmjobtracker.open_application_pipeline import (
    OpenApplicationStepNotReady,
    build_open_application_identity_prompt,
    cover_letter_ready,
    create_open_application,
    cv_ready,
    introduction_message_ready,
    make_pipeline,
    parse_company_details_answer,
    parse_introduction_message_answer,
    parse_open_application_identity_answer,
    submit_extract_open_application_identity,
    submit_generate_cover_letter,
    submit_generate_cv,
    submit_generate_introduction_message,
    submit_open_application_revise_turn,
)
from llmjobtracker.open_application_research import ResearchItemInput
from llmjobtracker.open_applications import (
    count_open_applications,
    get_open_application_detail,
    set_master_cv,
)
from llmjobtracker.profile_files import store_profile_file
from llmjobtracker.profile_pipeline import store_output
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_documents"
)

GOOD_COMPANY_DETAILS_ANSWER = """=== TARGET NAME ===
Acme Talent Pool
=== END TARGET NAME ===

=== TARGET TYPE ===
talent_pool
=== END TARGET TYPE ===

=== CONTACT NAME ===
=== END CONTACT NAME ===

=== CONTACT TITLE ===
=== END CONTACT TITLE ===

=== CONTACT EMAIL ===
=== END CONTACT EMAIL ===

=== ANGLE ===
=== END ANGLE ===

=== WHY THIS COMPANY ===
They have a strong data team.
=== END WHY THIS COMPANY ===
"""

GOOD_CV_ANSWER = """=== EDIT ===
ID: B2
TEXT: Data Analyst
=== END EDIT ===
"""

GOOD_LETTER_ANSWER = (
    "=== EDIT ===\nID: B1\nTEXT: 9 October 2026\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B2\nTEXT: Application to Acme Talent Pool\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B3\nTEXT: Dear Acme Team,\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B4\nTEXT: " + " ".join(["word"] * 60) + "\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B5\nTEXT: " + " ".join(["word"] * 120) + "\n=== END EDIT ===\n\n"
    "=== EDIT ===\nID: B6\nTEXT: " + " ".join(["word"] * 60) + "\n=== END EDIT ===\n"
)

GOOD_INTRODUCTION_ANSWER = """=== SUBJECT ===
Following up on your talent pool
=== END SUBJECT ===

=== MESSAGE ===
Hello, I would like to be considered for your talent pool. Thank you.
=== END MESSAGE ===
"""


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


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


def add_open_application(db_path: Path, fields: dict[str, str | None] | None = None) -> int:
    """Creates a row directly with `fields` already resolved - the wizard's own pre-creation
    identity step (tested separately below) is what would normally have produced them."""
    conn = connect(db_path)
    try:
        application_id = create_open_application(
            conn,
            fields or {},
            [ResearchItemInput(source_type="text", content="Acme is hiring data analysts.")],
        )
        conn.commit()
    finally:
        conn.close()
    return application_id


COMPANY_DETAILS_FIELDS: dict[str, str | None] = {
    "target_name": "Acme Talent Pool",
    "target_type": "talent_pool",
    "why_this_company": "They have a strong data team.",
}


# --- Parsing (no queue involved) ----------------------------------------------------------------


def test_parse_company_details_answer_reads_the_fields() -> None:
    answer = parse_company_details_answer(GOOD_COMPANY_DETAILS_ANSWER, typed_angle=None)
    assert answer.target_name == "Acme Talent Pool"
    assert answer.target_type == "talent_pool"
    assert answer.why_this_company == "They have a strong data team."


def test_parse_company_details_answer_falls_back_to_none_on_a_bad_target_type() -> None:
    answer = parse_company_details_answer(
        GOOD_COMPANY_DETAILS_ANSWER.replace("talent_pool", "carrier_pigeon"), typed_angle=None
    )
    assert answer.target_type is None


def test_parse_company_details_answer_never_overwrites_the_typed_angle() -> None:
    answer = parse_company_details_answer(
        GOOD_COMPANY_DETAILS_ANSWER, typed_angle="My mom knows the CTO."
    )
    assert answer.angle == "My mom knows the CTO."


def test_parse_introduction_message_answer_requires_both_blocks() -> None:
    subject, message = parse_introduction_message_answer(GOOD_INTRODUCTION_ANSWER)
    assert subject == "Following up on your talent pool"
    assert "talent pool" in message


# --- End to end, through the real queue and FakeRunner -----------------------------------------


def test_extract_identity_populates_the_fields_without_writing_to_any_row(db_path: Path) -> None:
    """The wizard's "fields" stage (D-251's revised flow): runs against raw reviewed text, with
    no Open Application row to read from or write to yet - `open_application_id` is None."""
    queue = make_queue(db_path, FakeRunner(text=GOOD_COMPANY_DETAILS_ANSWER))
    conn = connect(db_path)
    job_id = submit_extract_open_application_identity(
        conn, queue, "Acme is a talent pool for data analysts."
    )
    conn.commit()
    run_all(queue)

    job = get_claude_job(conn, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.open_application_id is None
    assert count_open_applications(conn) == 0  # nothing was created

    exchange = prompt_exchange(conn, job_id, 0)
    assert exchange is not None
    answer = parse_open_application_identity_answer(exchange.result_text or "")
    assert answer.target_name == "Acme Talent Pool"
    assert answer.target_type == "talent_pool"
    assert answer.why_this_company == "They have a strong data team."


def test_build_open_application_identity_prompt_includes_the_text() -> None:
    prompt = build_open_application_identity_prompt("Acme is hiring data analysts.")
    assert "TASK: generate_open_application_company_details" in prompt
    assert "Acme is hiring data analysts." in prompt


def test_cv_is_not_ready_until_company_details_and_master_cv_exist(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    application_id = add_open_application(db_path, COMPANY_DETAILS_FIELDS)

    conn = connect(db_path)
    assert cv_ready(conn, application_id) is False  # no master CV, no profile documents yet

    try:
        submit_generate_cv(conn, queue, application_id)
        raised = False
    except OpenApplicationStepNotReady:
        raised = True
    assert raised


def test_cv_and_cover_letter_and_introduction_message_generate_end_to_end(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    application_id = add_open_application(db_path, COMPANY_DETAILS_FIELDS)
    add_profile_documents(db_path)
    add_master_cv(db_path, application_id)
    add_cover_letter_template(db_path)

    conn = connect(db_path)
    assert cv_ready(conn, application_id) is True
    assert introduction_message_ready(conn, application_id) is True

    queue.set_runner(FakeRunner(text=GOOD_CV_ANSWER))
    job_id = submit_generate_cv(conn, queue, application_id)
    run_all(queue)
    job = get_claude_job(conn, job_id)
    assert job is not None
    assert job.status == "done"
    assert latest_open_application_file_of_kind(conn, application_id, "tailored_cv") is not None
    # Regression guard (the real bug the user hit): the *sent* prompt must actually show the
    # model the EDIT/INSERT AFTER/REMOVE/ADD ROW AFTER block syntax, not just reference it by
    # name - FakeRunner's canned answer parses either way, so only reading the prompt itself
    # back catches a prompt that forgot to include it.
    cv_exchange = prompt_exchange(conn, job_id, 0)
    assert cv_exchange is not None
    assert "=== EDIT ===" in (cv_exchange.prompt_text or "")

    assert cover_letter_ready(conn, application_id) is True
    queue.set_runner(FakeRunner(text=GOOD_LETTER_ANSWER))
    job_id = submit_generate_cover_letter(conn, queue, application_id)
    run_all(queue)
    job = get_claude_job(conn, job_id)
    assert job is not None
    assert job.status == "done"
    assert latest_open_application_file_of_kind(conn, application_id, "cover_letter") is not None
    letter_exchange = prompt_exchange(conn, job_id, 0)
    assert letter_exchange is not None
    assert "=== EDIT ===" in (letter_exchange.prompt_text or "")

    queue.set_runner(FakeRunner(text=GOOD_INTRODUCTION_ANSWER))
    job_id = submit_generate_introduction_message(conn, queue, application_id)
    run_all(queue)
    job = get_claude_job(conn, job_id)
    assert job is not None
    assert job.status == "done"
    intro = latest_open_application_file_of_kind(conn, application_id, "introduction_message")
    assert intro is not None
    assert intro["subject"] == "Following up on your talent pool"


def test_cv_and_cover_letter_revise_prompts_include_the_edit_block_syntax(db_path: Path) -> None:
    """Same regression guard as the generate test above, for the shared revise prompt
    (`_build_docx_revise_prompt`), which had the identical bug."""
    queue = make_queue(db_path, FakeRunner(text=GOOD_CV_ANSWER))
    application_id = add_open_application(db_path, COMPANY_DETAILS_FIELDS)
    add_profile_documents(db_path)
    add_master_cv(db_path, application_id)
    add_cover_letter_template(db_path)

    conn = connect(db_path)
    submit_generate_cv(conn, queue, application_id)
    run_all(queue)
    queue.set_runner(FakeRunner(text=GOOD_LETTER_ANSWER))
    submit_generate_cover_letter(conn, queue, application_id)
    run_all(queue)

    queue.set_runner(FakeRunner(text=GOOD_CV_ANSWER))
    job_id = submit_open_application_revise_turn(
        conn, queue, application_id, "tailored_cv", "Reword the tagline"
    )
    run_all(queue)
    cv_exchange = prompt_exchange(conn, job_id, 0)
    assert cv_exchange is not None
    assert "=== EDIT ===" in (cv_exchange.prompt_text or "")

    queue.set_runner(FakeRunner(text=GOOD_LETTER_ANSWER))
    job_id = submit_open_application_revise_turn(
        conn, queue, application_id, "cover_letter", "Make the opening more direct"
    )
    run_all(queue)
    letter_exchange = prompt_exchange(conn, job_id, 0)
    assert letter_exchange is not None
    assert "=== EDIT ===" in (letter_exchange.prompt_text or "")


def test_revise_company_details_patches_one_field(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text=GOOD_COMPANY_DETAILS_ANSWER))
    application_id = add_open_application(db_path, COMPANY_DETAILS_FIELDS)

    conn = connect(db_path)
    queue.set_runner(
        FakeRunner(
            text="=== FIELD PATCH ===\n"
            "FIELD: WHY_THIS_COMPANY\n"
            "VALUE: They just raised a Series B.\n"
            "=== END FIELD PATCH ===\n"
        )
    )
    submit_open_application_revise_turn(
        conn, queue, application_id, "company_details", "Update why I'm applying"
    )
    run_all(queue)

    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.why_this_company == "They just raised a Series B."
    assert detail.target_name == "Acme Talent Pool"  # unmentioned fields stay as they were
