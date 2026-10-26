from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import llmjobtracker.app as app_module
from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file, job_file_text
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"
FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"
LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def add_application(db_path: Path, company: str = "Co", role_title: str = "Analyst") -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": company, "role_title": role_title})
        conn.commit()
    finally:
        conn.close()
    return app_id


def add_profile_file(db_path: Path, kind: str, original_name: str) -> int:
    from llmjobtracker.profile_files import store_profile_file

    conn = connect(db_path)
    try:
        return store_profile_file(conn, db_path.parent, kind, original_name, b"content").id
    finally:
        conn.close()


# --- Upload --------------------------------------------------------------------------------


def test_upload_stores_the_file_under_the_managed_folder(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path, "Acme Inc", "Analyst")

    response = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "Job Listing.pdf"},
        content=b"%PDF-1.4 fake",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "listing"
    assert body["name"] == "Job Listing.pdf"
    stored = db_path.parent / "files" / "Acme Inc" / "Analyst" / "Job Listing.pdf"
    assert stored.read_bytes() == b"%PDF-1.4 fake"

    detail = client.get(f"/job-applications/{app_id}").json()
    assert [f["id"] for f in detail["files"]] == [body["id"]]


def test_an_uploaded_listing_or_additional_file_is_extracted_but_other_kinds_are_not(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path, "Acme Inc", "Analyst")

    listing = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.html"},
        content=(LISTING_FIXTURES / "listing.html").read_bytes(),
    ).json()
    assert listing["extraction_status"] == "ok"
    assert listing["extraction_message"] is None

    # "other" is Additional files (the Files subsection) - also extracted at upload time (D-262),
    # so its content can feed Application history's Revise context.
    other = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Reminder: follow up Friday.",
    ).json()
    assert other["extraction_status"] == "ok"

    # A kind that still isn't prompt input (D-109) gets no extraction.
    unextracted = client.post(
        f"/job-applications/{app_id}/files/tailored_cv",
        headers={"X-File-Name": "draft.txt"},
        content=b"A draft CV, not actually generated here.",
    ).json()
    assert unextracted["extraction_status"] is None

    conn = connect(db_path)
    try:
        text = job_file_text(conn, listing["id"])
        assert text is not None
        assert "Senior Data Analyst" in text.text
        assert "Accept all" not in text.text
        other_text = job_file_text(conn, other["id"])
        assert other_text is not None
        assert other_text.text == "Reminder: follow up Friday."
        unextracted_text = job_file_text(conn, unextracted["id"])
        assert unextracted_text is not None
        assert unextracted_text.text == ""
    finally:
        conn.close()

    detail = client.get(f"/job-applications/{app_id}").json()
    by_id = {f["id"]: f for f in detail["files"]}
    assert by_id[listing["id"]]["extraction_status"] == "ok"
    assert by_id[other["id"]]["extraction_status"] == "ok"
    assert by_id[unextracted["id"]]["extraction_status"] is None


def test_an_unreadable_listing_upload_is_kept_and_reported(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "scan.pdf"},
        content=b"%PDF-1.4 not a real pdf",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["extraction_status"] in ("failed", "no_text")


def test_a_second_upload_with_the_same_name_does_not_overwrite_the_first(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    first = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"first",
    ).json()
    second = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"second",
    ).json()

    assert first["name"] == "notes.txt"
    assert second["name"] != "notes.txt"
    folder = db_path.parent / "files" / "Co" / "Analyst"
    assert (folder / first["name"]).read_bytes() == b"first"
    assert (folder / second["name"]).read_bytes() == b"second"


def test_upload_rejects_an_unknown_kind(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/files/not_a_kind",
        headers={"X-File-Name": "x.txt"},
        content=b"x",
    )
    assert response.status_code == 400


def test_upload_rejects_an_unsupported_extension(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "virus.exe"},
        content=b"x",
    )
    assert response.status_code == 415


def test_upload_to_an_unknown_application_is_not_found(client: TestClient) -> None:
    response = client.post(
        "/job-applications/999/files/listing",
        headers={"X-File-Name": "x.pdf"},
        content=b"x",
    )
    assert response.status_code == 404


# --- Open and preview ------------------------------------------------------------------------


def test_open_hands_the_copy_to_the_default_app(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = add_application(db_path)
    uploaded = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.txt"},
        content=b"A listing.",
    ).json()
    opened: list[Path] = []
    monkeypatch.setattr(app_module, "open_in_default_app", opened.append)

    response = client.post(f"/job-applications/{app_id}/files/{uploaded['id']}/open")

    assert response.status_code == 204
    assert opened == [db_path.parent / "files" / "Co" / "Analyst" / "listing.txt"]


def test_open_of_a_file_from_another_application_is_not_found(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path, "Co", "Analyst")
    other_id = add_application(db_path, "Other Co", "Analyst")
    uploaded = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.txt"},
        content=b"A listing.",
    ).json()

    response = client.post(f"/job-applications/{other_id}/files/{uploaded['id']}/open")

    assert response.status_code == 404


def test_reveal_shows_the_copy_in_the_file_manager(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id = add_application(db_path)
    uploaded = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.txt"},
        content=b"A listing.",
    ).json()
    revealed: list[Path] = []
    monkeypatch.setattr(app_module, "reveal_in_file_manager", revealed.append)

    response = client.post(f"/job-applications/{app_id}/files/{uploaded['id']}/reveal")

    assert response.status_code == 204
    assert revealed == [db_path.parent / "files" / "Co" / "Analyst" / "listing.txt"]


def test_reveal_of_a_file_from_another_application_is_not_found(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path, "Co", "Analyst")
    other_id = add_application(db_path, "Other Co", "Analyst")
    uploaded = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.txt"},
        content=b"A listing.",
    ).json()

    response = client.post(f"/job-applications/{other_id}/files/{uploaded['id']}/reveal")

    assert response.status_code == 404


def test_download_returns_the_files_own_bytes_and_name(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    uploaded = client.post(
        f"/job-applications/{app_id}/files/listing",
        headers={"X-File-Name": "listing.txt"},
        content=b"A listing.",
    ).json()

    response = client.get(f"/job-applications/{app_id}/files/{uploaded['id']}/download")

    assert response.status_code == 200
    assert response.content == b"A listing."
    assert 'filename="listing.txt"' in response.headers["content-disposition"]


def test_download_of_an_unknown_file_is_not_found(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.get(f"/job-applications/{app_id}/files/999999/download")
    assert response.status_code == 404


def test_a_txt_upload_previews_as_text(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    uploaded = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Some notes.",
    ).json()

    response = client.get(f"/job-applications/{app_id}/files/{uploaded['id']}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Some notes."


def test_preview_of_an_unknown_file_is_not_found(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.get(f"/job-applications/{app_id}/files/999999/preview")
    assert response.status_code == 404


# --- Delete a file (D-211) --------------------------------------------------------------------


def test_deleting_a_file_removes_the_row_and_the_copy_on_disk(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    uploaded = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Some notes.",
    ).json()
    stored_path = db_path.parent / "files" / "Co" / "Analyst" / "notes.txt"
    assert stored_path.exists()

    response = client.delete(f"/job-applications/{app_id}/files/{uploaded['id']}")

    assert response.status_code == 200
    assert not stored_path.exists()
    assert client.get(f"/job-applications/{app_id}").json()["files"] == []


def test_deleting_an_unknown_file_is_not_found(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.delete(f"/job-applications/{app_id}/files/999999")
    assert response.status_code == 404


def test_deleting_a_file_scoped_to_a_different_application_is_not_found(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    other_app_id = add_application(db_path, company="Other Co", role_title="Other Role")
    uploaded = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Some notes.",
    ).json()

    response = client.delete(f"/job-applications/{other_app_id}/files/{uploaded['id']}")

    assert response.status_code == 404
    assert client.get(f"/job-applications/{app_id}").json()["files"] != []


def test_deleting_the_positioning_breakdown_also_clears_the_match_score(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    conn = connect(db_path)
    try:
        folder = db_path.parent / "files" / "Co" / "Analyst"
        folder.mkdir(parents=True)
        (folder / "Positioning breakdown.md").write_text("breakdown", encoding="utf-8")
        insert_job_file(
            conn,
            app_id,
            kind="positioning_breakdown",
            name="Positioning breakdown.md",
            stored_path="Co/Analyst/Positioning breakdown.md",
        )
        conn.execute(
            "UPDATE job_applications SET match_score = 81.0, positioning_scores = '[]' "
            "WHERE id = ?",
            (app_id,),
        )
        conn.commit()
    finally:
        conn.close()
    file_id = client.get(f"/job-applications/{app_id}").json()["files"][0]["id"]

    response = client.delete(f"/job-applications/{app_id}/files/{file_id}")

    assert response.status_code == 200
    detail = client.get(f"/job-applications/{app_id}").json()
    assert detail["match_score"] is None
    assert detail["files"] == []


def test_deleting_a_non_breakdown_file_leaves_the_match_score_alone(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    conn = connect(db_path)
    try:
        conn.execute(
            "UPDATE job_applications SET match_score = 81.0, positioning_scores = '[]' "
            "WHERE id = ?",
            (app_id,),
        )
        conn.commit()
    finally:
        conn.close()
    uploaded = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Some notes.",
    ).json()

    response = client.delete(f"/job-applications/{app_id}/files/{uploaded['id']}")

    assert response.status_code == 200
    assert client.get(f"/job-applications/{app_id}").json()["match_score"] == 81.0


# --- Edit ------------------------------------------------------------------------------------


def test_edit_updates_only_the_fields_sent(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    client.patch(f"/job-applications/{app_id}", json={"location": "Geneva, CH"})

    response = client.patch(f"/job-applications/{app_id}", json={"notes": "Follow up Friday."})

    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Geneva, CH"
    assert body["notes"] == "Follow up Friday."


def test_edit_writes_lane(client: TestClient, db_path: Path) -> None:
    """D-178: lane becomes manually editable through Job details, like every other field there."""
    app_id = add_application(db_path)

    response = client.patch(
        f"/job-applications/{app_id}", json={"lane": "AI Product/Applied AI Engineer"}
    )

    assert response.status_code == 200
    assert response.json()["lane"] == "AI Product/Applied AI Engineer"


def test_edit_writes_requirements_and_manual_positioning_fields(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)

    response = client.patch(
        f"/job-applications/{app_id}",
        json={
            "requirements": ["Python", "SQL"],
            "fit": ["Strong SQL background"],
            "gaps": ["No retail experience"],
            "strategy": "Lead with the data pipeline work.",
            "unclear": ["Which BI tool they use"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requirements"] == ["Python", "SQL"]
    assert body["fit"] == ["Strong SQL background"]
    assert body["gaps"] == ["No retail experience"]
    assert body["strategy"] == "Lead with the data pipeline work."
    assert body["unclear"] == ["Which BI tool they use"]
    # match_score is untouched by Edit (D-47, D-116).
    assert body["match_score"] is None


def test_edit_writes_interview_prep_pairs(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.patch(
        f"/job-applications/{app_id}",
        json={
            "interview_prep": [
                {"question": "Why this role?", "answer": "The SQL work lines up.", "score": 8},
                # A pair added by hand, with no score (D-173: null for an unscored pair).
                {"question": "Biggest gap?", "answer": "No retail experience."},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interview_prep"] == [
        {"question": "Why this role?", "answer": "The SQL work lines up.", "score": 8},
        {"question": "Biggest gap?", "answer": "No retail experience.", "score": None},
    ]


def test_edit_rejects_an_unknown_work_mode(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.patch(f"/job-applications/{app_id}", json={"work_mode": "Flexible"})
    assert response.status_code == 400


def test_edit_of_an_unknown_application_is_not_found(client: TestClient) -> None:
    response = client.patch("/job-applications/999", json={"notes": "x"})
    assert response.status_code == 404


def test_edit_with_an_empty_body_changes_nothing(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    client.patch(f"/job-applications/{app_id}", json={"notes": "Keep this."})

    response = client.patch(f"/job-applications/{app_id}", json={})

    assert response.status_code == 200
    assert response.json()["notes"] == "Keep this."


# --- Edit: role_title (D-207) -----------------------------------------------------------------


def test_edit_writes_role_title(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "Senior Analyst"})

    assert response.status_code == 200
    assert response.json()["role_title"] == "Senior Analyst"


def test_edit_trims_role_title(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "  Senior  "})

    assert response.status_code == 200
    assert response.json()["role_title"] == "Senior"


def test_edit_rejects_a_blank_role_title(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "   "})

    assert response.status_code == 400
    unchanged = client.get(f"/job-applications/{app_id}")
    assert unchanged.json()["role_title"] == "Analyst"


def test_edit_renames_the_managed_folder_and_its_stored_files(
    client: TestClient, db_path: Path
) -> None:
    files_root = db_path.parent / "files"
    app_id = add_application(db_path, company="Co", role_title="Analyst")
    conn = connect(db_path)
    try:
        folder = files_root / "Co" / "Analyst"
        folder.mkdir(parents=True)
        (folder / "Job Listing.md").write_text("Some listing text.", encoding="utf-8")
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Co/Analyst/Job Listing.md",
        )
        conn.commit()
    finally:
        conn.close()

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "Senior Analyst"})

    assert response.status_code == 200
    assert not folder.exists()
    new_folder = files_root / "Co" / "Senior Analyst"
    assert (new_folder / "Job Listing.md").read_text(encoding="utf-8") == "Some listing text."

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT stored_path FROM job_files WHERE job_application_id = ?", (app_id,)
        ).fetchone()
        assert row["stored_path"] == "Co/Senior Analyst/Job Listing.md"
    finally:
        conn.close()

    download = client.get(f"/job-applications/{app_id}/files/999999999/download")
    assert download.status_code == 404  # sanity check the route itself still works post-rename


def test_edit_renaming_to_the_same_title_is_a_no_op(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path, company="Co", role_title="Analyst")

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "Analyst"})

    assert response.status_code == 200
    assert response.json()["role_title"] == "Analyst"


def test_edit_rejects_renaming_onto_an_existing_folder(client: TestClient, db_path: Path) -> None:
    files_root = db_path.parent / "files"
    app_id = add_application(db_path, company="Co", role_title="Analyst")
    (files_root / "Co" / "Senior Analyst").mkdir(parents=True)

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "Senior Analyst"})

    assert response.status_code == 400


def test_edit_renames_the_folder_even_with_no_files_yet(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path, company="Co", role_title="Analyst")

    response = client.patch(f"/job-applications/{app_id}", json={"role_title": "Senior Analyst"})

    assert response.status_code == 200


# --- Master CV ---------------------------------------------------------------------------------


def test_choosing_a_master_cv_sets_the_reference_and_name(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    profile_file_id = add_profile_file(db_path, "master_cv", "Master CV.pdf")

    response = client.post(
        f"/job-applications/{app_id}/master-cv", json={"profile_file_id": profile_file_id}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["master_cv_profile_file_id"] == profile_file_id
    assert body["master_cv_name"] == "Master CV.pdf"
    # No job file is created - it's a reference, not a copy (D-116).
    assert body["files"] == []


def test_choosing_a_non_master_cv_file_is_rejected(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    profile_file_id = add_profile_file(db_path, "older_cv", "Old CV.pdf")

    response = client.post(
        f"/job-applications/{app_id}/master-cv", json={"profile_file_id": profile_file_id}
    )

    assert response.status_code == 400


def test_choosing_an_unknown_profile_file_is_not_found(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.post(f"/job-applications/{app_id}/master-cv", json={"profile_file_id": 999})
    assert response.status_code == 404


def test_clearing_the_master_cv_selection(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    profile_file_id = add_profile_file(db_path, "master_cv", "Master CV.pdf")
    client.post(f"/job-applications/{app_id}/master-cv", json={"profile_file_id": profile_file_id})

    response = client.post(f"/job-applications/{app_id}/master-cv", json={"profile_file_id": None})

    assert response.status_code == 200
    assert response.json()["master_cv_profile_file_id"] is None


def test_deleting_the_chosen_profile_file_clears_the_reference(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)
    profile_file_id = add_profile_file(db_path, "master_cv", "Master CV.pdf")
    client.post(f"/job-applications/{app_id}/master-cv", json={"profile_file_id": profile_file_id})

    client.delete(f"/profile/files/{profile_file_id}")

    detail = client.get(f"/job-applications/{app_id}").json()
    assert detail["master_cv_profile_file_id"] is None
    assert detail["master_cv_name"] is None


# --- Status history ------------------------------------------------------------------------


def test_replacing_stage_dates_sets_the_furthest_reached_as_current(
    client: TestClient, db_path: Path
) -> None:
    app_id = add_application(db_path)

    response = client.put(
        f"/job-applications/{app_id}/status-history",
        json={
            "entries": [
                {"status": "Identified", "changed_at": "2026-09-01T00:00:00Z"},
                {"status": "Applied", "changed_at": "2026-09-05T00:00:00Z"},
                {"status": "Screening", "changed_at": "2026-09-10T00:00:00Z"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Screening"
    assert [h["status"] for h in body["status_history"]] == ["Identified", "Applied", "Screening"]
    assert body["last_updated"] == "2026-09-10T00:00:00Z"


def test_an_end_state_takes_priority_over_main_stages(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.put(
        f"/job-applications/{app_id}/status-history",
        json={
            "entries": [
                {"status": "Identified", "changed_at": "2026-09-01T00:00:00Z"},
                {"status": "Applied", "changed_at": "2026-09-05T00:00:00Z"},
                {"status": "Rejected", "changed_at": "2026-09-12T00:00:00Z"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Rejected"


def test_the_later_end_state_wins_when_both_are_dated(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)

    response = client.put(
        f"/job-applications/{app_id}/status-history",
        json={
            "entries": [
                {"status": "Rejected", "changed_at": "2026-09-12T00:00:00Z"},
                {"status": "Withdrawn", "changed_at": "2026-09-20T00:00:00Z"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Withdrawn"


def test_replace_fully_replaces_the_previous_stage_dates(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    client.put(
        f"/job-applications/{app_id}/status-history",
        json={
            "entries": [
                {"status": "Identified", "changed_at": "2026-09-01T00:00:00Z"},
                {"status": "Applied", "changed_at": "2026-09-05T00:00:00Z"},
            ]
        },
    )

    response = client.put(
        f"/job-applications/{app_id}/status-history",
        json={"entries": [{"status": "Identified", "changed_at": "2026-09-01T00:00:00Z"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Identified"
    assert [h["status"] for h in body["status_history"]] == ["Identified"]


def test_an_empty_entry_list_is_rejected(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.put(f"/job-applications/{app_id}/status-history", json={"entries": []})
    assert response.status_code == 400


def test_an_unknown_status_value_is_rejected(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    response = client.put(
        f"/job-applications/{app_id}/status-history",
        json={"entries": [{"status": "Maybe later", "changed_at": "2026-09-01T00:00:00Z"}]},
    )
    assert response.status_code == 400


def test_status_history_for_an_unknown_application_is_not_found(client: TestClient) -> None:
    response = client.put(
        "/job-applications/999/status-history",
        json={"entries": [{"status": "Identified", "changed_at": "2026-09-01T00:00:00Z"}]},
    )
    assert response.status_code == 404
