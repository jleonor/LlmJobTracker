"""Tests for the job page's chat-revise plumbing (D-136, Agent/specs/job-revise-steps.md):
Job details' patch grammar, the shared job-scoped turns table, and the routes.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from localjobtracker.job_applications import (
    get_job_application_detail,
    insert_job_application,
    update_job_application,
)
from localjobtracker.job_files import store_job_file
from localjobtracker.job_revise_pipeline import (
    JobReviseNotReady,
    RequirementPatch,
    apply_requirement_patches,
    make_pipeline,
    parse_job_details_revision,
    submit_job_revise_turn,
)
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"

LISTING_TEXT = (
    "Senior Data Analyst at Acme Inc\n\n"
    "Requirements:\n"
    "- 4+ years in analytics\n"
    "- Strong SQL\n"
    "- Fluent German or French\n"
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


def add_listing(db_path: Path, app_id: int, text: str = LISTING_TEXT) -> None:
    conn = connect(db_path)
    try:
        store_job_file(
            conn, db_path.parent / "files", app_id, "listing", "Job Listing.txt", text.encode()
        )
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


def read_job_details(db_path: Path, app_id: int) -> tuple[str | None, list[str]]:
    conn = connect(db_path)
    try:
        detail = get_job_application_detail(conn, app_id)
    finally:
        conn.close()
    assert detail is not None
    return detail.description, detail.requirements


def submit(
    db_path: Path, queue: ClaudeJobQueue, app_id: int, section_kind: str, message: str
) -> int:
    conn = connect(db_path)
    try:
        return submit_job_revise_turn(conn, queue, app_id, section_kind, message)
    finally:
        conn.close()


def patch_answer(description: str = "unchanged", *patches: str) -> str:
    body = "\n\n".join(patches)
    return f"=== DESCRIPTION ===\n{description}\n=== END DESCRIPTION ===\n\n{body}"


def requirement_patch(number: str, action: str, text: str | None = None) -> str:
    text_line = f"\nTEXT: {text}" if text is not None else ""
    return (
        f"=== REQUIREMENT PATCH ===\nNUMBER: {number}\nACTION: {action}{text_line}\n"
        "=== END REQUIREMENT PATCH ==="
    )


# --- parse_job_details_revision / apply_requirement_patches: pure-function tests ---


def test_parse_job_details_revision_reads_description_and_patches() -> None:
    text = patch_answer(
        "A sharper description.",
        requirement_patch("2", "EDIT", "Excellent SQL"),
        requirement_patch("3", "REMOVE"),
    )
    revision = parse_job_details_revision(text)
    assert revision.description == "A sharper description."
    assert revision.patches == [
        RequirementPatch(number="2", action="EDIT", text="Excellent SQL"),
        RequirementPatch(number="3", action="REMOVE", text=None),
    ]


def test_parse_job_details_revision_unchanged_description_is_none() -> None:
    revision = parse_job_details_revision(
        patch_answer("unchanged", requirement_patch("1", "REMOVE"))
    )
    assert revision.description is None


def test_parse_job_details_revision_rejects_an_empty_answer() -> None:
    with pytest.raises(PromptRejected, match="did not change anything"):
        parse_job_details_revision(patch_answer("unchanged"))


def test_parse_job_details_revision_rejects_edit_missing_text() -> None:
    with pytest.raises(PromptRejected, match="missing TEXT"):
        parse_job_details_revision(
            patch_answer(
                "unchanged",
                "=== REQUIREMENT PATCH ===\nNUMBER: 1\nACTION: EDIT\n=== END REQUIREMENT PATCH ===",
            )
        )


def test_apply_requirement_patches_edits_removes_and_adds() -> None:
    result = apply_requirement_patches(
        ["4+ years in analytics", "Strong SQL", "Fluent German or French"],
        [
            RequirementPatch(number="2", action="EDIT", text="Strong SQL"),
            RequirementPatch(number="3", action="REMOVE", text=None),
            RequirementPatch(number="NEW", action="ADD", text="4+ years in analytics"),
        ],
        LISTING_TEXT,
    )
    assert result == ["4+ years in analytics", "Strong SQL", "4+ years in analytics"]


def test_apply_requirement_patches_rejects_non_verbatim_text() -> None:
    with pytest.raises(PromptRejected, match="does not appear in the listing"):
        apply_requirement_patches(
            ["Strong SQL"],
            [RequirementPatch(number="1", action="EDIT", text="Expert-level SQL mastery")],
            LISTING_TEXT,
        )


def test_apply_requirement_patches_rejects_an_out_of_range_number() -> None:
    with pytest.raises(PromptRejected, match="not a current requirement"):
        apply_requirement_patches(
            ["Strong SQL"], [RequirementPatch(number="5", action="REMOVE", text=None)], LISTING_TEXT
        )


def test_apply_requirement_patches_rejects_patching_the_same_requirement_twice() -> None:
    with pytest.raises(PromptRejected, match="more than once"):
        apply_requirement_patches(
            ["Strong SQL", "4+ years in analytics"],
            [
                RequirementPatch(number="1", action="REMOVE", text=None),
                RequirementPatch(number="1", action="EDIT", text="Strong SQL"),
            ],
            LISTING_TEXT,
        )


# --- submit_job_revise_turn / the pipeline, end to end with FakeRunner ---


def test_a_turn_sends_the_listing_and_current_requirements_and_applies_an_edit(
    db_path: Path,
) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["4+ years in analytics", "Strong SQL"])
    runner = FakeRunner(
        text=patch_answer("unchanged", requirement_patch("2", "EDIT", "Strong SQL"))
    )
    queue = make_queue(db_path, runner)

    job_id = submit(db_path, queue, app_id, "job_details", "Tighten the SQL requirement's wording.")
    run_all(queue)

    assert "Tighten the SQL requirement's wording." in runner.prompts[0]
    assert "4+ years in analytics" in runner.prompts[0]
    assert "TASK: revise_job_details" in runner.prompts[0]
    description, requirements = read_job_details(db_path, app_id)
    assert description == "A role description."  # unchanged
    assert requirements == ["4+ years in analytics", "Strong SQL"]
    assert job_id > 0


def test_a_turn_replaces_the_description(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    runner = FakeRunner(text=patch_answer("A much sharper description of the role."))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "job_details", "Make the description punchier.")
    run_all(queue)

    description, requirements = read_job_details(db_path, app_id)
    assert description == "A much sharper description of the role."
    assert requirements == ["Strong SQL"]


def test_a_bad_edit_leaves_requirements_unchanged(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    runner = FakeRunner(
        text=patch_answer("unchanged", requirement_patch("1", "EDIT", "Expert-level SQL mastery"))
    )
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "job_details", "Make it sound more impressive.")
    run_all(queue)

    description, requirements = read_job_details(db_path, app_id)
    assert requirements == ["Strong SQL"]  # the bad edit never applied


def test_a_second_turn_sees_the_first_turns_message_in_its_history(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    runner = FakeRunner(text=patch_answer("A new description."))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "job_details", "First ask.")
    run_all(queue)
    submit(db_path, queue, app_id, "job_details", "Second ask.")
    run_all(queue)

    assert len(runner.prompts) == 2
    assert "Turn 1: First ask." not in runner.prompts[0]  # no history yet for the first turn
    assert "Turn 1: First ask." in runner.prompts[1]
    assert "Second ask." in runner.prompts[1]


def test_submit_rejects_when_job_details_has_nothing_to_revise(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="no Job details yet"):
        submit(db_path, queue, app_id, "job_details", "Tighten this up.")


def test_submit_rejects_an_empty_message(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(ValueError, match="empty"):
        submit(db_path, queue, app_id, "job_details", "   ")


def test_submit_rejects_a_section_kind_whose_grammar_is_not_built_yet(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="isn't built yet"):
        submit(db_path, queue, app_id, "positioning", "Raise the weight on the SQL requirement.")


def test_submit_rejects_an_unknown_section_kind(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(ValueError, match="Unknown section kind"):
        submit(db_path, queue, app_id, "not_a_kind", "x")


# --- routes ---


def client_for(db_path: Path, runner: FakeRunner) -> TestClient:
    test_client = TestClient(create_app(TOKEN, db_path, runner))
    test_client.headers[TOKEN_HEADER] = TOKEN
    return test_client


def test_route_turn_lifecycle(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_listing(db_path, app_id)
    fill_job_details(db_path, app_id, ["Strong SQL"])
    runner = FakeRunner(text=patch_answer("A new description."))
    with client_for(db_path, runner) as client:
        assert client.get(f"/job-applications/{app_id}/revise/job_details/turns").json() == []

        response = client.post(
            f"/job-applications/{app_id}/revise/job_details/turns",
            json={"message": "Make the description punchier."},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["message"] == "Make the description punchier."
        assert body["job"]["status"] in ("queued", "processing")

        turns = client.get(f"/job-applications/{app_id}/revise/job_details/turns").json()
        assert len(turns) == 1
        assert turns[0]["id"] == body["id"]


def test_route_404s_for_an_unknown_application_or_section_kind(db_path: Path) -> None:
    app_id = add_application(db_path)
    with client_for(db_path, FakeRunner()) as client:
        assert client.get("/job-applications/999999/revise/job_details/turns").status_code == 404
        assert client.get(f"/job-applications/{app_id}/revise/not_a_kind/turns").status_code == 404
        assert (
            client.post(
                f"/job-applications/{app_id}/revise/not_a_kind/turns", json={"message": "x"}
            ).status_code
            == 404
        )


def test_route_400s_when_theres_nothing_to_revise_yet(db_path: Path) -> None:
    app_id = add_application(db_path)
    with client_for(db_path, FakeRunner()) as client:
        response = client.post(
            f"/job-applications/{app_id}/revise/job_details/turns", json={"message": "x"}
        )
        assert response.status_code == 400
