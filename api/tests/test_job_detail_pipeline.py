"""Tests for Job details, Positioning analysis and Application history's Claude Job kinds
(job-llm-steps.md §2-4, D-124 to D-128): verbatim-requirement validation, the weight/match score
formula, and Application history's deliberate exclusion of `notes`.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_applications import (
    insert_job_application,
    set_master_cv,
    update_job_application,
)
from llmjobtracker.job_files import list_job_files, store_job_file
from llmjobtracker.job_pipeline import (
    JobStepNotReady,
    RequirementScore,
    additional_files_block,
    application_history_ready,
    clear_positioning,
    compute_match_score,
    interview_prep_ready,
    job_details_ready,
    make_pipeline,
    parse_application_history_answer,
    parse_interview_prep_answer,
    parse_job_details_answer,
    parse_positioning_answer,
    positioning_ready,
    render_breakdown_document,
    scores_from_json,
    submit_generate_application_history,
    submit_generate_interview_prep,
    submit_generate_job_details,
    submit_generate_positioning,
)
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.profile_pipeline import store_output
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"

LISTING_TEXT = (
    "Senior Data Analyst at Acme Inc\n\n"
    "We're hiring a Senior Data Analyst.\n\n"
    "Requirements:\n"
    "- 4+ years in analytics\n"
    "- Strong SQL\n"
)

GOOD_JOB_DETAILS_ANSWER = """=== DESCRIPTION ===
Acme Inc is hiring a Senior Data Analyst to own reporting and dashboards.
=== END DESCRIPTION ===

=== REQUIREMENT ===
4+ years in analytics
=== END REQUIREMENT ===

=== REQUIREMENT ===
Strong SQL
=== END REQUIREMENT ===

=== WORK MODE ===
Remote
=== END WORK MODE ===

=== CONTRACT TYPE ===
Full-Time
=== END CONTRACT TYPE ===
"""

REQUIREMENTS = ["Strong SQL", "4+ years experience"]


def _requirement_block(number: int, weight: str, match: str, reasoning: str = "Reasoning.") -> str:
    return (
        f"=== REQUIREMENT ===\nNUMBER: {number}\nWEIGHT: {weight}\nMATCH: {match}\n"
        f"REASONING: {reasoning}\n=== END REQUIREMENT ==="
    )


_TAIL = (
    "\n\n=== FIT ===\n- bullet\n=== END FIT ===\n\n"
    "=== GAPS ===\n=== END GAPS ===\n\n"
    "=== JOB STRATEGY ===\nSome strategy.\n=== END JOB STRATEGY ===\n\n"
    "=== UNCLEAR ===\n=== END UNCLEAR ===\n"
)

GOOD_POSITIONING_ANSWER = (
    _requirement_block(
        1, "8", "9", "The career history shows five years of SQL-heavy analyst work."
    )
    + "\n\n"
    + _requirement_block(2, "6", "10", "The career history shows five years in analytics.")
    + "\n\n=== FIT ===\n- Strong SQL background\n=== END FIT ===\n\n"
    "=== GAPS ===\n- No stated experience with the specific BI tool\n=== END GAPS ===\n\n"
    "=== JOB STRATEGY ===\nLead with the SQL and reporting experience.\n"
    "=== END JOB STRATEGY ===\n\n"
    "=== UNCLEAR ===\n- Which BI tool the team actually uses\n=== END UNCLEAR ===\n"
)


def _qa_block(question: str, answer: str, score: int = 7) -> str:
    return f"=== QA ===\nQUESTION: {question}\nANSWER: {answer}\nSCORE: {score}\n=== END QA ==="


GOOD_INTERVIEW_PREP_ANSWER = "\n\n".join(
    _qa_block(f"Question {n}?", f"Answer {n}, grounded in the career history.", score=n)
    for n in range(10)
)


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


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


def add_listing(db_path: Path, app_id: int, text: str) -> None:
    conn = connect(db_path)
    try:
        store_job_file(
            conn,
            db_path.parent / "files",
            app_id,
            "listing",
            "Job Listing.txt",
            text.encode("utf-8"),
        )
    finally:
        conn.close()


def add_additional_file(db_path: Path, app_id: int, name: str, content: bytes) -> int:
    conn = connect(db_path)
    try:
        return store_job_file(conn, db_path.parent / "files", app_id, "other", name, content).id
    finally:
        conn.close()


def add_email(db_path: Path, app_id: int, subject: str, body: str) -> None:
    eml = (
        "From: recruiter@acme.example\r\n"
        "To: candidate@example.com\r\n"
        "Date: Mon, 10 Oct 2026 09:00:00 +0000\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        f"{body}\r\n"
    ).encode()
    conn = connect(db_path)
    try:
        store_job_file(conn, db_path.parent / "files", app_id, "eml", f"{subject}.eml", eml)
    finally:
        conn.close()


def fill_job_details(db_path: Path, app_id: int, requirements: list[str]) -> None:
    conn = connect(db_path)
    try:
        update_job_application(
            conn, app_id, {"description": "A role description.", "requirements": requirements}
        )
    finally:
        conn.close()


def add_profile_documents(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        store_output(
            conn,
            "full_cv_history",
            "# Career history\n\nAnalyst with five years of SQL-heavy work.",
            None,
            [],
            source="generated",
        )
        store_output(
            conn,
            "questionnaire_analysis",
            "# Questionnaire analysis\n\nStrong preference for data roles.",
            None,
            [],
            source="generated",
        )
        store_output(
            conn,
            "strategy",
            "# Strategy\n\nLead with SQL and reporting experience.",
            None,
            [],
            source="generated",
        )
        conn.commit()
    finally:
        conn.close()


def add_master_cv(db_path: Path, app_id: int) -> None:
    conn = connect(db_path)
    try:
        file_id = conn.execute(
            "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
            "VALUES ('master_cv', 'cv.pdf', 'profile/cv.pdf', 'abc', 10)"
        ).lastrowid
        set_master_cv(conn, app_id, file_id)
        conn.commit()
    finally:
        conn.close()


def make_positioning_ready(db_path: Path) -> int:
    app_id = add_application(db_path)
    add_listing(
        db_path, app_id, "Senior Data Analyst. Requirements: Strong SQL, 4+ years experience."
    )
    fill_job_details(db_path, app_id, REQUIREMENTS)
    add_profile_documents(db_path)
    add_master_cv(db_path, app_id)
    return app_id


def add_master_cv_with_text(db_path: Path, app_id: int, text: str) -> None:
    """Like `add_master_cv` above, but with real extracted text (D-167) - Interview
    preparation's own gate needs this, unlike Positioning analysis's, which never reads the
    Master CV's content."""
    conn = connect(db_path)
    try:
        file_id = conn.execute(
            "INSERT INTO profile_files "
            "(kind, original_name, stored_path, sha256, size_bytes, "
            "extraction_status, extracted_text) "
            "VALUES ('master_cv', 'cv.pdf', 'profile/cv.pdf', 'abc', 10, 'ok', ?)",
            (text,),
        ).lastrowid
        set_master_cv(conn, app_id, file_id)
        conn.commit()
    finally:
        conn.close()


def make_interview_prep_ready(db_path: Path) -> int:
    app_id = add_application(db_path)
    add_listing(
        db_path, app_id, "Senior Data Analyst. Requirements: Strong SQL, 4+ years experience."
    )
    fill_job_details(db_path, app_id, REQUIREMENTS)
    add_profile_documents(db_path)
    add_master_cv_with_text(db_path, app_id, "Jordan Doe - Senior Data Analyst, five years SQL.")
    return app_id


def _ready(db_path: Path, fn: object, app_id: int) -> bool:
    conn = connect(db_path)
    try:
        return bool(fn(conn, app_id))  # type: ignore[operator]
    finally:
        conn.close()


# --- Job details: parsing -----------------------------------------------------------------


def test_parse_job_details_answer_reads_description_requirements_and_fields() -> None:
    answer = parse_job_details_answer(GOOD_JOB_DETAILS_ANSWER, LISTING_TEXT)
    assert answer.description == (
        "Acme Inc is hiring a Senior Data Analyst to own reporting and dashboards."
    )
    assert answer.requirements == ["4+ years in analytics", "Strong SQL"]
    assert answer.work_mode == "Remote"
    assert answer.contract_type == "Full-Time"


def test_parse_job_details_answer_rejects_a_requirement_not_in_the_listing() -> None:
    bad = GOOD_JOB_DETAILS_ANSWER.replace("Strong SQL", "Expert in Rust programming")
    with pytest.raises(PromptRejected, match="does not appear in the listing"):
        parse_job_details_answer(bad, LISTING_TEXT)


def test_parse_job_details_answer_tolerates_typographic_quote_differences() -> None:
    """Live bug (2026-10-11): a real listing used a curly apostrophe ("You’ve shipped..."),
    and the model's otherwise-correct, faithful answer wrote the plain ASCII form ("You've
    shipped..."), failing the verbatim check twice in a row over typography, not wording."""
    listing = LISTING_TEXT + "- Production-level ML expertise: You’ve shipped models.\n"
    answer = GOOD_JOB_DETAILS_ANSWER.replace(
        "Strong SQL", "Production-level ML expertise: You've shipped models."
    )
    parsed = parse_job_details_answer(answer, listing)
    assert "Production-level ML expertise: You've shipped models." in parsed.requirements


def test_parse_job_details_answer_tolerates_a_pdf_line_wrapped_hyphen() -> None:
    """Live bug (2026-10-11): a real PDF's own line wrap split "scikit-learn" into
    "scikit-\\nlearn" (already stored before extraction.py's own dehyphenate fix existed), which
    failed the verbatim check against the model's natural, unbroken "scikit-learn"."""
    listing = LISTING_TEXT + "- ML frameworks (TensorFlow, PyTorch, scikit-\nlearn).\n"
    answer = GOOD_JOB_DETAILS_ANSWER.replace(
        "Strong SQL", "ML frameworks (TensorFlow, PyTorch, scikit-learn)."
    )
    parsed = parse_job_details_answer(answer, listing)
    assert "ML frameworks (TensorFlow, PyTorch, scikit-learn)." in parsed.requirements


def test_parse_job_details_answer_tolerates_a_pdf_accent_spacing_artifact() -> None:
    """Live bug (2026-10-12): a real French listing PDF's font encoding inserted a stray space on
    both sides of accented letters ("d é butez" for "débutez", "exp é rience" for "expérience"),
    which failed the verbatim check against the model's own, correctly-spelled French answer."""
    listing = (
        LISTING_TEXT
        + "- Vous d é butez votre parcours professionnel ou disposez de 0 à 2 ans\n"
        + "d'exp é rience dans un domaine technique.\n"
    )
    answer = GOOD_JOB_DETAILS_ANSWER.replace(
        "Strong SQL",
        "Vous débutez votre parcours professionnel ou disposez de 0 à 2 ans "
        "d'expérience dans un domaine technique.",
    )
    parsed = parse_job_details_answer(answer, listing)
    assert (
        "Vous débutez votre parcours professionnel ou disposez de 0 à 2 ans "
        "d'expérience dans un domaine technique."
    ) in parsed.requirements


def test_parse_job_details_answer_falls_back_to_unknown_for_a_bad_work_mode() -> None:
    bad = GOOD_JOB_DETAILS_ANSWER.replace("Remote", "Flexible")
    answer = parse_job_details_answer(bad, LISTING_TEXT)
    assert answer.work_mode == "Unknown"


def test_parse_job_details_answer_requires_a_description() -> None:
    text = "=== REQUIREMENT ===\n4+ years in analytics\n=== END REQUIREMENT ===\n"
    with pytest.raises(PromptRejected, match="DESCRIPTION"):
        parse_job_details_answer(text, LISTING_TEXT)


def test_parse_job_details_answer_requires_at_least_one_requirement() -> None:
    text = "=== DESCRIPTION ===\nSome description.\n=== END DESCRIPTION ===\n"
    with pytest.raises(PromptRejected, match="REQUIREMENT"):
        parse_job_details_answer(text, LISTING_TEXT)


# --- Positioning: parsing and scoring --------------------------------------------------------


def test_parse_positioning_answer_reads_scores_and_sections() -> None:
    answer = parse_positioning_answer(GOOD_POSITIONING_ANSWER, REQUIREMENTS)
    assert [score.text for score in answer.scores] == REQUIREMENTS
    assert answer.scores[0].weight == 8
    assert answer.scores[0].match == 9
    assert answer.fit == ["Strong SQL background"]
    assert answer.gaps == ["No stated experience with the specific BI tool"]
    assert answer.strategy == "Lead with the SQL and reporting experience."
    assert answer.unclear == ["Which BI tool the team actually uses"]


def test_parse_positioning_answer_tolerates_a_missing_end_requirement_tag() -> None:
    # Regression test: a real Claude Sonnet 5 run (2026-10-09, live-verified against the actual
    # CLI) returned otherwise well-formed REQUIREMENT blocks with no "=== END REQUIREMENT ==="
    # line at all - just a blank line before the next block. The synthetic GOOD_POSITIONING_ANSWER
    # above always included the tag, so this shape never hit the parser until live verification.
    text = (
        "=== REQUIREMENT ===\n"
        "NUMBER: 1\n"
        "WEIGHT: 8\n"
        "MATCH: 9\n"
        "REASONING: Five years of SQL-heavy analyst work.\n"
        "\n"
        "=== REQUIREMENT ===\n"
        "NUMBER: 2\n"
        "WEIGHT: 6\n"
        "MATCH: 10\n"
        "REASONING: Five years in analytics roles.\n"
        "\n"
        "=== FIT ===\n"
        "- Strong SQL background\n"
        "\n"
        "=== GAPS ===\n"
        "\n"
        "=== JOB STRATEGY ===\n"
        "Lead with SQL.\n"
        "\n"
        "=== UNCLEAR ===\n"
    )
    answer = parse_positioning_answer(text, REQUIREMENTS)
    assert [score.text for score in answer.scores] == REQUIREMENTS
    assert answer.scores[0].reasoning == "Five years of SQL-heavy analyst work."
    assert answer.scores[1].reasoning == "Five years in analytics roles."
    assert answer.fit == ["Strong SQL background"]
    assert answer.gaps == []
    assert answer.strategy == "Lead with SQL."
    assert answer.unclear == []


def test_parse_job_details_answer_tolerates_adjacent_blocks_with_no_end_tags() -> None:
    text = (
        "=== DESCRIPTION ===\n"
        "Acme Inc is hiring a Senior Data Analyst.\n"
        "=== REQUIREMENT ===\n"
        "4+ years in analytics\n"
        "=== REQUIREMENT ===\n"
        "Strong SQL\n"
        "=== WORK MODE ===\n"
        "Remote\n"
    )
    answer = parse_job_details_answer(text, LISTING_TEXT)
    assert answer.description == "Acme Inc is hiring a Senior Data Analyst."
    assert answer.requirements == ["4+ years in analytics", "Strong SQL"]
    assert answer.work_mode == "Remote"
    # No CONTRACT TYPE block at all, not even an empty one.
    assert answer.contract_type == "Unknown"


def test_compute_match_score_matches_a_hand_calculation() -> None:
    answer = parse_positioning_answer(GOOD_POSITIONING_ANSWER, REQUIREMENTS)
    # (8*9 + 6*10) / (10*(8+6)) * 100 = (72+60)/140*100 = 94.285714...
    assert compute_match_score(answer.scores) == pytest.approx(94.3, abs=0.05)


def test_parse_positioning_answer_rejects_a_missing_requirement() -> None:
    text = _requirement_block(1, "8", "9") + _TAIL
    with pytest.raises(PromptRejected, match="missing"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_an_out_of_range_number() -> None:
    text = (
        _requirement_block(1, "8", "9")
        + "\n\n"
        + _requirement_block(2, "6", "10")
        + "\n\n"
        + _requirement_block(3, "5", "5")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="not a valid requirement number"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_a_duplicate_number() -> None:
    # Regression guard for D-134: NUMBER identifies which stored requirement a block scores, so a
    # requirement's own text can no longer be reworded by the model - but a duplicate or missing
    # number is still a real answer-shape error and must still be caught. Every valid number (1
    # and 2) is present at least once, with an extra duplicate of 2 - neither "missing" nor "not a
    # valid requirement number" names anything, so the parser falls back to its generic message.
    text = (
        _requirement_block(1, "8", "9")
        + "\n\n"
        + _requirement_block(2, "6", "10")
        + "\n\n"
        + _requirement_block(2, "6", "10")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match=r"don't match the stored list \(a duplicate"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_a_non_integer_number() -> None:
    text = (
        "=== REQUIREMENT ===\nNUMBER: one\nWEIGHT: 8\nMATCH: 9\nREASONING: Reasoning.\n"
        "=== END REQUIREMENT ===\n\n" + _requirement_block(2, "6", "10") + _TAIL
    )
    with pytest.raises(PromptRejected, match="NUMBER is not an integer"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_an_out_of_range_score() -> None:
    text = _requirement_block(1, "11", "9") + "\n\n" + _requirement_block(2, "6", "10") + _TAIL
    with pytest.raises(PromptRejected, match="out of range"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_a_non_numeric_score() -> None:
    text = _requirement_block(1, "high", "9") + "\n\n" + _requirement_block(2, "6", "10") + _TAIL
    with pytest.raises(PromptRejected, match="not a number"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_all_zero_weights() -> None:
    text = _requirement_block(1, "0", "9") + "\n\n" + _requirement_block(2, "0", "10") + _TAIL
    with pytest.raises(PromptRejected, match="weight of 0"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_requires_a_job_strategy_block() -> None:
    text = (
        _requirement_block(1, "8", "9")
        + "\n\n"
        + _requirement_block(2, "6", "10")
        + "\n\n=== FIT ===\n=== END FIT ===\n\n=== GAPS ===\n=== END GAPS ===\n\n"
        "=== UNCLEAR ===\n=== END UNCLEAR ===\n"
    )
    with pytest.raises(PromptRejected, match="JOB STRATEGY"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_render_breakdown_document_builds_a_table_with_pipes_escaped() -> None:
    scores = [RequirementScore(text="A | B", weight=8, match=9, reasoning="Has a | pipe")]
    document = render_breakdown_document(scores, 90.0)
    assert "Match score: 90.0%" in document
    assert "A \\| B" in document
    assert "Has a \\| pipe" in document


# --- Application history: parsing ------------------------------------------------------------


def test_parse_application_history_answer_reads_all_three_fields() -> None:
    text = (
        "=== NOTES ===\nThe recruiter confirmed a phone screen next week.\n=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\nPrepare for the phone screen\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\n2026-10-20\n=== END DUE DATE ===\n"
    )
    answer = parse_application_history_answer(text)
    assert answer.notes == "The recruiter confirmed a phone screen next week."
    assert answer.next_action == "Prepare for the phone screen"
    assert answer.due_date == "2026-10-20"


def test_parse_application_history_answer_allows_empty_next_action_and_due_date() -> None:
    text = (
        "=== NOTES ===\nNothing new.\n=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\n=== END DUE DATE ===\n"
    )
    answer = parse_application_history_answer(text)
    assert answer.next_action is None
    assert answer.due_date is None


def test_parse_application_history_answer_drops_an_unparsable_due_date() -> None:
    text = (
        "=== NOTES ===\nSome notes.\n=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\nnext Friday\n=== END DUE DATE ===\n"
    )
    assert parse_application_history_answer(text).due_date is None


def test_parse_application_history_answer_requires_notes() -> None:
    text = (
        "=== NEXT ACTION ===\n=== END NEXT ACTION ===\n\n=== DUE DATE ===\n=== END DUE DATE ===\n"
    )
    with pytest.raises(PromptRejected, match="NOTES"):
        parse_application_history_answer(text)


# --- Gates (D-128) ----------------------------------------------------------------------------


def test_job_details_ready_requires_a_readable_listing(db_path: Path) -> None:
    app_id = add_application(db_path)
    assert not _ready(db_path, job_details_ready, app_id)
    add_listing(db_path, app_id, LISTING_TEXT)
    assert _ready(db_path, job_details_ready, app_id)


def test_positioning_ready_requires_every_input(db_path: Path) -> None:
    app_id = add_application(db_path)
    assert not _ready(db_path, positioning_ready, app_id)
    add_listing(db_path, app_id, "Senior Data Analyst. Requirements: Strong SQL.")
    fill_job_details(db_path, app_id, ["Strong SQL"])
    assert not _ready(db_path, positioning_ready, app_id)  # no profile docs or Master CV yet
    add_profile_documents(db_path)
    assert not _ready(db_path, positioning_ready, app_id)  # still no Master CV
    add_master_cv(db_path, app_id)
    assert _ready(db_path, positioning_ready, app_id)


def test_application_history_ready_requires_job_details(db_path: Path) -> None:
    app_id = add_application(db_path)
    assert not _ready(db_path, application_history_ready, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    assert _ready(db_path, application_history_ready, app_id)


# --- Job details: end to end --------------------------------------------------------------


def test_generate_job_details_end_to_end(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id, LISTING_TEXT)
    queue = make_queue(db_path, FakeRunner(text=GOOD_JOB_DETAILS_ANSWER))
    conn = connect(db_path)
    try:
        job_id = submit_generate_job_details(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        row = conn.execute(
            "SELECT description, requirements, work_mode, contract_type "
            "FROM job_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert row["description"] == (
            "Acme Inc is hiring a Senior Data Analyst to own reporting and dashboards."
        )
        assert json.loads(row["requirements"]) == ["4+ years in analytics", "Strong SQL"]
        assert row["work_mode"] == "Remote"
        assert row["contract_type"] == "Full-Time"
    finally:
        conn.close()


def test_generate_job_details_fails_the_job_on_a_fabricated_requirement(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id, LISTING_TEXT)
    bad_answer = GOOD_JOB_DETAILS_ANSWER.replace("Strong SQL", "Expert in Rust programming")
    queue = make_queue(db_path, FakeRunner(text=bad_answer))
    conn = connect(db_path)
    try:
        job_id = submit_generate_job_details(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "does not appear in the listing" in (job.error or "")
        row = conn.execute(
            "SELECT description FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["description"] is None
    finally:
        conn.close()


def test_submit_generate_job_details_rejects_when_not_ready(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_job_details(conn, queue, app_id)
    finally:
        conn.close()


# --- Positioning: end to end ---------------------------------------------------------------


def test_generate_positioning_end_to_end_computes_and_stores_the_score(db_path: Path) -> None:
    app_id = make_positioning_ready(db_path)
    queue = make_queue(db_path, FakeRunner(text=GOOD_POSITIONING_ANSWER))
    conn = connect(db_path)
    try:
        job_id = submit_generate_positioning(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        row = conn.execute(
            "SELECT fit, gaps, strategy, unclear, match_score, positioning_scores "
            "FROM job_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert json.loads(row["fit"]) == ["Strong SQL background"]
        assert row["strategy"] == "Lead with the SQL and reporting experience."
        assert row["match_score"] == pytest.approx(94.3, abs=0.05)
        scores = scores_from_json(row["positioning_scores"])
        assert [s.text for s in scores] == REQUIREMENTS
        assert scores[0].weight == 8
        files = list_job_files(conn, app_id)
        breakdown = [f for f in files if f["kind"] == "positioning_breakdown"]
        assert len(breakdown) == 1
        assert breakdown[0]["name"] == "Positioning breakdown.md"
    finally:
        conn.close()


def test_clear_positioning_resets_the_score_and_removes_the_breakdown_file(
    db_path: Path,
) -> None:
    app_id = make_positioning_ready(db_path)
    queue = make_queue(db_path, FakeRunner(text=GOOD_POSITIONING_ANSWER))
    conn = connect(db_path)
    try:
        job_id = submit_generate_positioning(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    files_root = db_path.parent / "files"
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None and job.status == "done"
        breakdown_path = files_root / str(
            [f for f in list_job_files(conn, app_id) if f["kind"] == "positioning_breakdown"][0][
                "stored_path"
            ]
        )
        assert breakdown_path.exists()

        detail = clear_positioning(conn, files_root, app_id)

        assert detail is not None
        assert detail.fit == []
        assert detail.gaps == []
        assert detail.strategy is None
        assert detail.unclear == []
        assert detail.match_score is None
        row = conn.execute(
            "SELECT positioning_scores FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert json.loads(row["positioning_scores"]) == []
        assert [
            f for f in list_job_files(conn, app_id) if f["kind"] == "positioning_breakdown"
        ] == []
        assert not breakdown_path.exists()
    finally:
        conn.close()


def test_clear_positioning_of_an_unknown_application_returns_none(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        assert clear_positioning(conn, db_path.parent / "files", 999) is None
    finally:
        conn.close()


def test_generate_positioning_fails_the_job_when_requirement_numbers_dont_match(
    db_path: Path,
) -> None:
    app_id = make_positioning_ready(db_path)
    bad_answer = GOOD_POSITIONING_ANSWER.replace("NUMBER: 2", "NUMBER: 1")
    queue = make_queue(db_path, FakeRunner(text=bad_answer))
    conn = connect(db_path)
    try:
        job_id = submit_generate_positioning(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        row = conn.execute(
            "SELECT match_score FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["match_score"] is None
    finally:
        conn.close()


def test_submit_generate_positioning_rejects_when_not_ready(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_positioning(conn, queue, app_id)
    finally:
        conn.close()


# --- Application history: end to end --------------------------------------------------------


def test_generate_application_history_end_to_end_writes_notes_too(
    db_path: Path,
) -> None:
    """D-177 supersedes D-127: notes is now written by this step, from the status history plus
    whatever the filed emails add."""
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    add_email(
        db_path,
        app_id,
        "Phone screen scheduled",
        "We'd like to schedule a phone screen for Oct 20, 2026.",
    )
    answer_text = (
        "=== NOTES ===\nIdentified, then the recruiter scheduled a phone screen for Oct 20."
        "\n=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\nPrepare for the phone screen\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\n2026-10-20\n=== END DUE DATE ===\n"
    )
    runner = FakeRunner(text=answer_text)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_generate_application_history(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    assert "Phone screen scheduled" in runner.prompts[0]
    assert "We'd like to schedule a phone screen" in runner.prompts[0]
    assert "Identified" in runner.prompts[0]  # the status history block

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        row = conn.execute(
            "SELECT notes, next_action, due_date FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["notes"] == "Identified, then the recruiter scheduled a phone screen for Oct 20."
        assert row["next_action"] == "Prepare for the phone screen"
        assert row["due_date"] == "2026-10-20"
    finally:
        conn.close()


def test_generate_application_history_reads_additional_files_too(db_path: Path) -> None:
    """D-262: a Job Application's own Additional files are extracted at upload time and read by
    this step the same way filed emails already are."""
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    add_additional_file(db_path, app_id, "notes.txt", b"Recruiter mentioned a start date of Nov 3.")
    answer_text = (
        "=== NOTES ===\nIdentified; the recruiter mentioned a Nov 3 start date.\n"
        "=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\n=== END DUE DATE ===\n"
    )
    runner = FakeRunner(text=answer_text)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        submit_generate_application_history(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    assert "Recruiter mentioned a start date of Nov 3." in runner.prompts[0]


def test_additional_files_block_truncates_an_oversized_file(db_path: Path) -> None:
    app_id = add_application(db_path)
    long_text = "Filler. " * 10_000  # well over _MAX_ADDITIONAL_FILE_CHARS
    add_additional_file(db_path, app_id, "big.txt", long_text.encode())

    conn = connect(db_path)
    try:
        block = additional_files_block(conn, app_id)
    finally:
        conn.close()

    assert "truncated" in block
    assert len(block) < len(long_text)


def test_additional_files_block_excludes_the_given_ids(db_path: Path) -> None:
    app_id = add_application(db_path)
    excluded_id = add_additional_file(db_path, app_id, "a.txt", b"Content A.")
    add_additional_file(db_path, app_id, "b.txt", b"Content B.")

    conn = connect(db_path)
    try:
        block = additional_files_block(conn, app_id, frozenset({excluded_id}))
    finally:
        conn.close()

    assert "Content A." not in block
    assert "Content B." in block


def test_generate_application_history_leaves_next_action_and_due_date_untouched_when_empty(
    db_path: Path,
) -> None:
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    conn = connect(db_path)
    try:
        update_job_application(
            conn, app_id, {"next_action": "Follow up Friday", "due_date": "2026-10-15"}
        )
    finally:
        conn.close()
    answer_text = (
        "=== NOTES ===\nNothing new from the emails.\n=== END NOTES ===\n\n"
        "=== NEXT ACTION ===\n=== END NEXT ACTION ===\n\n"
        "=== DUE DATE ===\n=== END DUE DATE ===\n"
    )
    queue = make_queue(db_path, FakeRunner(text=answer_text))
    conn = connect(db_path)
    try:
        submit_generate_application_history(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT notes, next_action, due_date FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["notes"] == "Nothing new from the emails."  # notes always replaces, D-177
        assert row["next_action"] == "Follow up Friday"
        assert row["due_date"] == "2026-10-15"
    finally:
        conn.close()


def test_submit_generate_application_history_rejects_when_not_ready(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_application_history(conn, queue, app_id)
    finally:
        conn.close()


# --- Interview preparation: end to end ------------------------------------------------------


def test_parse_interview_prep_answer_reads_ten_pairs() -> None:
    pairs = parse_interview_prep_answer(GOOD_INTERVIEW_PREP_ANSWER)
    assert len(pairs) == 10
    assert pairs[0].question == "Question 0?"
    assert pairs[0].answer == "Answer 0, grounded in the career history."
    assert pairs[0].score == 0
    assert pairs[9].score == 9


def test_parse_interview_prep_answer_rejects_an_out_of_range_score() -> None:
    bad_answer = GOOD_INTERVIEW_PREP_ANSWER.replace("SCORE: 0", "SCORE: 11")
    with pytest.raises(PromptRejected, match="out of range 0-10"):
        parse_interview_prep_answer(bad_answer)


def test_parse_interview_prep_answer_rejects_a_non_numeric_score() -> None:
    bad_answer = GOOD_INTERVIEW_PREP_ANSWER.replace("SCORE: 0", "SCORE: strong")
    with pytest.raises(PromptRejected, match="not a whole number"):
        parse_interview_prep_answer(bad_answer)


def test_parse_interview_prep_answer_rejects_fewer_than_ten_pairs() -> None:
    short_answer = "\n\n".join(GOOD_INTERVIEW_PREP_ANSWER.split("\n\n")[:-1])
    with pytest.raises(PromptRejected, match="exactly ten"):
        parse_interview_prep_answer(short_answer)


def test_parse_interview_prep_answer_rejects_an_empty_answer_field() -> None:
    bad_answer = GOOD_INTERVIEW_PREP_ANSWER.replace(
        "ANSWER: Answer 0, grounded in the career history.", "ANSWER:"
    )
    with pytest.raises(PromptRejected, match="QUESTION or ANSWER"):
        parse_interview_prep_answer(bad_answer)


def test_interview_prep_ready_requires_readable_master_cv_text(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(
        db_path, app_id, "Senior Data Analyst. Requirements: Strong SQL, 4+ years experience."
    )
    fill_job_details(db_path, app_id, REQUIREMENTS)
    add_profile_documents(db_path)
    assert not _ready(db_path, interview_prep_ready, app_id)  # still no Master CV
    # Positioning analysis's own gate is satisfied by a Master CV with no readable text - but
    # interview_prep_ready is the same function (D-167), so this is the same "not ready" case.
    add_master_cv(db_path, app_id)
    assert _ready(db_path, interview_prep_ready, app_id)


def test_generate_interview_prep_end_to_end_stores_ten_pairs(db_path: Path) -> None:
    app_id = make_interview_prep_ready(db_path)
    runner = FakeRunner(text=GOOD_INTERVIEW_PREP_ANSWER)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_generate_interview_prep(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    assert "Jordan Doe - Senior Data Analyst" in runner.prompts[0]

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        row = conn.execute(
            "SELECT interview_prep FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        pairs = json.loads(row["interview_prep"])
        assert len(pairs) == 10
        assert pairs[0] == {
            "question": "Question 0?",
            "answer": "Answer 0, grounded in the career history.",
            "score": 0,
        }
    finally:
        conn.close()


def test_generate_interview_prep_fails_the_job_on_fewer_than_ten_pairs(db_path: Path) -> None:
    app_id = make_interview_prep_ready(db_path)
    short_answer = "\n\n".join(GOOD_INTERVIEW_PREP_ANSWER.split("\n\n")[:-1])
    queue = make_queue(db_path, FakeRunner(text=short_answer))
    conn = connect(db_path)
    try:
        job_id = submit_generate_interview_prep(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        row = conn.execute(
            "SELECT interview_prep FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["interview_prep"] == "[]"
    finally:
        conn.close()


def test_submit_generate_interview_prep_rejects_when_not_ready(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(JobStepNotReady):
            submit_generate_interview_prep(conn, queue, app_id)
    finally:
        conn.close()


# --- Routes -------------------------------------------------------------------------------


def test_job_details_route_201_when_ready_400_when_not(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        app_id = add_application(db_path)
        assert client.post(f"/job-applications/{app_id}/job-details/generate").status_code == 400
        add_listing(db_path, app_id, LISTING_TEXT)
        response = client.post(f"/job-applications/{app_id}/job-details/generate")
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_job_details"


def test_job_details_route_for_unknown_application_is_not_found(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.post("/job-applications/999/job-details/generate").status_code == 404


def test_positioning_route_201_when_ready_400_when_not(db_path: Path) -> None:
    app_id = add_application(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.post(f"/job-applications/{app_id}/positioning/generate").status_code == 400

    ready_id = make_positioning_ready(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post(f"/job-applications/{ready_id}/positioning/generate")
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_positioning"


def test_clear_positioning_route_resets_the_application(db_path: Path) -> None:
    app_id = make_positioning_ready(db_path)
    queue = make_queue(db_path, FakeRunner(text=GOOD_POSITIONING_ANSWER))
    conn = connect(db_path)
    try:
        submit_generate_positioning(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post(f"/job-applications/{app_id}/positioning/clear")

    assert response.status_code == 200
    body = response.json()
    assert body["fit"] == []
    assert body["match_score"] is None
    assert [f for f in body["files"] if f["kind"] == "positioning_breakdown"] == []


def test_clear_positioning_route_for_unknown_application_is_not_found(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.post("/job-applications/999/positioning/clear").status_code == 404


def test_application_history_route_201_when_ready_400_when_not(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        app_id = add_application(db_path)
        route = f"/job-applications/{app_id}/application-history/generate"
        assert client.post(route).status_code == 400
        fill_job_details(db_path, app_id, ["Strong SQL"])
        response = client.post(route)
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_application_history"


def test_interview_prep_route_201_when_ready_400_when_not(db_path: Path) -> None:
    app_id = add_application(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.post(f"/job-applications/{app_id}/interview-prep/generate").status_code == 400

    ready_id = make_interview_prep_ready(db_path)
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post(f"/job-applications/{ready_id}/interview-prep/generate")
        assert response.status_code == 201
        assert response.json()["kind"] == "generate_interview_prep"
