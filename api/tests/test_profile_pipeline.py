import copy
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue
from localjobtracker.claude_jobs import get_claude_job
from localjobtracker.profile_files import store_profile_file
from localjobtracker.profile_pipeline import (
    DEFAULT_RULES_PATH,
    PROMPT_KINDS,
    SCHEMAS,
    ProfileBusy,
    ProfileNotReady,
    check_facts,
    make_pipeline,
    submit_profile_analysis,
)
from localjobtracker.runner import RateLimitError, RunResult
from localjobtracker.storage import connect

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"
TOKEN = "test-token"
TASK_LINE = re.compile(r"^TASK: (\w+)$", re.MULTILINE)


class CannedRunner:
    """Answers each profile prompt from a table, keyed by the TASK line in the prompt."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any] | None] = []
        self.limit_before: set[str] = set()

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> RunResult:
        match = TASK_LINE.search(prompt)
        assert match is not None, "every profile prompt names its task"
        kind = match.group(1)
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        if kind in self.limit_before:
            self.limit_before.discard(kind)
            raise RateLimitError("Plan limit (canned runner).")
        answer = self.answers[kind]
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return RunResult(ok=True, text=text, duration_ms=0, cost_usd=0.0)


def store(db_path: Path, kind: str, name: str, content: bytes) -> int:
    conn = connect(db_path)
    try:
        return store_profile_file(conn, db_path.parent, kind, name, content).id
    finally:
        conn.close()


@pytest.fixture
def cv_id(db_path: Path) -> int:
    return store(db_path, "master_cv", "cv_en.pdf", (FIXTURES / "cv_en.pdf").read_bytes())


@pytest.fixture
def questionnaire_id(db_path: Path) -> int:
    return store(db_path, "questionnaire", "q.txt", (FIXTURES / "questionnaire.txt").read_bytes())


def good_answers(cv: int) -> dict[str, Any]:
    return {
        "full_cv_history": {
            "items": [
                {
                    "id": "H-001",
                    "kind": "role",
                    "text": "Analyst, Example Corp",
                    "date": "2020",
                    "source": {"file_id": cv, "location": "Line 2"},
                    "conflicts": [{"with": "H-002", "note": "End year differs."}],
                },
                {
                    "id": "H-002",
                    "kind": "role",
                    "text": "Analyst, Example Corp, to 2022",
                    "date": "2020",
                    "source": {"file_id": cv, "location": "Line 2"},
                    "conflicts": [{"with": "H-001", "note": "End year differs."}],
                },
            ]
        },
        "fact_sheet": {
            "facts": [
                {
                    "id": "F-001",
                    "text": "Worked as an analyst at Example Corp.",
                    "date": "2020",
                    "source": {"file_id": cv, "location": "Line 2"},
                    "history_ids": ["H-001"],
                },
                {
                    "id": "F-002",
                    "text": "Analyst role ended in 2022.",
                    "date": "2022",
                    "source": {"file_id": cv, "location": "Line 2"},
                    "history_ids": ["H-002"],
                },
            ],
            "conflicts": [{"id": "C-01", "fact_ids": ["F-001", "F-002"], "note": "End year."}],
        },
        "questionnaire_analysis": {
            "themes": [
                {
                    "id": "Q-001",
                    "text": "Wants analyst roles.",
                    "questionnaire_ref": "Q1",
                    "fact_ids": ["F-001"],
                }
            ],
            "gaps": [{"text": "Salary range is not given."}],
        },
        "strategy": {
            "overview": "Analyst work with reporting.",
            "lanes": [
                {
                    "id": "L-01",
                    "name": "Reporting analyst",
                    "description": "Reporting and data quality roles.",
                    "fact_ids": ["F-001"],
                    "questionnaire_ids": ["Q-001"],
                }
            ],
            "open_points": [],
        },
    }


def make_queue(db_path: Path, runner: CannedRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(rules_path=DEFAULT_RULES_PATH)
    return ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)


def start(db_path: Path, queue: ClaudeJobQueue) -> int:
    conn = connect(db_path)
    try:
        return submit_profile_analysis(conn, queue)
    finally:
        conn.close()


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def job_state(db_path: Path, job_id: int) -> tuple[str, str | None, list[str]]:
    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    return job.status, job.error, [prompt.status for prompt in job.prompts]


def outputs(db_path: Path) -> list[tuple[str, int]]:
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT kind, version FROM profile_outputs ORDER BY id").fetchall()
    finally:
        conn.close()
    return [(row["kind"], row["version"]) for row in rows]


def test_a_full_run_stores_the_four_outputs_and_their_facts(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id) == ("done", None, ["done"] * 4)
    assert outputs(db_path) == [(kind, 1) for kind in PROMPT_KINDS]
    conn = connect(db_path)
    try:
        facts = conn.execute("SELECT fact_key, date, source_file_id, status FROM facts").fetchall()
    finally:
        conn.close()
    assert [(f["fact_key"], f["date"], f["source_file_id"], f["status"]) for f in facts] == [
        ("F-001", "2020", cv_id, "unverified"),
        ("F-002", "2022", cv_id, "unverified"),
    ]
    assert check_facts(connect(db_path)) == []


def test_each_prompt_is_sent_with_its_schema(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    assert runner.schemas == [SCHEMAS[kind] for kind in PROMPT_KINDS]


def test_each_prompt_builds_on_what_came_before(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    fact_sheet, questionnaire, strategy = runner.prompts[1:]
    assert '"H-001"' in fact_sheet  # the history it was built from, stored by the first prompt
    assert '"F-001"' in questionnaire
    assert '"Q-001"' in strategy and '"F-002"' in strategy


def test_unreadable_files_are_left_out_of_the_prompts(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    scan_id = store(
        db_path, "older_cv", "scan.pdf", (FIXTURES / "scanned_no_text.pdf").read_bytes()
    )
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    assert f"FILE {scan_id} |" not in runner.prompts[0]
    assert f"FILE {cv_id} |" in runner.prompts[0]


def test_the_analysis_needs_a_questionnaire_and_a_cv(db_path: Path) -> None:
    queue = make_queue(db_path, CannedRunner({}))
    with pytest.raises(ProfileNotReady, match="questionnaire"):
        start(db_path, queue)
    store(db_path, "questionnaire", "q.txt", b"Some answers.")
    with pytest.raises(ProfileNotReady, match="CV"):
        start(db_path, queue)


def test_a_second_analysis_is_refused_while_one_is_unfinished(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    queue = make_queue(db_path, CannedRunner(good_answers(cv_id)))
    start(db_path, queue)
    with pytest.raises(ProfileBusy):
        start(db_path, queue)


def test_a_second_run_stores_new_versions_and_keeps_the_first(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)
    start(db_path, queue)
    run_all(queue)

    assert outputs(db_path).count(("fact_sheet", 1)) == 1
    assert outputs(db_path).count(("fact_sheet", 2)) == 1


BAD_ANSWERS: list[tuple[str, str, Any, str]] = [
    (
        "full_cv_history",
        "source file",
        lambda a: a["items"][0]["source"].update(file_id=999),
        "source file_id is not one of the input files",
    ),
    (
        "full_cv_history",
        "date",
        lambda a: a["items"][0].update(date="sometime"),
        "date must be",
    ),
    (
        "full_cv_history",
        "one-sided conflict",
        lambda a: a["items"][1].update(conflicts=[]),
        "must be listed on both items",
    ),
    (
        "fact_sheet",
        "unknown history id",
        lambda a: a["facts"][0].update(history_ids=["H-404"]),
        "unknown id H-404",
    ),
    (
        "fact_sheet",
        "missing location",
        lambda a: a["facts"][0]["source"].update(location=" "),
        "source location is empty",
    ),
    (
        "questionnaire_analysis",
        "unknown fact",
        lambda a: a["themes"][0].update(fact_ids=["F-777"]),
        "unknown id F-777",
    ),
    (
        "strategy",
        "lane without facts",
        lambda a: a["lanes"][0].update(fact_ids=[]),
        "a lane needs at least one fact",
    ),
]


@pytest.mark.parametrize(("kind", "label", "break_answer", "message"), BAD_ANSWERS)
def test_a_bad_answer_fails_the_job_with_the_reason(
    db_path: Path,
    cv_id: int,
    questionnaire_id: int,
    kind: str,
    label: str,
    break_answer: Any,
    message: str,
) -> None:
    answers = good_answers(cv_id)
    broken = copy.deepcopy(answers[kind])
    break_answer(broken)
    answers[kind] = broken
    queue = make_queue(db_path, CannedRunner(answers))
    job_id = start(db_path, queue)

    run_all(queue)

    status, error, _prompts = job_state(db_path, job_id)
    assert status == "failed", label
    assert error is not None and message in error
    assert kind not in [name for name, _version in outputs(db_path)]


def test_an_answer_wrapped_in_a_code_fence_is_accepted(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    answers = good_answers(cv_id)
    answers["full_cv_history"] = "```json\n" + json.dumps(answers["full_cv_history"]) + "\n```"
    queue = make_queue(db_path, CannedRunner(answers))
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"


def test_a_plan_limit_pauses_the_analysis_and_resume_builds_the_prompt_again(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    runner.limit_before = {"fact_sheet"}
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)
    run_all(queue)

    status, error, prompt_statuses = job_state(db_path, job_id)
    assert status == "paused"
    assert prompt_statuses == ["done", "queued", "queued", "queued"]
    assert error is not None and "Paused at a plan limit" in error

    conn = connect(db_path)
    try:
        assert queue.resume(conn, job_id) is True
    finally:
        conn.close()
    run_all(queue)

    assert job_state(db_path, job_id) == ("done", None, ["done"] * 4)


def test_the_users_own_writing_rules_replace_the_default(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    store(db_path, "writing_rules", "rules.txt", b"MY OWN RULE: keep sentences short.")
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    assert "MY OWN RULE: keep sentences short." in runner.prompts[0]
    assert "Honesty rules for generated documents" not in runner.prompts[0]


def test_the_default_rules_apply_when_none_are_uploaded(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    assert "Honesty rules for generated documents" in runner.prompts[0]


def test_a_prompt_that_is_too_large_fails_with_a_message(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    store(db_path, "older_letter", "letter.txt", ("word " * 40_000).encode("utf-8"))
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)
    run_all(queue)

    status, error, _prompts = job_state(db_path, job_id)
    assert status == "failed"
    assert error is not None and "too large" in error
    assert runner.prompts == []


@pytest.fixture
def analysis_client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, CannedRunner({}))) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def test_the_analysis_route_refuses_when_inputs_are_missing(analysis_client: TestClient) -> None:
    response = analysis_client.post("/profile/analysis")
    assert response.status_code == 400
    assert "questionnaire" in response.json()["detail"]


def test_the_analysis_route_queues_four_prompts_and_refuses_a_second_start(
    db_path: Path, analysis_client: TestClient, cv_id: int, questionnaire_id: int
) -> None:
    started = analysis_client.post("/profile/analysis")
    assert started.status_code == 201
    body = started.json()
    assert body["kind"] == "profile_analysis"
    assert [prompt["prompt_kind"] for prompt in body["prompts"]] == list(PROMPT_KINDS)
    assert analysis_client.post("/profile/analysis").status_code == 409


def test_the_outputs_route_returns_the_latest_version_of_each(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    app = create_app(TOKEN, db_path, CannedRunner(good_answers(cv_id)))
    queue: ClaudeJobQueue = app.state.queue
    with TestClient(app) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        start(db_path, queue)
        run_all(queue)

        listed = client.get("/profile/outputs").json()

    assert [item["kind"] for item in listed] == list(PROMPT_KINDS)
    assert listed[0]["body"]["items"][0]["id"] == "H-001"
