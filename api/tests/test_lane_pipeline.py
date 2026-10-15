"""Tests for extract_lanes (Agent/specs/lane-steps.md §1, D-214): the Lanes section's "Sync from
strategy" action, which regenerates the approved lane catalog from the positioning strategy
document.
"""

from pathlib import Path

import pytest

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.job_pipeline import make_pipeline
from llmjobtracker.lane_pipeline import (
    JOB_KIND_EXTRACT_LANES,
    LaneSyncNotReady,
    build_extract_lanes_prompt,
    parse_lanes_answer,
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
