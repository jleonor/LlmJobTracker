"""Tests for the lane Claude Jobs (Agent/specs/lane-steps.md, D-214): extract_lanes, the Lanes
section's "Sync from strategy" action, and assign_job_lane, the per-application step behind the
one-off reassignment pass (D-217).
"""

from pathlib import Path

import pytest

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file
from llmjobtracker.job_pipeline import make_pipeline
from llmjobtracker.lane_pipeline import (
    JOB_KIND_ASSIGN_LANE,
    JOB_KIND_EXTRACT_LANES,
    LaneAssignmentNotReady,
    LaneSyncNotReady,
    build_assign_lane_prompt,
    build_extract_lanes_prompt,
    parse_lanes_answer,
    submit_assign_job_lane,
    submit_extract_lanes,
)
from llmjobtracker.lanes import create_lane, list_lanes
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
    assert [lane.name for lane in lanes] == ["Data Analytics", "Product Analytics"]
    assert [lane.position for lane in lanes] == [0, 1]


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
    assert [lane.name for lane in lanes] == ["Existing Lane"]


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
