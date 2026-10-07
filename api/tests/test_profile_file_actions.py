from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import localjobtracker.app as app_module
from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.profile_files import store_generated_file, store_profile_file
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def upload_one(db_path: Path, kind: str, name: str, content: bytes) -> tuple[int, Path]:
    conn = connect(db_path)
    try:
        file = store_profile_file(conn, db_path.parent, kind, name, content)
        stored = conn.execute(
            "SELECT stored_path FROM profile_files WHERE id = ?", (file.id,)
        ).fetchone()
    finally:
        conn.close()
    return file.id, db_path.parent / stored[0]


def test_removing_a_file_deletes_its_copy(client: TestClient, db_path: Path) -> None:
    file_id, copy = upload_one(db_path, "older_cv", "old.txt", b"An old CV.")
    assert copy.exists()

    response = client.delete(f"/profile/files/{file_id}")

    assert response.status_code == 200
    assert not copy.exists()
    assert client.get("/profile/files").json() == []


def test_removing_an_unknown_file_is_not_found(client: TestClient) -> None:
    assert client.delete("/profile/files/999").status_code == 404


def test_open_hands_the_copy_to_the_default_app(
    client: TestClient, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_id, copy = upload_one(db_path, "older_letter", "letter.txt", b"A letter.")
    opened: list[Path] = []
    monkeypatch.setattr(app_module, "open_in_default_app", opened.append)

    response = client.post(f"/profile/files/{file_id}/open")

    assert response.status_code == 204
    assert opened == [copy]


def test_open_of_an_unknown_file_is_not_found(client: TestClient) -> None:
    assert client.post("/profile/files/999/open").status_code == 404


def test_a_second_upload_to_a_single_file_kind_replaces_the_first(
    client: TestClient, db_path: Path
) -> None:
    _first_id, first_copy = upload_one(db_path, "own_strategy", "old.md", b"Old strategy.")
    second_id, second_copy = upload_one(db_path, "own_strategy", "new.md", b"New strategy.")

    assert not first_copy.exists()
    assert second_copy.exists()
    listed = client.get("/profile/files").json()
    assert [item["id"] for item in listed] == [second_id]


def test_a_generated_file_is_listed_and_readable_like_an_upload(
    client: TestClient, db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        file = store_generated_file(
            conn, db_path.parent, "own_full_cv_history", "full_cv_history.md", b"# Career history"
        )
    finally:
        conn.close()

    listed = client.get("/profile/files").json()
    assert len(listed) == 1
    assert listed[0]["id"] == file.id
    assert listed[0]["generated"] is True

    response = client.delete(f"/profile/files/{file.id}")
    assert response.status_code == 200
    assert client.get("/profile/files").json() == []


def test_an_upload_replaces_a_generated_file_in_the_same_slot(
    client: TestClient, db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        generated = store_generated_file(
            conn, db_path.parent, "own_questionnaire_analysis", "analysis.md", b"# Analysis"
        )
    finally:
        conn.close()
    generated_copy = (
        db_path.parent / "profile" / "own_questionnaire_analysis" / f"{generated.sha256}.md"
    )
    assert generated_copy.exists()

    uploaded_id, uploaded_copy = upload_one(
        db_path, "own_questionnaire_analysis", "mine.pdf", b"My own analysis."
    )

    assert not generated_copy.exists()
    assert uploaded_copy.exists()
    listed = client.get("/profile/files").json()
    assert [item["id"] for item in listed] == [uploaded_id]
    assert listed[0]["generated"] is False
