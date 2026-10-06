import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import localjobtracker.app as app_module
from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.profile_files import store_profile_file
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
    assert response.json() == {"removed_facts": 0}
    assert not copy.exists()
    assert client.get("/profile/files").json() == []


def test_removing_a_file_removes_the_facts_that_cite_it(client: TestClient, db_path: Path) -> None:
    file_id, _copy = upload_one(db_path, "master_cv", "cv.txt", b"A CV.")
    conn = connect(db_path)
    try:
        with conn:
            output = conn.execute(
                "INSERT INTO profile_outputs (kind, version, body_json, input_sha256s) "
                "VALUES ('fact_sheet', 1, ?, '[]')",
                (json.dumps({"facts": [], "conflicts": []}),),
            ).lastrowid
            conn.execute(
                "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
                "source_location) VALUES (?, 'F-001', 'A fact.', '2020', ?, 'Line 2')",
                (output, file_id),
            )
    finally:
        conn.close()

    response = client.delete(f"/profile/files/{file_id}")

    assert response.json() == {"removed_facts": 1}


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
