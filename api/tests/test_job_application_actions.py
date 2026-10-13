from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import localjobtracker.app as app_module
from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.job_applications import insert_job_application
from localjobtracker.job_files import job_file_text
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

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
    from localjobtracker.profile_files import store_profile_file

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


def test_an_uploaded_listing_is_extracted_but_other_kinds_are_not(
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

    other = client.post(
        f"/job-applications/{app_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"Reminder: follow up Friday.",
    ).json()
    assert other["extraction_status"] is None

    conn = connect(db_path)
    try:
        text = job_file_text(conn, listing["id"])
        assert text is not None
        assert "Senior Data Analyst" in text.text
        assert "Accept all" not in text.text
        assert job_file_text(conn, other["id"]) is not None
        assert job_file_text(conn, other["id"]).text == ""  # type: ignore[union-attr]
    finally:
        conn.close()

    detail = client.get(f"/job-applications/{app_id}").json()
    by_id = {f["id"]: f for f in detail["files"]}
    assert by_id[listing["id"]]["extraction_status"] == "ok"
    assert by_id[other["id"]]["extraction_status"] is None


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


# --- Edit ------------------------------------------------------------------------------------


def test_edit_updates_only_the_fields_sent(client: TestClient, db_path: Path) -> None:
    app_id = add_application(db_path)
    client.patch(f"/job-applications/{app_id}", json={"location": "Geneva, CH"})

    response = client.patch(f"/job-applications/{app_id}", json={"notes": "Follow up Friday."})

    assert response.status_code == 200
    body = response.json()
    assert body["location"] == "Geneva, CH"
    assert body["notes"] == "Follow up Friday."


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
                {"question": "Why this role?", "answer": "The SQL work lines up."},
                {"question": "Biggest gap?", "answer": "No retail experience."},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interview_prep"] == [
        {"question": "Why this role?", "answer": "The SQL work lines up."},
        {"question": "Biggest gap?", "answer": "No retail experience."},
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
