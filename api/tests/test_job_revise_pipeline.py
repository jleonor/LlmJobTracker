"""Tests for the job page's chat-revise plumbing (D-136, Agent/specs/job-revise-steps.md):
Job details', Application history's and Positioning analysis's patch grammars, the shared
job-scoped turns table, and the routes.
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
from localjobtracker.job_files import list_job_files, store_job_file
from localjobtracker.job_pipeline import RequirementScore, scores_to_json
from localjobtracker.job_revise_pipeline import (
    ApplicationHistoryRevision,
    JobReviseNotReady,
    RequirementPatch,
    ScorePatch,
    apply_requirement_patches,
    apply_score_patches,
    make_pipeline,
    parse_application_history_revision,
    parse_job_details_revision,
    parse_positioning_revision,
    submit_job_revise_turn,
)
from localjobtracker.profile_pipeline import store_output
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
    db_path: Path,
    queue: ClaudeJobQueue,
    app_id: int,
    section_kind: str,
    message: str,
    attachment_job_file_id: int | None = None,
) -> int:
    conn = connect(db_path)
    try:
        return submit_job_revise_turn(
            conn, queue, app_id, section_kind, message, attachment_job_file_id
        )
    finally:
        conn.close()


def fill_application_history(
    db_path: Path, app_id: int, next_action: str | None, due_date: str | None
) -> None:
    conn = connect(db_path)
    try:
        update_job_application(conn, app_id, {"next_action": next_action, "due_date": due_date})
    finally:
        conn.close()


def read_application_history(db_path: Path, app_id: int) -> tuple[str | None, str | None]:
    conn = connect(db_path)
    try:
        detail = get_job_application_detail(conn, app_id)
    finally:
        conn.close()
    assert detail is not None
    return detail.next_action, detail.due_date


def history_answer(next_action: str = "unchanged", due_date: str = "unchanged") -> str:
    return (
        f"=== NEXT ACTION ===\n{next_action}\n=== END NEXT ACTION ===\n\n"
        f"=== DUE DATE ===\n{due_date}\n=== END DUE DATE ==="
    )


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


# --- Application history: parse_application_history_revision, pure-function tests ---


def test_parse_application_history_revision_reads_both_fields() -> None:
    revision = parse_application_history_revision(
        history_answer("Follow up with the recruiter.", "2026-11-01")
    )
    assert revision == ApplicationHistoryRevision(
        True, "Follow up with the recruiter.", True, "2026-11-01"
    )


def test_parse_application_history_revision_none_clears_a_field() -> None:
    revision = parse_application_history_revision(history_answer("unchanged", "none"))
    assert revision.due_date_changed is True
    assert revision.due_date is None
    assert revision.next_action_changed is False


def test_parse_application_history_revision_rejects_a_bad_date() -> None:
    with pytest.raises(PromptRejected, match="YYYY-MM-DD"):
        parse_application_history_revision(history_answer("unchanged", "next Tuesday"))


def test_parse_application_history_revision_rejects_a_no_op_answer() -> None:
    with pytest.raises(PromptRejected, match="did not change anything"):
        parse_application_history_revision(history_answer("unchanged", "unchanged"))


# --- submit_job_revise_turn / the pipeline, end to end with FakeRunner ---


def test_a_turn_updates_next_action_and_leaves_due_date_unchanged(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_application_history(db_path, app_id, "Wait for a reply.", "2026-10-20")
    runner = FakeRunner(text=history_answer("Call the recruiter back.", "unchanged"))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "application_history", "They called - update the next step.")
    run_all(queue)

    next_action, due_date = read_application_history(db_path, app_id)
    assert next_action == "Call the recruiter back."
    assert due_date == "2026-10-20"


def test_a_turn_can_clear_the_due_date(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_application_history(db_path, app_id, "Wait for a reply.", "2026-10-20")
    runner = FakeRunner(text=history_answer("unchanged", "none"))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "application_history", "There's no deadline after all.")
    run_all(queue)

    next_action, due_date = read_application_history(db_path, app_id)
    assert next_action == "Wait for a reply."
    assert due_date is None


def test_a_bad_date_leaves_application_history_unchanged(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_application_history(db_path, app_id, "Wait for a reply.", "2026-10-20")
    runner = FakeRunner(text=history_answer("unchanged", "soonish"))
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "application_history", "Push the date out a bit.")
    run_all(queue)

    next_action, due_date = read_application_history(db_path, app_id)
    assert (next_action, due_date) == ("Wait for a reply.", "2026-10-20")


def test_an_attached_eml_shows_up_in_the_sent_prompt(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_application_history(db_path, app_id, "Wait for a reply.", None)
    conn = connect(db_path)
    try:
        eml = (
            b"From: recruiter@acme.example\r\n"
            b"Date: Mon, 10 Oct 2026 09:00:00 +0000\r\n"
            b"Subject: Interview scheduled\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"\r\n"
            b"Can you do Thursday at 2pm?\r\n"
        )
        attachment = store_job_file(
            conn, db_path.parent / "files", app_id, "eml", "Interview.eml", eml
        )
    finally:
        conn.close()
    runner = FakeRunner(text=history_answer("Confirm Thursday at 2pm.", "unchanged"))
    queue = make_queue(db_path, runner)

    submit(
        db_path,
        queue,
        app_id,
        "application_history",
        "Set the next action from the attached email.",
        attachment.id,
    )
    run_all(queue)

    assert "Can you do Thursday at 2pm?" in runner.prompts[0]
    next_action, _ = read_application_history(db_path, app_id)
    assert next_action == "Confirm Thursday at 2pm."


def test_an_attached_other_file_is_read_with_the_general_extractor(db_path: Path) -> None:
    app_id = add_application(db_path)
    fill_application_history(db_path, app_id, "Wait for a reply.", None)
    conn = connect(db_path)
    try:
        attachment = store_job_file(
            conn,
            db_path.parent / "files",
            app_id,
            "other",
            "notes.txt",
            b"Recruiter said to follow up by the 5th.",
        )
    finally:
        conn.close()
    runner = FakeRunner(text=history_answer("unchanged", "unchanged"))
    queue = make_queue(db_path, runner)

    submit(
        db_path,
        queue,
        app_id,
        "application_history",
        "Anything useful in the attachment?",
        attachment.id,
    )
    run_all(queue)

    assert "Recruiter said to follow up by the 5th." in runner.prompts[0]


def test_submit_rejects_when_application_history_has_nothing_to_revise(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="no Application history yet"):
        submit(db_path, queue, app_id, "application_history", "What's next?")


# --- Positioning analysis: helpers ---


def add_profile_documents(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        for kind, text in (
            ("full_cv_history", "# Career history\n\nAnalyst with five years of SQL-heavy work."),
            (
                "questionnaire_analysis",
                "# Questionnaire analysis\n\nStrong preference for data roles.",
            ),
            ("strategy", "# Strategy\n\nLead with SQL and reporting experience."),
        ):
            store_output(conn, kind, text, None, [], source="generated")
        conn.commit()
    finally:
        conn.close()


def fill_positioning(
    db_path: Path,
    app_id: int,
    *,
    fit: list[str],
    gaps: list[str],
    strategy: str,
    unclear: list[str],
    scores: list[RequirementScore],
) -> None:
    conn = connect(db_path)
    try:
        update_job_application(
            conn, app_id, {"fit": fit, "gaps": gaps, "strategy": strategy, "unclear": unclear}
        )
        # Empty scores (D-140: a Positioning analysis generated before migration 19) has no
        # match_score to compute - left null, the same as a row that predates it.
        match_score = (
            round(
                sum(s.weight * s.match for s in scores)
                / (10 * sum(s.weight for s in scores))
                * 100,
                1,
            )
            if scores
            else None
        )
        with conn:
            conn.execute(
                "UPDATE job_applications SET match_score = ?, positioning_scores = ? WHERE id = ?",
                (match_score, scores_to_json(scores), app_id),
            )
    finally:
        conn.close()


def read_positioning(
    db_path: Path, app_id: int
) -> tuple[list[str], list[str], str | None, list[str], float | None]:
    conn = connect(db_path)
    try:
        detail = get_job_application_detail(conn, app_id)
    finally:
        conn.close()
    assert detail is not None
    return detail.fit, detail.gaps, detail.strategy, detail.unclear, detail.match_score


def positioning_answer(
    fit: str = "unchanged",
    gaps: str = "unchanged",
    strategy: str = "unchanged",
    unclear: str = "unchanged",
    *patches: str,
) -> str:
    body = "\n\n".join(patches)
    return (
        f"=== FIT ===\n{fit}\n=== END FIT ===\n\n"
        f"=== GAPS ===\n{gaps}\n=== END GAPS ===\n\n"
        f"=== STRATEGY ===\n{strategy}\n=== END STRATEGY ===\n\n"
        f"=== UNCLEAR ===\n{unclear}\n=== END UNCLEAR ===\n\n{body}"
    )


def score_patch(
    number: str, weight: str = "unchanged", match: str = "unchanged", reasoning: str = "unchanged"
) -> str:
    return (
        f"=== REQUIREMENT PATCH ===\nNUMBER: {number}\nWEIGHT: {weight}\nMATCH: {match}\n"
        f"REASONING: {reasoning}\n=== END REQUIREMENT PATCH ==="
    )


TWO_SCORES = [
    RequirementScore(text="Strong SQL", weight=8, match=9, reasoning="Five years of SQL work."),
    RequirementScore(text="4+ years experience", weight=6, match=10, reasoning="Six years total."),
]


# --- parse_positioning_revision / apply_score_patches: pure-function tests ---


def test_parse_positioning_revision_reads_fields_and_patches() -> None:
    revision = parse_positioning_revision(
        positioning_answer(
            "- A new fit point", "unchanged", "unchanged", "unchanged", score_patch("1", "9")
        )
    )
    assert revision.fit == ["A new fit point"]
    assert revision.gaps is None
    assert revision.patches == [ScorePatch(number="1", weight="9", match=None, reasoning=None)]


def test_parse_positioning_revision_drops_a_fully_unchanged_patch_block() -> None:
    """D-140: observed live - with no scores to patch yet, the model echoed the answer
    template's own REQUIREMENT PATCH block with every field "unchanged" rather than omitting it.
    That block has nothing to apply, so it's dropped instead of failing on a non-integer NUMBER."""
    revision = parse_positioning_revision(
        positioning_answer(
            "unchanged", "- A new gap", "unchanged", "unchanged", score_patch("unchanged")
        )
    )
    assert revision.gaps == ["A new gap"]
    assert revision.patches == []


def test_parse_positioning_revision_rejects_a_no_op_answer() -> None:
    with pytest.raises(PromptRejected, match="did not change anything"):
        parse_positioning_revision(positioning_answer())


def test_apply_score_patches_changes_only_the_given_fields() -> None:
    result = apply_score_patches(
        TWO_SCORES, [ScorePatch(number="1", weight="9", match=None, reasoning=None)]
    )
    assert result[0] == RequirementScore(
        text="Strong SQL", weight=9, match=9, reasoning="Five years of SQL work."
    )
    assert result[1] == TWO_SCORES[1]  # untouched


def test_apply_score_patches_rejects_an_out_of_range_number() -> None:
    with pytest.raises(PromptRejected, match="not a current requirement"):
        apply_score_patches(
            TWO_SCORES, [ScorePatch(number="5", weight="1", match=None, reasoning=None)]
        )


def test_apply_score_patches_rejects_leaving_every_weight_at_zero() -> None:
    with pytest.raises(PromptRejected, match="weight of 0"):
        apply_score_patches(
            TWO_SCORES,
            [
                ScorePatch(number="1", weight="0", match=None, reasoning=None),
                ScorePatch(number="2", weight="0", match=None, reasoning=None),
            ],
        )


# --- submit_job_revise_turn / the pipeline, end to end with FakeRunner ---


def test_a_turn_adjusts_one_weight_and_recomputes_match_score(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_profile_documents(db_path)
    fill_positioning(
        db_path,
        app_id,
        fit=["Strong SQL background"],
        gaps=[],
        strategy="Lead with the data work.",
        unclear=[],
        scores=TWO_SCORES,
    )
    runner = FakeRunner(
        text=positioning_answer(
            "unchanged", "unchanged", "unchanged", "unchanged", score_patch("1", "10", "9")
        )
    )
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "positioning", "Weight the SQL requirement higher.")
    run_all(queue)

    fit, gaps, strategy, unclear, match_score = read_positioning(db_path, app_id)
    assert strategy == "Lead with the data work."  # unchanged
    # Σ(weight×match)÷(10×Σweight)×100 = (10×9 + 6×10) ÷ (10×16) × 100 = 93.75 -> 93.8
    assert match_score == pytest.approx(93.8, abs=0.05)
    conn = connect(db_path)
    try:
        breakdown = [
            f for f in list_job_files(conn, app_id) if f["kind"] == "positioning_breakdown"
        ]
    finally:
        conn.close()
    assert len(breakdown) == 1


def test_a_turn_replaces_fit_and_gaps(db_path: Path) -> None:
    app_id = add_application(db_path)
    add_profile_documents(db_path)
    fill_positioning(
        db_path,
        app_id,
        fit=["Strong SQL background"],
        gaps=[],
        strategy="Lead with the data work.",
        unclear=[],
        scores=TWO_SCORES,
    )
    runner = FakeRunner(
        text=positioning_answer(
            "- Strong SQL background\n- Five years of analytics", "- No BI tool experience"
        )
    )
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "positioning", "Add a fit point and note the BI tool gap.")
    run_all(queue)

    fit, gaps, strategy, unclear, match_score = read_positioning(db_path, app_id)
    assert fit == ["Strong SQL background", "Five years of analytics"]
    assert gaps == ["No BI tool experience"]
    assert match_score == pytest.approx(94.3, abs=0.05)  # untouched by a fit/gaps-only turn


def test_submit_rejects_when_positioning_has_nothing_to_revise(db_path: Path) -> None:
    app_id = add_application(db_path)
    queue = make_queue(db_path, FakeRunner())
    with pytest.raises(JobReviseNotReady, match="no Positioning analysis yet"):
        submit(db_path, queue, app_id, "positioning", "Raise the SQL weight.")


def test_a_turn_succeeds_with_no_scores_yet_and_an_echoed_empty_patch_block(db_path: Path) -> None:
    """D-140: a Positioning analysis generated before migration 19 has positioning_scores = '[]'
    - a turn that only touches gaps must still succeed even if the model echoes the answer
    template's own empty REQUIREMENT PATCH block."""
    app_id = add_application(db_path)
    add_profile_documents(db_path)
    fill_positioning(
        db_path,
        app_id,
        fit=["Strong SQL background"],
        gaps=[],
        strategy="Lead with the data work.",
        unclear=[],
        scores=[],
    )
    runner = FakeRunner(
        text=positioning_answer(
            "unchanged",
            "- No BI tool experience",
            "unchanged",
            "unchanged",
            score_patch("unchanged"),
        )
    )
    queue = make_queue(db_path, runner)

    submit(db_path, queue, app_id, "positioning", "Note the BI tool gap.")
    run_all(queue)

    fit, gaps, strategy, unclear, match_score = read_positioning(db_path, app_id)
    assert gaps == ["No BI tool experience"]
    assert match_score is None  # untouched - no scores existed to recompute from
