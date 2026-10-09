"""Tests for Job details, Positioning analysis and Application history's Claude Job kinds
(job-llm-steps.md §2-4, D-124 to D-128): verbatim-requirement validation, the weight/match score
formula, and Application history's deliberate exclusion of `notes`.
"""

import json
from pathlib import Path

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
from localjobtracker.job_files import list_job_files, store_job_file
from localjobtracker.job_pipeline import (
    JobStepNotReady,
    RequirementScore,
    application_history_ready,
    compute_match_score,
    job_details_ready,
    make_pipeline,
    parse_application_history_answer,
    parse_job_details_answer,
    parse_positioning_answer,
    positioning_ready,
    render_breakdown_document,
    submit_generate_application_history,
    submit_generate_job_details,
    submit_generate_positioning,
)
from localjobtracker.profile_pipeline import store_output
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

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


def _requirement_block(text: str, weight: str, match: str, reasoning: str = "Reasoning.") -> str:
    return (
        f"=== REQUIREMENT ===\nTEXT: {text}\nWEIGHT: {weight}\nMATCH: {match}\n"
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
        "Strong SQL", "8", "9", "The career history shows five years of SQL-heavy analyst work."
    )
    + "\n\n"
    + _requirement_block(
        "4+ years experience", "6", "10", "The career history shows five years in analytics."
    )
    + "\n\n=== FIT ===\n- Strong SQL background\n=== END FIT ===\n\n"
    "=== GAPS ===\n- No stated experience with the specific BI tool\n=== END GAPS ===\n\n"
    "=== JOB STRATEGY ===\nLead with the SQL and reporting experience.\n"
    "=== END JOB STRATEGY ===\n\n"
    "=== UNCLEAR ===\n- Which BI tool the team actually uses\n=== END UNCLEAR ===\n"
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
        "TEXT: Strong SQL\n"
        "WEIGHT: 8\n"
        "MATCH: 9\n"
        "REASONING: Five years of SQL-heavy analyst work.\n"
        "\n"
        "=== REQUIREMENT ===\n"
        "TEXT: 4+ years experience\n"
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
    text = _requirement_block("Strong SQL", "8", "9") + _TAIL
    with pytest.raises(PromptRejected, match="missing"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_an_extra_requirement() -> None:
    text = (
        _requirement_block("Strong SQL", "8", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "6", "10")
        + "\n\n"
        + _requirement_block("Knows Rust", "5", "5")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="not a real requirement"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_a_reworded_requirement() -> None:
    text = (
        _requirement_block("Strong SQL skills", "8", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "6", "10")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="don't match the stored list"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_an_out_of_range_score() -> None:
    text = (
        _requirement_block("Strong SQL", "11", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "6", "10")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="out of range"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_a_non_numeric_score() -> None:
    text = (
        _requirement_block("Strong SQL", "high", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "6", "10")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="not a number"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_rejects_all_zero_weights() -> None:
    text = (
        _requirement_block("Strong SQL", "0", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "0", "10")
        + _TAIL
    )
    with pytest.raises(PromptRejected, match="weight of 0"):
        parse_positioning_answer(text, REQUIREMENTS)


def test_parse_positioning_answer_requires_a_job_strategy_block() -> None:
    text = (
        _requirement_block("Strong SQL", "8", "9")
        + "\n\n"
        + _requirement_block("4+ years experience", "6", "10")
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
            "SELECT fit, gaps, strategy, unclear, match_score FROM job_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        assert json.loads(row["fit"]) == ["Strong SQL background"]
        assert row["strategy"] == "Lead with the SQL and reporting experience."
        assert row["match_score"] == pytest.approx(94.3, abs=0.05)
        files = list_job_files(conn, app_id)
        breakdown = [f for f in files if f["kind"] == "positioning_breakdown"]
        assert len(breakdown) == 1
        assert breakdown[0]["name"] == "Positioning breakdown.md"
    finally:
        conn.close()


def test_generate_positioning_fails_the_job_when_requirements_dont_match(db_path: Path) -> None:
    app_id = make_positioning_ready(db_path)
    bad_answer = GOOD_POSITIONING_ANSWER.replace("Strong SQL", "Strong SQL skills")
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


def test_generate_application_history_end_to_end_reads_the_email_but_never_writes_notes(
    db_path: Path,
) -> None:
    app_id = add_application(db_path)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    add_email(
        db_path,
        app_id,
        "Phone screen scheduled",
        "We'd like to schedule a phone screen for Oct 20, 2026.",
    )
    answer_text = (
        "=== NOTES ===\nThe recruiter scheduled a phone screen for Oct 20.\n=== END NOTES ===\n\n"
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

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        row = conn.execute(
            "SELECT notes, next_action, due_date FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
        assert row["notes"] is None  # D-127: never written, regardless of the answer's NOTES
        assert row["next_action"] == "Prepare for the phone screen"
        assert row["due_date"] == "2026-10-20"
    finally:
        conn.close()


def test_generate_application_history_leaves_existing_fields_untouched_when_answer_is_empty(
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
            "SELECT next_action, due_date FROM job_applications WHERE id = ?", (app_id,)
        ).fetchone()
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
