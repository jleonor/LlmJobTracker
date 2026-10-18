"""Tests for the lane Claude Jobs (Agent/specs/lane-steps.md, D-214): extract_lanes, the Lanes
section's "Sync from strategy" action, and assign_job_lane, the per-application step behind the
one-off reassignment pass (D-217).
"""

import json
from pathlib import Path

import pytest

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file
from llmjobtracker.job_pipeline import make_pipeline
from llmjobtracker.lane_pipeline import (
    JOB_KIND_ANALYZE_LANE,
    JOB_KIND_ASSIGN_LANE,
    JOB_KIND_EXTRACT_LANES,
    JOB_KIND_SUMMARIZE_LANES,
    LaneAnalysisNotReady,
    LaneAssignmentNotReady,
    LaneOverviewNotReady,
    LaneSyncNotReady,
    build_analyze_lane_prompt,
    build_assign_lane_prompt,
    build_extract_lanes_prompt,
    build_summarize_lanes_prompt,
    lane_analysis_ready,
    lane_overview_ready,
    parse_analyze_lane_answer,
    parse_lanes_answer,
    parse_summarize_lanes_answer,
    scored_applications_for_lane,
    submit_analyze_lane,
    submit_assign_job_lane,
    submit_extract_lanes,
    submit_summarize_lanes,
)
from llmjobtracker.lanes import (
    create_lane,
    ensure_other_lane,
    get_lane,
    get_lane_overview,
    list_lanes,
)
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

GOOD_LANES_ANSWER = """=== LANE ===
NAME: Data Analytics
DESCRIPTION: Reporting, dashboards and analytics automation roles.
REASONING: Matches the BI and reporting work in the career history.
=== END LANE ===

=== LANE ===
NAME: Product Analytics
DESCRIPTION: Analytics embedded in a product team, closer to the roadmap.
REASONING: Builds on the same SQL/Python skills in a more product-facing context.
=== END LANE ==="""


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, db_path.parent / "files")
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def write_strategy(db_path: Path, text: str = "Lead with data work.") -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_outputs (kind, version, document, input_sha256s) "
            "VALUES ('strategy', 1, ?, '[]')",
            (text,),
        )
        conn.commit()
    finally:
        conn.close()


def write_career_history(db_path: Path, text: str = "Ten years in data analytics.") -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_outputs (kind, version, document, input_sha256s) "
            "VALUES ('full_cv_history', 1, ?, '[]')",
            (text,),
        )
        conn.commit()
    finally:
        conn.close()


# --- ensure_other_lane (D-219) ---------------------------------------------------------------


def test_ensure_other_lane_adds_it_when_missing(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM lanes")  # migration 29 already seeded it - remove it first
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        ensure_other_lane(conn)
        lanes = list_lanes(conn)
    finally:
        conn.close()
    assert [lane.name for lane in lanes] == ["Data Analytics", "Other"]
    assert lanes[1].description == "Roles that don't clearly fit any of the lanes above."


def test_ensure_other_lane_is_a_no_op_once_present(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM lanes")  # migration 29's own "Other" would also match
        create_lane(conn, "other", None, None)  # lowercase - matched case-insensitively
        conn.commit()
        ensure_other_lane(conn)
        lanes = list_lanes(conn)
    finally:
        conn.close()
    assert [lane.name for lane in lanes] == ["other"]


# --- Prompt building and answer parsing (no queue involved) ---------------------------------


def test_build_extract_lanes_prompt_includes_the_task_and_the_strategy(db_path: Path) -> None:
    write_strategy(db_path, "Lead with the data work.")
    conn = connect(db_path)
    try:
        prompt = build_extract_lanes_prompt(conn)
    finally:
        conn.close()
    assert "TASK: extract_lanes" in prompt
    assert "=== STRATEGY ===" in prompt
    assert "Lead with the data work." in prompt


def test_build_extract_lanes_prompt_instructs_to_include_every_lane_group(db_path: Path) -> None:
    """D-220/D-221: the strategy document groups lanes into main/secondary/tertiary - a tertiary
    lane was being silently dropped from the catalog. The prompt now says explicitly to include
    all three groups, and that tertiary lanes are not lanes to avoid."""
    write_strategy(db_path)
    conn = connect(db_path)
    try:
        prompt = build_extract_lanes_prompt(conn)
    finally:
        conn.close()
    normalized = " ".join(prompt.split())
    assert "main lanes" in normalized
    assert "secondary lanes" in normalized
    assert "tertiary lanes" in normalized
    assert "not lanes to avoid" in normalized
    assert "Include every lane from all three groups" in normalized


def test_build_extract_lanes_prompt_requires_a_strategy_document(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="STRATEGY"):
            build_extract_lanes_prompt(conn)
    finally:
        conn.close()


def test_parse_lanes_answer_reads_multiple_lanes() -> None:
    lanes = parse_lanes_answer(GOOD_LANES_ANSWER)
    assert [lane.name for lane in lanes] == ["Data Analytics", "Product Analytics"]
    assert lanes[0].description == "Reporting, dashboards and analytics automation roles."
    assert lanes[0].reasoning == "Matches the BI and reporting work in the career history."


def test_parse_lanes_answer_tolerates_a_missing_description_or_reasoning() -> None:
    text = "=== LANE ===\nNAME: Data Analytics\nDESCRIPTION: \nREASONING: \n=== END LANE ==="
    lanes = parse_lanes_answer(text)
    assert len(lanes) == 1
    assert lanes[0].name == "Data Analytics"
    assert lanes[0].description == ""
    assert lanes[0].reasoning == ""


def test_parse_lanes_answer_rejects_an_answer_with_no_lane_blocks() -> None:
    with pytest.raises(PromptRejected, match="any lanes"):
        parse_lanes_answer("I could not find any lanes in this document.")


# --- The extract_lanes job ---------------------------------------------------------------------


def test_submit_extract_lanes_requires_a_strategy_document(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text="unused"))
    conn = connect(db_path)
    try:
        with pytest.raises(LaneSyncNotReady):
            submit_extract_lanes(conn, queue)
    finally:
        conn.close()


def test_extract_lanes_job_replaces_the_stored_lanes(db_path: Path) -> None:
    write_strategy(db_path)
    conn = connect(db_path)
    try:
        create_lane(conn, "Old Lane", "stale", "stale")
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text=GOOD_LANES_ANSWER)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_extract_lanes(conn, queue)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.prompts[0].prompt_kind == JOB_KIND_EXTRACT_LANES
        lanes = list_lanes(conn)
    finally:
        conn.close()
    # The Other lane (D-219) is always re-added after a full catalog replace.
    assert [lane.name for lane in lanes] == ["Data Analytics", "Product Analytics", "Other"]
    assert [lane.position for lane in lanes] == [0, 1, 2]


def test_extract_lanes_job_with_no_lane_blocks_leaves_existing_lanes_untouched(
    db_path: Path,
) -> None:
    write_strategy(db_path)
    conn = connect(db_path)
    try:
        create_lane(conn, "Existing Lane", "kept", "kept")
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text="I could not find any lanes in this document.")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_extract_lanes(conn, queue)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "failed"
        lanes = list_lanes(conn)
    finally:
        conn.close()
    # "Other" is migration 29's own seed; the rejected answer leaves everything untouched.
    assert [lane.name for lane in lanes] == ["Other", "Existing Lane"]


def test_extract_lanes_job_does_not_duplicate_an_other_lane_the_model_already_wrote(
    db_path: Path,
) -> None:
    write_strategy(db_path)
    answer = (
        "=== LANE ===\n"
        "NAME: Data Analytics\n"
        "DESCRIPTION: Reporting roles.\n"
        "REASONING: x\n"
        "=== END LANE ===\n\n"
        "=== LANE ===\n"
        "NAME: other\n"
        "DESCRIPTION: Everything else.\n"
        "REASONING: x\n"
        "=== END LANE ==="
    )
    queue = make_queue(db_path, FakeRunner(text=answer))
    conn = connect(db_path)
    try:
        job_id = submit_extract_lanes(conn, queue)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        assert get_claude_job(conn, job_id).status == "done"  # type: ignore[union-attr]
        lanes = list_lanes(conn)
    finally:
        conn.close()
    # Matched case-insensitively against the model's own "other" - no second row added.
    assert [lane.name for lane in lanes] == ["Data Analytics", "other"]


# --- assign_job_lane (D-217's one-off reassignment pass) ---------------------------------------


def add_application_with_listing(db_path: Path, listing_text: str) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            extracted_text=listing_text,
        )
        conn.commit()
    finally:
        conn.close()
    return app_id


def test_build_assign_lane_prompt_includes_the_listing_and_catalog(db_path: Path) -> None:
    app_id = add_application_with_listing(db_path, "Senior Data Analyst, must know SQL.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", "Reporting roles.", None)
        conn.commit()
        prompt = build_assign_lane_prompt(conn, app_id)
    finally:
        conn.close()
    assert "TASK: assign_job_lane" in prompt
    assert "Senior Data Analyst, must know SQL." in prompt
    assert "Data Analytics: Reporting roles." in prompt


def test_build_assign_lane_prompt_rejects_a_listing_with_no_text(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            extracted_text=None,
        )
        conn.commit()
        with pytest.raises(PromptRejected, match="no readable text"):
            build_assign_lane_prompt(conn, app_id)
    finally:
        conn.close()


def test_submit_assign_job_lane_requires_a_listing_file(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text="unused"))
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        conn.commit()
        with pytest.raises(LaneAssignmentNotReady):
            submit_assign_job_lane(conn, queue, app_id)
    finally:
        conn.close()


def test_assign_job_lane_job_writes_the_matched_lane(db_path: Path) -> None:
    app_id = add_application_with_listing(db_path, "Senior Data Analyst, must know SQL.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        create_lane(conn, "Product Analytics", None, None)
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text="=== LANE ===\nData Analytics\n=== END LANE ===")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_assign_job_lane(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.prompts[0].prompt_kind == JOB_KIND_ASSIGN_LANE
        row = conn.execute("SELECT lane FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    assert row["lane"] == "Data Analytics"


def test_assign_job_lane_job_matches_case_insensitively_to_the_catalogs_own_casing(
    db_path: Path,
) -> None:
    app_id = add_application_with_listing(db_path, "Senior Data Analyst, must know SQL.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text="=== LANE ===\ndata analytics\n=== END LANE ===")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_assign_job_lane(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        assert get_claude_job(conn, job_id).status == "done"  # type: ignore[union-attr]
        row = conn.execute("SELECT lane FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    assert row["lane"] == "Data Analytics"


def test_assign_job_lane_job_clears_lane_for_an_unmatched_answer(db_path: Path) -> None:
    app_id = add_application_with_listing(db_path, "Senior Data Analyst, must know SQL.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Product Analytics", None, None)
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text="=== LANE ===\nUnknown\n=== END LANE ===")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_assign_job_lane(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        assert get_claude_job(conn, job_id).status == "done"  # type: ignore[union-attr]
        row = conn.execute("SELECT lane FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    assert row["lane"] is None


def test_assign_job_lane_job_writes_other_when_the_role_fits_none_of_the_specific_lanes(
    db_path: Path,
) -> None:
    """D-219: Other is just another approved catalog entry - the model answering it resolves the
    same way any other approved name would, no special-casing in the code."""
    app_id = add_application_with_listing(db_path, "Welder, must know TIG welding.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        ensure_other_lane(conn)
        conn.commit()
    finally:
        conn.close()

    runner = FakeRunner(text="=== LANE ===\nOther\n=== END LANE ===")
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_assign_job_lane(conn, queue, app_id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        assert get_claude_job(conn, job_id).status == "done"  # type: ignore[union-attr]
        row = conn.execute("SELECT lane FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    finally:
        conn.close()
    assert row["lane"] == "Other"


# --- analyze_lane (Phase 10's per-lane fit/gap summary, D-238) ---------------------------------

GOOD_ANALYZE_LANE_ANSWER = """=== FIT SUMMARY ===
Consistently strong on SQL and dashboarding work.
=== END FIT SUMMARY ===

=== GAPS SUMMARY ===
Limited exposure to large-scale distributed systems.
=== END GAPS SUMMARY ==="""


def add_scored_application(
    db_path: Path,
    lane: str,
    role_title: str,
    fit: list[str],
    gaps: list[str],
    match_score: float,
    listing_text: str | None = None,
) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(
            conn, {"company": "Acme Inc", "role_title": role_title, "lane": lane}
        )
        conn.execute(
            "UPDATE job_applications SET fit = ?, gaps = ?, match_score = ? WHERE id = ?",
            (json.dumps(fit), json.dumps(gaps), match_score, app_id),
        )
        if listing_text is not None:
            insert_job_file(
                conn,
                app_id,
                kind="listing",
                name="Job Listing.md",
                stored_path=f"Acme Inc/{role_title}/Job Listing.md",
                extracted_text=listing_text,
            )
        conn.commit()
    finally:
        conn.close()
    return app_id


def test_scored_applications_for_lane_only_returns_this_lanes_scored_rows(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        other_lane = create_lane(conn, "Product Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(
        db_path, "Data Analytics", "Analyst I", ["Strong SQL"], ["No Spark"], 80.0
    )
    add_scored_application(db_path, "Data Analytics", "Analyst II", ["Strong Python"], [], 60.0)
    # Unscored - excluded.
    conn = connect(db_path)
    try:
        insert_job_application(
            conn, {"company": "Acme", "role_title": "Unscored", "lane": "Data Analytics"}
        )
        conn.commit()
    finally:
        conn.close()
    add_scored_application(db_path, "Product Analytics", "PM Analyst", ["Other fit"], [], 90.0)

    conn = connect(db_path)
    try:
        applications = scored_applications_for_lane(conn, lane.id)
        other_applications = scored_applications_for_lane(conn, other_lane.id)
    finally:
        conn.close()
    # Ordered by match_score descending.
    assert [application.role_title for application in applications] == ["Analyst I", "Analyst II"]
    assert applications[0].fit == ["Strong SQL"]
    assert applications[0].gaps == ["No Spark"]
    assert [application.role_title for application in other_applications] == ["PM Analyst"]


def test_lane_analysis_ready_is_false_with_no_scored_applications(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        ready = lane_analysis_ready(conn, lane.id)
    finally:
        conn.close()
    assert ready is False


def test_lane_analysis_ready_is_true_with_a_single_scored_application(db_path: Path) -> None:
    """D-238: no minimum beyond "at least one"."""
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(db_path, "Data Analytics", "Analyst I", ["Strong SQL"], [], 80.0)

    conn = connect(db_path)
    try:
        ready = lane_analysis_ready(conn, lane.id)
    finally:
        conn.close()
    assert ready is True


def test_build_analyze_lane_prompt_includes_every_scored_application(db_path: Path) -> None:
    write_career_history(db_path, "Ten years in data analytics, SQL and Python focus.")
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(
        db_path,
        "Data Analytics",
        "Analyst I",
        ["Strong SQL"],
        ["No Spark"],
        80.0,
        listing_text="Senior Data Analyst, must know SQL and dashboarding.",
    )
    add_scored_application(db_path, "Data Analytics", "Analyst II", ["Strong Python"], [], 60.0)

    conn = connect(db_path)
    try:
        prompt = build_analyze_lane_prompt(conn, lane.id)
    finally:
        conn.close()
    assert "TASK: analyze_lane" in prompt
    assert "=== CAREER HISTORY ===" in prompt
    assert "Ten years in data analytics, SQL and Python focus." in prompt
    assert "TITLE: Analyst I" in prompt
    assert "LISTING:\nSenior Data Analyst, must know SQL and dashboarding." in prompt
    assert "- Strong SQL" in prompt
    assert "- No Spark" in prompt
    assert "TITLE: Analyst II" in prompt
    assert "- Strong Python" in prompt
    # D-244: an application with no listing on file gets a placeholder, not a blank/missing field.
    assert "(no listing text available)" in prompt


def test_build_analyze_lane_prompt_asks_for_structured_markdown(db_path: Path) -> None:
    write_career_history(db_path)
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(db_path, "Data Analytics", "Analyst I", ["Strong SQL"], [], 80.0)

    conn = connect(db_path)
    try:
        prompt = build_analyze_lane_prompt(conn, lane.id)
    finally:
        conn.close()
    normalized = " ".join(prompt.split())
    assert "### Recurring strengths" in normalized
    assert "### Where this shows up in the listings" in normalized
    assert "### Recurring gaps" in normalized
    assert "### What the listings ask for that isn't covered" in normalized


def test_build_analyze_lane_prompt_rejects_an_oversized_prompt(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import llmjobtracker.lane_pipeline as lane_pipeline_module

    monkeypatch.setattr(lane_pipeline_module, "MAX_PROMPT_CHARS", 100)
    write_career_history(db_path, "A" * 500)
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(db_path, "Data Analytics", "Analyst I", ["Strong SQL"], [], 80.0)

    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="too large"):
            build_analyze_lane_prompt(conn, lane.id)
    finally:
        conn.close()


def test_build_analyze_lane_prompt_requires_a_career_history_document(db_path: Path) -> None:
    """D-242: the career history is read for context, like every other prompt that needs a
    required document - missing entirely (not just empty) fails closed with a clear reason."""
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(db_path, "Data Analytics", "Analyst I", ["Strong SQL"], [], 80.0)

    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="CAREER HISTORY"):
            build_analyze_lane_prompt(conn, lane.id)
    finally:
        conn.close()


def test_build_analyze_lane_prompt_rejects_a_lane_with_no_scored_applications(
    db_path: Path,
) -> None:
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        with pytest.raises(PromptRejected, match="no positioning-scored applications"):
            build_analyze_lane_prompt(conn, lane.id)
    finally:
        conn.close()


def test_parse_analyze_lane_answer_reads_both_summaries() -> None:
    answer = parse_analyze_lane_answer(GOOD_ANALYZE_LANE_ANSWER)
    assert answer.fit_summary == "Consistently strong on SQL and dashboarding work."
    assert answer.gaps_summary == "Limited exposure to large-scale distributed systems."


def test_parse_analyze_lane_answer_tolerates_one_empty_summary() -> None:
    answer = parse_analyze_lane_answer(
        "=== FIT SUMMARY ===\nStrong across the board.\n=== END FIT SUMMARY ===\n\n"
        "=== GAPS SUMMARY ===\n=== END GAPS SUMMARY ==="
    )
    assert answer.fit_summary == "Strong across the board."
    assert answer.gaps_summary == ""


def test_parse_analyze_lane_answer_rejects_when_both_summaries_are_empty() -> None:
    with pytest.raises(PromptRejected, match="FIT SUMMARY or GAPS SUMMARY"):
        parse_analyze_lane_answer("I have nothing to say about this lane.")


def test_submit_analyze_lane_requires_a_scored_application(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text="unused"))
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        with pytest.raises(LaneAnalysisNotReady):
            submit_analyze_lane(conn, queue, lane.id)
    finally:
        conn.close()


def test_analyze_lane_job_writes_the_fit_gap_summary(db_path: Path) -> None:
    write_career_history(db_path)
    conn = connect(db_path)
    try:
        lane = create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    add_scored_application(
        db_path, "Data Analytics", "Analyst I", ["Strong SQL"], ["No Spark"], 80.0
    )

    runner = FakeRunner(text=GOOD_ANALYZE_LANE_ANSWER)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_analyze_lane(conn, queue, lane.id)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.lane_id == lane.id
        assert job.prompts[0].prompt_kind == JOB_KIND_ANALYZE_LANE
        updated = get_lane(conn, lane.id)
    finally:
        conn.close()
    assert updated is not None
    assert updated.fit_gap_summary is not None
    assert "Consistently strong on SQL and dashboarding work." in updated.fit_gap_summary
    assert "Limited exposure to large-scale distributed systems." in updated.fit_gap_summary
    assert updated.fit_gap_summary_generated_at is not None


# --- summarize_lanes (Phase 10's cross-lane overview report, D-245) ----------------------------

GOOD_SUMMARIZE_LANES_ANSWER = """=== OVERALL FIT ===
Consistently strong across data-facing roles.
=== END OVERALL FIT ===

=== OVERALL GAPS ===
Large-scale distributed systems experience is the recurring gap.
=== END OVERALL GAPS ==="""


def analyze_a_lane(db_path: Path, lane_name: str, summary: str) -> None:
    """Sets a lane's fit_gap_summary directly, as if "Analyze lanes" had already run for it -
    summarize_lanes reads this, not the applications behind it."""
    conn = connect(db_path)
    try:
        lane_id = conn.execute("SELECT id FROM lanes WHERE name = ?", (lane_name,)).fetchone()["id"]
        conn.execute("UPDATE lanes SET fit_gap_summary = ? WHERE id = ?", (summary, lane_id))
        conn.commit()
    finally:
        conn.close()


def test_lane_overview_ready_is_false_with_no_lane_analyzed(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        ready = lane_overview_ready(conn)
    finally:
        conn.close()
    assert ready is False


def test_lane_overview_ready_is_true_once_one_lane_is_analyzed(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    analyze_a_lane(db_path, "Data Analytics", "**Fit**\n\nStrong.\n\n**Gaps**\n\nNone.")

    conn = connect(db_path)
    try:
        ready = lane_overview_ready(conn)
    finally:
        conn.close()
    assert ready is True


def test_build_summarize_lanes_prompt_includes_history_strategy_and_analyzed_lanes_only(
    db_path: Path,
) -> None:
    write_career_history(db_path, "Ten years in data analytics.")
    write_strategy(db_path, "Lead with data analytics roles.")
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        create_lane(conn, "Product Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    analyze_a_lane(db_path, "Data Analytics", "**Fit**\n\nStrong SQL.\n\n**Gaps**\n\nNo Spark.")
    # "Product Analytics" is left with no fit_gap_summary - not analyzed yet.

    conn = connect(db_path)
    try:
        prompt = build_summarize_lanes_prompt(conn)
    finally:
        conn.close()
    assert "TASK: summarize_lanes" in prompt
    assert "Ten years in data analytics." in prompt
    assert "Lead with data analytics roles." in prompt
    assert "NAME: Data Analytics" in prompt
    assert "Strong SQL." in prompt
    assert "Product Analytics" not in prompt


def test_build_summarize_lanes_prompt_rejects_when_no_lane_has_been_analyzed(
    db_path: Path,
) -> None:
    write_career_history(db_path)
    write_strategy(db_path)
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
        with pytest.raises(PromptRejected, match="No lane has been analyzed"):
            build_summarize_lanes_prompt(conn)
    finally:
        conn.close()


def test_parse_summarize_lanes_answer_reads_both_sections() -> None:
    answer = parse_summarize_lanes_answer(GOOD_SUMMARIZE_LANES_ANSWER)
    assert answer.overall_fit == "Consistently strong across data-facing roles."
    assert answer.overall_gaps == "Large-scale distributed systems experience is the recurring gap."


def test_parse_summarize_lanes_answer_rejects_when_both_sections_are_empty() -> None:
    with pytest.raises(PromptRejected, match="OVERALL FIT or OVERALL GAPS"):
        parse_summarize_lanes_answer("I have nothing to say about this job search.")


def test_submit_summarize_lanes_requires_a_lane_to_be_analyzed(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner(text="unused"))
    conn = connect(db_path)
    try:
        with pytest.raises(LaneOverviewNotReady):
            submit_summarize_lanes(conn, queue)
    finally:
        conn.close()


def test_summarize_lanes_job_writes_the_lane_overview(db_path: Path) -> None:
    write_career_history(db_path)
    write_strategy(db_path)
    conn = connect(db_path)
    try:
        create_lane(conn, "Data Analytics", None, None)
        conn.commit()
    finally:
        conn.close()
    analyze_a_lane(db_path, "Data Analytics", "**Fit**\n\nStrong SQL.\n\n**Gaps**\n\nNo Spark.")

    runner = FakeRunner(text=GOOD_SUMMARIZE_LANES_ANSWER)
    queue = make_queue(db_path, runner)
    conn = connect(db_path)
    try:
        job_id = submit_summarize_lanes(conn, queue)
    finally:
        conn.close()
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.lane_id is None
        assert job.job_application_id is None
        assert job.prompts[0].prompt_kind == JOB_KIND_SUMMARIZE_LANES
        overview = get_lane_overview(conn)
    finally:
        conn.close()
    assert overview.summary is not None
    assert "Consistently strong across data-facing roles." in overview.summary
    assert "Large-scale distributed systems experience is the recurring gap." in overview.summary
    assert overview.generated_at is not None
