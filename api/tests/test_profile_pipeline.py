import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.claude_jobs import get_claude_job
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.profile_files import store_profile_file
from llmjobtracker.profile_pipeline import (
    DEFAULT_RULES_PATH,
    PROMPT_KINDS,
    ProfileBusy,
    ProfileNotReady,
    make_pipeline,
    submit_profile_analysis,
)
from llmjobtracker.runner import RateLimitError, RunResult
from llmjobtracker.storage import connect

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"
TOKEN = "test-token"
TASK_LINE = re.compile(r"^TASK: (\w+)$", re.MULTILINE)


class CannedRunner:
    """Answers each profile prompt from a table, keyed by the TASK line in the prompt."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.prompts: list[str] = []
        self.limit_before: set[str] = set()

    def run(
        self,
        prompt: str,
        cancel: threading.Event | None = None,
        json_schema: dict[str, Any] | None = None,
        on_text: Any = None,
    ) -> RunResult:
        match = TASK_LINE.search(prompt)
        assert match is not None, "every profile prompt names its task"
        kind = match.group(1)
        self.prompts.append(prompt)
        if kind in self.limit_before:
            self.limit_before.discard(kind)
            raise RateLimitError("Plan limit (canned runner).")
        return RunResult(ok=True, text=self.answers[kind], duration_ms=0, cost_usd=0.0)


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


def good_answers(cv: int) -> dict[str, str]:
    return {
        "full_cv_history": (
            "# Career history\n\n"
            "## Analyst, Example Corp\n"
            f"2020 to 2022, per FILE {cv}. Worked as an analyst with a focus on reporting.\n"
        ),
        "questionnaire_analysis": (
            "# Questionnaire analysis\n\n"
            "## How the material reads\n"
            "A clear analyst story with a focus on reporting.\n\n"
            "## Patterns\n"
            "Wants analyst roles that lean on reporting work.\n"
        ),
        "strategy": (
            "# Positioning strategy\n\n"
            "## Primary lanes\n"
            "Reporting analyst, fit 4.5/5. Matches the reporting work.\n"
        ),
    }


def make_queue(db_path: Path, runner: CannedRunner) -> ClaudeJobQueue:
    render, on_result = make_pipeline(db_path.parent, rules_path=DEFAULT_RULES_PATH)
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def start(db_path: Path, queue: ClaudeJobQueue) -> int:
    conn = connect(db_path)
    try:
        return submit_profile_analysis(conn, queue, db_path.parent)
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


def test_a_full_run_stores_the_three_documents(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id) == ("done", None, ["done"] * 3)
    assert outputs(db_path) == [(kind, 1) for kind in PROMPT_KINDS]


def test_a_full_run_also_saves_each_output_as_a_readable_generated_file(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT kind FROM profile_files WHERE generated = 1 ORDER BY kind"
        ).fetchall()
    finally:
        conn.close()
    assert [row["kind"] for row in rows] == [
        "own_full_cv_history",
        "own_questionnaire_analysis",
        "own_strategy",
    ]


def test_a_generated_file_is_not_sent_back_as_evidence(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    conn = connect(db_path)
    try:
        generated_id = conn.execute(
            "SELECT id FROM profile_files WHERE kind = 'own_full_cv_history'"
        ).fetchone()["id"]
    finally:
        conn.close()
    assert f"FILE {generated_id} |" not in runner.prompts[0]


def test_each_prompt_builds_on_what_came_before(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)

    questionnaire_prompt, strategy_prompt = runner.prompts[1:]
    # The history it was built from, stored by the first prompt.
    assert "Analyst, Example Corp" in questionnaire_prompt
    assert "Analyst, Example Corp" in strategy_prompt
    assert "clear analyst story" in strategy_prompt


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


def test_a_second_run_creates_nothing_when_everything_is_there(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    queue = make_queue(db_path, runner)
    start(db_path, queue)
    run_all(queue)
    before = outputs(db_path)

    with pytest.raises(ProfileNotReady, match="Nothing is missing"):
        start(db_path, queue)
    assert outputs(db_path) == before
    assert len(runner.prompts) == 3


def test_an_empty_answer_fails_the_job(db_path: Path, cv_id: int, questionnaire_id: int) -> None:
    answers = good_answers(cv_id)
    answers["full_cv_history"] = "   "
    queue = make_queue(db_path, CannedRunner(answers))
    job_id = start(db_path, queue)

    run_all(queue)

    status, error, _prompts = job_state(db_path, job_id)
    assert status == "failed"
    assert error is not None and "empty" in error
    assert "full_cv_history" not in [name for name, _version in outputs(db_path)]


def test_an_answer_wrapped_in_a_code_fence_is_accepted(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    answers = good_answers(cv_id)
    answers["full_cv_history"] = "```markdown\n" + answers["full_cv_history"] + "```"
    queue = make_queue(db_path, CannedRunner(answers))
    job_id = start(db_path, queue)

    run_all(queue)

    assert job_state(db_path, job_id)[0] == "done"
    conn = connect(db_path)
    try:
        document = conn.execute(
            "SELECT document FROM profile_outputs WHERE kind = 'full_cv_history'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert not document.startswith("```")


def test_a_plan_limit_pauses_the_analysis_and_resume_builds_the_prompt_again(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    runner = CannedRunner(good_answers(cv_id))
    runner.limit_before = {"questionnaire_analysis"}
    queue = make_queue(db_path, runner)
    job_id = start(db_path, queue)
    run_all(queue)

    status, error, prompt_statuses = job_state(db_path, job_id)
    assert status == "paused"
    assert prompt_statuses == ["done", "queued", "queued"]
    assert error is not None and "Paused at a plan limit" in error

    conn = connect(db_path)
    try:
        assert queue.resume(conn, job_id) is True
    finally:
        conn.close()
    run_all(queue)

    assert job_state(db_path, job_id) == ("done", None, ["done"] * 3)


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


def test_the_analysis_route_queues_three_prompts_and_refuses_a_second_start(
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
    assert "Analyst, Example Corp" in listed[0]["document"]


def test_an_analysis_reads_each_upload_again_from_its_copy(
    db_path: Path, cv_id: int, questionnaire_id: int
) -> None:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE profile_files SET extracted_text = 'stale text' WHERE id = ?", (cv_id,)
            )
    finally:
        conn.close()
    queue = make_queue(db_path, CannedRunner(good_answers(cv_id)))

    start(db_path, queue)

    conn = connect(db_path)
    try:
        text = conn.execute(
            "SELECT extracted_text FROM profile_files WHERE id = ?", (cv_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert text != "stale text"
    assert "Analyst, Example Corp" in text
