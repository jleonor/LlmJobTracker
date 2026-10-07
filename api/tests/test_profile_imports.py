import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_profile_pipeline import (
    FIXTURES,
    CannedRunner,
    good_answers,
    job_state,
    make_queue,
    outputs,
    run_all,
    start,
    store,
)

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue
from localjobtracker.claude_jobs import get_claude_job
from localjobtracker.profile_files import delete_profile_file
from localjobtracker.profile_pipeline import ProfileNotReady
from localjobtracker.storage import connect

TOKEN = "test-token"


def latest_versions(db_path: Path) -> dict[str, int]:
    latest: dict[str, int] = {}
    for kind, version in outputs(db_path):
        latest[kind] = max(latest.get(kind, 0), version)
    return latest


def prompt_results(db_path: Path, job_id: int) -> list[str | None]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT result_text FROM claude_job_prompts WHERE claude_job_id = ? ORDER BY position",
            (job_id,),
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


@pytest.fixture
def cv(db_path: Path) -> int:
    return store(db_path, "master_cv", "cv_en.pdf", (FIXTURES / "cv_en.pdf").read_bytes())


@pytest.fixture
def questionnaire(db_path: Path) -> int:
    return store(db_path, "questionnaire", "q.txt", (FIXTURES / "questionnaire.txt").read_bytes())


def test_missing_outputs_are_made_and_the_uploaded_ones_are_used_as_is(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    analysis = b"My own questionnaire analysis."
    store(db_path, "own_questionnaire_analysis", "analysis.txt", analysis)
    store(db_path, "own_strategy", "strategy.txt", b"My own strategy: analyst lanes.")
    runner = CannedRunner(good_answers(cv))
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    assert latest_versions(db_path) == {
        "full_cv_history": 1,
        "questionnaire_analysis": 1,
        "strategy": 1,
    }
    # Only the career history is missing, so only it sends a Claude prompt; the two uploads are
    # copied in as-is, with no reformatting call (D-86).
    assert len(runner.prompts) == 1
    results = prompt_results(db_path, job_id)
    assert results[1] == "Skipped: using your own file."
    assert results[2] == "Skipped: using your own file."
    conn = connect(db_path)
    try:
        document, recorded = conn.execute(
            "SELECT document, input_sha256s FROM profile_outputs "
            "WHERE kind = 'questionnaire_analysis'"
        ).fetchone()
    finally:
        conn.close()
    assert document == "My own questionnaire analysis."
    assert hashlib.sha256(analysis).hexdigest() in recorded

    # The API tells "used your own file" apart from "already in place" (not both just "skipped").
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert [p.skip_reason for p in job.prompts] == [
        None,
        "Skipped: using your own file.",
        "Skipped: using your own file.",
    ]


def test_a_run_with_everything_in_place_is_refused(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    store(db_path, "own_strategy", "strategy.txt", b"My own strategy.")
    queue = make_queue(db_path, CannedRunner(good_answers(cv)))
    start(db_path, queue)
    run_all(queue)

    with pytest.raises(ProfileNotReady, match="Nothing is missing"):
        start(db_path, queue)


def test_uploading_one_missing_output_uses_only_that_one(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    runner = CannedRunner(good_answers(cv))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)
    before = latest_versions(db_path)
    prompts_before = len(runner.prompts)

    store(db_path, "own_strategy", "strategy.txt", b"My own strategy.")
    job_id = start(db_path, queue)
    run_all(queue)

    after = latest_versions(db_path)
    assert after["strategy"] == before["strategy"] + 1
    assert {kind: after[kind] for kind in after if kind != "strategy"} == {
        kind: before[kind] for kind in before if kind != "strategy"
    }
    assert len(runner.prompts) == prompts_before  # the file is copied in, with no Claude call
    results = prompt_results(db_path, job_id)
    assert results[:2] == ["Skipped: already in place."] * 2
    assert results[2] == "Skipped: using your own file."


def test_a_new_career_history_rebuilds_what_depends_on_it(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    runner = CannedRunner(good_answers(cv))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)
    prompts_before = len(runner.prompts)

    store(db_path, "own_full_cv_history", "history.txt", b"My history.")
    start(db_path, queue)
    run_all(queue)

    assert latest_versions(db_path) == {
        "full_cv_history": 2,
        "questionnaire_analysis": 2,
        "strategy": 2,
    }
    # The history is copied in with no Claude call; the two that depend on it are regenerated.
    assert len(runner.prompts) - prompts_before == 2
    conn = connect(db_path)
    try:
        document = conn.execute(
            "SELECT document FROM profile_outputs WHERE kind = 'full_cv_history' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()
    assert document == "My history."


def test_a_history_upload_works_without_any_cv(db_path: Path, questionnaire: int) -> None:
    history = store(db_path, "own_full_cv_history", "history.txt", b"My history.")
    queue = make_queue(db_path, CannedRunner(good_answers(history)))
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    assert latest_versions(db_path)["full_cv_history"] == 1


def test_deleting_an_imported_own_file_makes_the_next_run_generate_a_fresh_one(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    own_id = store(db_path, "own_strategy", "strategy.txt", b"My own strategy.")
    runner = CannedRunner(good_answers(cv))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)
    assert latest_versions(db_path)["strategy"] == 1

    conn = connect(db_path)
    try:
        delete_profile_file(conn, db_path.parent, own_id)
    finally:
        conn.close()

    # Nothing of the user's own is left for strategy, and it is no longer "in place": the file
    # it was copied from is gone, so the next run must generate a fresh one, not keep reusing
    # the deleted file's content forever (D-93).
    job_id = start(db_path, queue)
    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    assert latest_versions(db_path)["strategy"] == 2
    results = prompt_results(db_path, job_id)
    assert results[2] not in ("Skipped: already in place.", "Skipped: using your own file.")
    conn = connect(db_path)
    try:
        document, source = conn.execute(
            "SELECT document, source FROM profile_outputs WHERE kind = 'strategy' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert source == "generated"
    assert document == good_answers(cv)["strategy"].strip()


def test_deleting_a_generated_file_makes_the_next_run_generate_a_fresh_one(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    # No own upload this time: the strategy document is Claude's own generated answer, mirrored
    # as a readable file (D-84). Deleting that file is the thing being tested, not an upload.
    runner = CannedRunner(good_answers(cv))
    app = create_app(TOKEN, db_path, runner)
    queue: ClaudeJobQueue = app.state.queue
    with TestClient(app) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        start(db_path, queue)
        run_all(queue)
        assert latest_versions(db_path)["strategy"] == 1

        files = client.get("/profile/files").json()
        generated = next(f for f in files if f["kind"] == "own_strategy")
        assert generated["generated"] is True

        removed = client.delete(f"/profile/files/{generated['id']}")
        assert removed.status_code == 200

        # Deleting the file alone must not leave the stored document behind, "still there" for
        # decide() to find (D-95): the next run has to generate a fresh one, same as D-93.
        job_id = start(db_path, queue)
        run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    # version 1 again, not 2: clear_output removes the row entirely, not just superseding it.
    assert latest_versions(db_path)["strategy"] == 1
    results = prompt_results(db_path, job_id)
    assert results[2] not in ("Skipped: already in place.", "Skipped: using your own file.")
