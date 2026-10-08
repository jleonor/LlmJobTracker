from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue
from localjobtracker.claude_jobs import get_claude_job, list_claude_jobs
from localjobtracker.profile_files import list_profile_files
from localjobtracker.profile_pipeline import DEFAULT_RULES_PATH, ProfileNotReady
from localjobtracker.revise_pipeline import make_pipeline, submit_revise_turn
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"


def seed_document(db_path: Path, kind: str, document: str) -> None:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO profile_outputs (kind, version, document, input_sha256s, source) "
                "VALUES (?, 1, ?, '[]', 'generated')",
                (kind, document),
            )
    finally:
        conn.close()


def latest_document(db_path: Path, kind: str) -> str:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT document FROM profile_outputs WHERE kind = ? ORDER BY version DESC LIMIT 1",
            (kind,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return str(row["document"])


def make_queue(db_path: Path, runner: FakeRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, rules_path=DEFAULT_RULES_PATH)
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def submit(db_path: Path, queue: ClaudeJobQueue, kind: str, message: str) -> int:
    conn = connect(db_path)
    try:
        return submit_revise_turn(conn, queue, kind, message)
    finally:
        conn.close()


def test_a_turn_sends_the_current_document_and_the_request_and_stores_the_answer(
    db_path: Path,
) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal text.")
    runner = FakeRunner(text="# Career history\n\nPunchier text.")
    queue = make_queue(db_path, runner)

    job_id = submit(db_path, queue, "full_cv_history", "Make it punchier.")
    run_all(queue)

    assert "Make it punchier." in runner.prompts[0]
    assert "Original text." in runner.prompts[0]
    assert "TASK: revise_full_cv_history" in runner.prompts[0]
    assert latest_document(db_path, "full_cv_history") == "# Career history\n\nPunchier text."

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "done"
    assert job.kind == "revise_own_full_cv_history"


def test_a_second_turn_reads_the_first_turns_answer_and_replays_it_as_history(
    db_path: Path,
) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    runner = FakeRunner(text="v2")
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "First ask.")
    run_all(queue)

    runner.text = "v3"
    submit(db_path, queue, "full_cv_history", "Second ask.")
    run_all(queue)

    second_prompt = runner.prompts[1]
    assert "First ask." in second_prompt
    assert "Second ask." in second_prompt
    assert "EARLIER REQUESTS" in second_prompt
    assert "v2" in second_prompt  # the document the second turn reads is the first turn's answer
    assert latest_document(db_path, "full_cv_history") == "v3"


def test_revise_is_refused_when_there_is_no_document_yet(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(ProfileNotReady):
            submit_revise_turn(conn, queue, "full_cv_history", "Hi")
    finally:
        conn.close()


def test_an_empty_message_is_refused(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# doc")
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(ValueError):
            submit_revise_turn(conn, queue, "full_cv_history", "   ")
    finally:
        conn.close()


def test_an_unknown_output_kind_is_refused(db_path: Path) -> None:
    queue = make_queue(db_path, FakeRunner())
    conn = connect(db_path)
    try:
        with pytest.raises(ValueError):
            submit_revise_turn(conn, queue, "cover_letter", "Hi")
    finally:
        conn.close()


def test_the_revised_document_is_saved_as_a_readable_generated_file(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    runner = FakeRunner(text="# Career history\n\nRevised.")
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "Revise it.")
    run_all(queue)

    conn = connect(db_path)
    try:
        files = [f for f in list_profile_files(conn) if f.kind == "own_full_cv_history"]
    finally:
        conn.close()
    assert len(files) == 1
    assert files[0].generated is True


def test_questionnaire_analysis_revise_fails_without_a_questionnaire(db_path: Path) -> None:
    seed_document(db_path, "questionnaire_analysis", "# Questionnaire analysis\n\nOld.")
    queue = make_queue(db_path, FakeRunner(text="New."))
    submit(db_path, queue, "questionnaire_analysis", "Punch it up.")
    run_all(queue)

    conn = connect(db_path)
    try:
        jobs = list_claude_jobs(conn)
    finally:
        conn.close()
    assert jobs[-1].status == "failed"
    assert "questionnaire" in (jobs[-1].error or "").lower()


def client_for(db_path: Path, runner: FakeRunner) -> TestClient:
    test_client = TestClient(create_app(TOKEN, db_path, runner))
    test_client.headers[TOKEN_HEADER] = TOKEN
    return test_client


def test_the_api_queues_a_turn_and_lists_it_once_done(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    runner = FakeRunner(text="# Career history\n\nRevised via chat.")
    with client_for(db_path, runner) as client:
        app = client.app
        assert isinstance(app, FastAPI)
        queue: ClaudeJobQueue = app.state.queue
        created = client.post(
            "/profile/revise/full_cv_history/turns", json={"message": "Tighten the summary."}
        )
        assert created.status_code == 201
        body = created.json()
        assert body["message"] == "Tighten the summary."
        assert body["job"]["status"] == "queued"

        run_all(queue)

        listed = client.get("/profile/revise/full_cv_history/turns").json()
        assert len(listed) == 1
        assert listed[0]["job"]["status"] == "done"
    assert latest_document(db_path, "full_cv_history") == "# Career history\n\nRevised via chat."


def test_an_unknown_output_kind_is_a_404_at_the_api(db_path: Path) -> None:
    with client_for(db_path, FakeRunner()) as client:
        assert client.get("/profile/revise/cover_letter/turns").status_code == 404
        assert (
            client.post("/profile/revise/cover_letter/turns", json={"message": "Hi"}).status_code
            == 404
        )
