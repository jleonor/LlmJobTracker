import hashlib
import re
from pathlib import Path

import pytest
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

from localjobtracker.profile_pipeline import ProfileNotReady
from localjobtracker.storage import connect

BUILD = "build from the material"
CONVERT = "convert the person's own version"


def modes(runner: CannedRunner) -> list[str]:
    found = []
    for prompt in runner.prompts:
        match = re.search(r"^MODE: (.*)$", prompt, re.MULTILINE)
        assert match is not None
        found.append(match.group(1))
    return found


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


def test_missing_outputs_are_made_and_the_uploaded_ones_are_converted(
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
        "fact_sheet": 1,
        "questionnaire_analysis": 1,
        "strategy": 1,
    }
    assert modes(runner) == [BUILD, BUILD, CONVERT, CONVERT]
    assert "My own questionnaire analysis." in runner.prompts[2]
    assert "My own strategy: analyst lanes." in runner.prompts[3]
    conn = connect(db_path)
    try:
        recorded = conn.execute(
            "SELECT input_sha256s FROM profile_outputs WHERE kind = 'questionnaire_analysis'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert hashlib.sha256(analysis).hexdigest() in recorded


def test_a_run_with_everything_in_place_is_refused(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    store(db_path, "own_strategy", "strategy.txt", b"My own strategy.")
    queue = make_queue(db_path, CannedRunner(good_answers(cv)))
    start(db_path, queue)
    run_all(queue)

    with pytest.raises(ProfileNotReady, match="Nothing is missing"):
        start(db_path, queue)


def test_uploading_one_missing_output_converts_only_that_one(
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
    assert modes(runner)[prompts_before:] == [CONVERT]
    results = prompt_results(db_path, job_id)
    assert results[:3] == ["Skipped: already in place."] * 3
    assert results[3] is not None and "Skipped" not in results[3]


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
        "fact_sheet": 2,
        "questionnaire_analysis": 2,
        "strategy": 2,
    }
    assert modes(runner)[prompts_before:] == [CONVERT, BUILD, BUILD, BUILD]
    assert "My history." in runner.prompts[prompts_before]


def test_a_history_upload_works_without_any_cv(db_path: Path, questionnaire: int) -> None:
    history = store(db_path, "own_full_cv_history", "history.txt", b"My history.")
    queue = make_queue(db_path, CannedRunner(good_answers(history)))
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    assert latest_versions(db_path)["full_cv_history"] == 1


def test_a_converted_output_that_breaks_the_checks_fails_the_job(
    db_path: Path, cv: int, questionnaire: int
) -> None:
    store(db_path, "own_strategy", "strategy.txt", b"My own strategy.")
    answers = good_answers(cv)
    answers["strategy"]["lanes"][0]["fact_ids"] = []
    queue = make_queue(db_path, CannedRunner(answers))
    job_id = start(db_path, queue)

    run_all(queue)

    status, error, _prompts = job_state(db_path, job_id)
    assert status == "failed"
    assert error is not None and "a lane needs at least one fact" in error
    assert "strategy" not in latest_versions(db_path)
