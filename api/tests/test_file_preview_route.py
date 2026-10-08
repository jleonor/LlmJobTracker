from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.profile_files import store_profile_file
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"
FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "profile"


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def upload(db_path: Path, kind: str, name: str, content: bytes) -> int:
    conn = connect(db_path)
    try:
        return store_profile_file(conn, db_path.parent, kind, name, content).id
    finally:
        conn.close()


def test_a_pdf_upload_previews_as_the_same_pdf_bytes(client: TestClient, db_path: Path) -> None:
    data = (FIXTURES / "cv_en.pdf").read_bytes()
    file_id = upload(db_path, "older_cv", "cv.pdf", data)

    response = client.get(f"/profile/files/{file_id}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == data


def test_a_docx_upload_previews_as_a_converted_pdf(client: TestClient, db_path: Path) -> None:
    data = (FIXTURES / "cv_en.docx").read_bytes()
    file_id = upload(db_path, "older_cv", "cv.docx", data)

    response = client.get(f"/profile/files/{file_id}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content[:5] == b"%PDF-"


def test_a_txt_upload_previews_as_text(client: TestClient, db_path: Path) -> None:
    file_id = upload(db_path, "older_cv", "notes.txt", b"Some notes.")

    response = client.get(f"/profile/files/{file_id}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Some notes."


def test_a_missing_file_is_a_404(client: TestClient) -> None:
    assert client.get("/profile/files/999999/preview").status_code == 404


def test_a_route_without_the_token_is_refused(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as bare:
        response = bare.get("/profile/files/1/preview")
    assert response.status_code == 401
