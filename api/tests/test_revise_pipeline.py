from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.claude_jobs import get_claude_job, list_claude_jobs
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.profile_files import list_profile_files, store_profile_file
from llmjobtracker.profile_pipeline import DEFAULT_RULES_PATH, ProfileNotReady
from llmjobtracker.revise_pipeline import make_pipeline, submit_revise_turn
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"


def rewrite(document: str) -> str:
    """A MODE: rewrite answer (D-110), the shape every FakeRunner answer used before D-110."""
    return f"MODE: rewrite\n\n{document}"


def edit(*pairs: tuple[str, str]) -> str:
    """A MODE: edit answer (D-110) made of one or more OLD/NEW blocks."""
    blocks = "\n\n".join(
        f"=== EDIT ===\nOLD:\n{old}\nNEW:\n{new}\n=== END EDIT ===" for old, new in pairs
    )
    return f"MODE: edit\n\n{blocks}"


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
    return ClaudeJobQueue(db_path, LangGraphRunner(runner), on_result=on_result, render=render)


def run_all(queue: ClaudeJobQueue) -> None:
    while queue.process_next():
        pass


def submit(
    db_path: Path,
    queue: ClaudeJobQueue,
    kind: str,
    message: str,
    excluded_kinds: list[str] | None = None,
) -> int:
    conn = connect(db_path)
    try:
        return submit_revise_turn(conn, queue, kind, message, excluded_kinds)
    finally:
        conn.close()


def store(db_path: Path, kind: str, name: str, content: bytes) -> int:
    conn = connect(db_path)
    try:
        return store_profile_file(conn, db_path.parent, kind, name, content).id
    finally:
        conn.close()


def test_a_turn_sends_the_current_document_and_the_request_and_stores_the_answer(
    db_path: Path,
) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal text.")
    runner = FakeRunner(text=rewrite("# Career history\n\nPunchier text."))
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
    runner = FakeRunner(text=rewrite("v2"))
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "First ask.")
    run_all(queue)

    runner.text = rewrite("v3")
    submit(db_path, queue, "full_cv_history", "Second ask.")
    run_all(queue)

    second_prompt = runner.prompts[1]
    assert "First ask." in second_prompt
    assert "Second ask." in second_prompt
    assert "EARLIER REQUESTS" in second_prompt
    assert "v2" in second_prompt  # the document the second turn reads is the first turn's answer
    assert latest_document(db_path, "full_cv_history") == "v3"


def test_a_career_history_revise_turn_reads_evidence_files_by_default(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    store(db_path, "older_cv", "cv.txt", b"Senior Analyst, Example Corp, 2019 to 2022.")
    store(db_path, "older_letter", "letter.txt", b"I am excited to apply for this role.")
    runner = FakeRunner(text=rewrite("v2"))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, "full_cv_history", "Fold in the older material.")
    run_all(queue)

    assert "Senior Analyst, Example Corp, 2019 to 2022." in runner.prompts[0]
    assert "I am excited to apply for this role." in runner.prompts[0]


def test_excluding_a_kind_leaves_its_files_out_of_a_career_history_revise(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    store(db_path, "older_cv", "cv.txt", b"Senior Analyst, Example Corp, 2019 to 2022.")
    store(db_path, "older_letter", "letter.txt", b"I am excited to apply for this role.")
    runner = FakeRunner(text=rewrite("v2"))
    queue = make_queue(db_path, runner)

    submit(
        db_path,
        queue,
        "full_cv_history",
        "Fold in the older CV only.",
        excluded_kinds=["older_letter"],
    )
    run_all(queue)

    assert "Senior Analyst, Example Corp, 2019 to 2022." in runner.prompts[0]
    assert "I am excited to apply for this role." not in runner.prompts[0]


def test_excluded_kinds_is_ignored_for_a_kind_with_no_evidence_group(db_path: Path) -> None:
    """Questionnaire analysis and strategy have no file-pool to exclude (D-261) - sending
    excluded_kinds for one is simply ignored, not an error."""
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    seed_document(db_path, "questionnaire_analysis", "# Questionnaire analysis\n\nOriginal.")
    store(db_path, "questionnaire", "q.txt", b"Some answers.")
    runner = FakeRunner(text=rewrite("v2"))
    queue = make_queue(db_path, runner)

    job_id = submit(
        db_path,
        queue,
        "questionnaire_analysis",
        "Tighten this up.",
        excluded_kinds=["older_cv"],
    )
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "done"


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
    runner = FakeRunner(text=rewrite("# Career history\n\nRevised."))
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


def test_the_prompt_explains_the_edit_and_rewrite_modes(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    runner = FakeRunner(text=rewrite("New."))
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "Make it punchier.")
    run_all(queue)

    assert "MODE: edit" in runner.prompts[0]
    assert "MODE: rewrite" in runner.prompts[0]
    assert "=== EDIT ===" in runner.prompts[0]


def test_a_single_edit_is_applied_to_the_current_document(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nAnalyst at Example Corp.")
    runner = FakeRunner(text=edit(("Analyst at Example Corp.", "Senior Analyst at Example Corp.")))
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "Say senior.")
    run_all(queue)

    assert (
        latest_document(db_path, "full_cv_history")
        == "# Career history\n\nSenior Analyst at Example Corp."
    )


def test_several_edits_are_all_applied(db_path: Path) -> None:
    seed_document(
        db_path, "full_cv_history", "# Career history\n\nRole: Analyst.\nYears: 2020-2022."
    )
    runner = FakeRunner(
        text=edit(
            ("Role: Analyst.", "Role: Senior Analyst."),
            ("Years: 2020-2022.", "Years: 2020-2023."),
        )
    )
    queue = make_queue(db_path, runner)
    submit(db_path, queue, "full_cv_history", "Fix the title and the end date.")
    run_all(queue)

    assert latest_document(db_path, "full_cv_history") == (
        "# Career history\n\nRole: Senior Analyst.\nYears: 2020-2023."
    )


def test_an_edit_that_does_not_match_fails_the_job_and_leaves_the_document_unchanged(
    db_path: Path,
) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal text.")
    runner = FakeRunner(text=edit(("Text that is not in the document", "Replacement")))
    queue = make_queue(db_path, runner)
    job_id = submit(db_path, queue, "full_cv_history", "Change something.")
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "failed"
    assert "Could not find this text" in (job.error or "")
    assert latest_document(db_path, "full_cv_history") == "# Career history\n\nOriginal text."


def test_an_edit_whose_old_text_is_not_unique_fails_the_job(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nAnalyst. Analyst.")
    runner = FakeRunner(text=edit(("Analyst.", "Senior Analyst.")))
    queue = make_queue(db_path, runner)
    job_id = submit(db_path, queue, "full_cv_history", "Fix the title.")
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "failed"
    assert "not unique" in (job.error or "")


def test_an_answer_with_no_mode_line_fails_the_job(db_path: Path) -> None:
    seed_document(db_path, "full_cv_history", "# Career history\n\nOriginal.")
    runner = FakeRunner(text="Just the document, no MODE line.")
    queue = make_queue(db_path, runner)
    job_id = submit(db_path, queue, "full_cv_history", "Change something.")
    run_all(queue)

    conn = connect(db_path)
    try:
        job = get_claude_job(conn, job_id)
    finally:
        conn.close()
    assert job is not None
    assert job.status == "failed"
    assert "MODE" in (job.error or "")


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
    runner = FakeRunner(text=rewrite("# Career history\n\nRevised via chat."))
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
