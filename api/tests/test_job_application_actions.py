from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import localjobtracker.app as app_module
from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.job_applications import insert_job_application
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"
FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"


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
