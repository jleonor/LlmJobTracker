import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.profile_files import MAX_UPLOAD_BYTES, profile_folder
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"
SYNTHETIC_CV = b"%PDF-1.4 synthetic cv bytes"


@pytest.fixture
def upload_client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def upload(client: TestClient, kind: str, name: str, content: bytes) -> Response:
    response: Response = client.post(
        f"/profile/files/{kind}",
        content=content,
        headers={"X-File-Name": quote(name)},
    )
    return response


def rows(db_path: Path) -> list[sqlite3.Row]:
    conn = connect(db_path)
    try:
        return conn.execute("SELECT * FROM profile_files ORDER BY id").fetchall()
    finally:
        conn.close()


def test_upload_copies_the_bytes_into_app_data(upload_client: TestClient, db_path: Path) -> None:
    response = upload(upload_client, "master_cv", "Master CV EN.pdf", SYNTHETIC_CV)

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "master_cv"
    assert body["original_name"] == "Master CV EN.pdf"
    assert body["sha256"] == hashlib.sha256(SYNTHETIC_CV).hexdigest()
    assert body["size_bytes"] == len(SYNTHETIC_CV)

    row = rows(db_path)[0]
    stored = db_path.parent / row["stored_path"]
    assert stored.parent == profile_folder(db_path.parent) / "master_cv"
    assert stored.read_bytes() == SYNTHETIC_CV


def test_the_original_file_is_not_changed_by_an_upload(
    upload_client: TestClient, tmp_path: Path
) -> None:
    original = tmp_path / "outside" / "cv.docx"
    original.parent.mkdir()
    original.write_bytes(b"original bytes")
    before = (original.read_bytes(), original.stat().st_mtime_ns)

    upload(upload_client, "older_cv", "cv.docx", original.read_bytes())

    assert (original.read_bytes(), original.stat().st_mtime_ns) == before


def test_the_same_file_twice_in_one_kind_is_refused(upload_client: TestClient) -> None:
    upload(upload_client, "older_cv", "cv.txt", b"same content")
    again = upload(upload_client, "older_cv", "cv.txt", b"same content")
    assert again.status_code == 409


def test_a_second_questionnaire_upload_replaces_the_first(upload_client: TestClient) -> None:
    first = upload(upload_client, "questionnaire", "old.txt", b"old answers")
    second = upload(upload_client, "questionnaire", "new.txt", b"new answers")
    assert first.status_code == 201
    assert second.status_code == 201
    listed = upload_client.get("/profile/files").json()
    assert [item["original_name"] for item in listed] == ["new.txt"]


def test_a_second_writing_rules_upload_replaces_the_first(upload_client: TestClient) -> None:
    upload(upload_client, "writing_rules", "old.md", b"# Old rules")
    upload(upload_client, "writing_rules", "new.md", b"# New rules")
    listed = upload_client.get("/profile/files").json()
    assert [item["original_name"] for item in listed] == ["new.md"]


def test_a_second_cover_letter_template_upload_replaces_the_first(
    upload_client: TestClient,
) -> None:
    upload(upload_client, "cover_letter_template", "old.docx", SYNTHETIC_CV)
    upload(upload_client, "cover_letter_template", "new.docx", SYNTHETIC_CV + b"x")
    listed = upload_client.get("/profile/files").json()
    assert [item["original_name"] for item in listed] == ["new.docx"]


def test_the_same_file_in_another_kind_is_allowed(upload_client: TestClient) -> None:
    first = upload(upload_client, "older_cv", "cv.txt", b"shared text")
    second = upload(upload_client, "older_letter", "letter.txt", b"shared text")
    assert first.status_code == 201
    assert second.status_code == 201


def test_unknown_kind_is_refused(upload_client: TestClient) -> None:
    response = upload(upload_client, "cv_other", "cv.pdf", SYNTHETIC_CV)
    assert response.status_code == 400


def test_unsupported_extension_is_refused(upload_client: TestClient) -> None:
    response = upload(upload_client, "older_cv", "cv.exe", SYNTHETIC_CV)
    assert response.status_code == 415


def test_empty_file_is_refused(upload_client: TestClient) -> None:
    response = upload(upload_client, "older_cv", "cv.pdf", b"")
    assert response.status_code == 400


def test_oversized_file_is_refused(upload_client: TestClient) -> None:
    response = upload(upload_client, "older_cv", "big.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))
    assert response.status_code == 413


def test_a_path_in_the_name_is_reduced_to_the_file_name(upload_client: TestClient) -> None:
    response = upload(upload_client, "older_cv", "..\\secret\\cv.pdf", SYNTHETIC_CV)
    assert response.json()["original_name"] == "cv.pdf"


def test_writing_rules_are_stored_as_their_own_kind(
    upload_client: TestClient, db_path: Path
) -> None:
    response = upload(upload_client, "writing_rules", "my rules.md", b"# My rules")
    assert response.status_code == 201
    assert rows(db_path)[0]["kind"] == "writing_rules"


def test_list_returns_the_uploads_without_their_bytes(upload_client: TestClient) -> None:
    upload(upload_client, "master_cv", "cv fr.pdf", SYNTHETIC_CV)
    listed = upload_client.get("/profile/files").json()
    assert [item["original_name"] for item in listed] == ["cv fr.pdf"]
    assert "stored_path" not in listed[0]


def test_upload_without_the_token_is_rejected(db_path: Path) -> None:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as bare:
        response = bare.post("/profile/files/older_cv", content=SYNTHETIC_CV)
        assert response.status_code == 401


def test_cover_letter_template_is_stored_as_its_own_kind(
    upload_client: TestClient, db_path: Path
) -> None:
    response = upload(upload_client, "cover_letter_template", "letter template.docx", SYNTHETIC_CV)
    assert response.status_code == 201
    assert rows(db_path)[0]["kind"] == "cover_letter_template"


# --- reveal_in_file_manager (D-160, D-161) -----------------------------------------------------


def test_reveal_on_windows_quotes_the_path_as_a_single_command_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live bug (2026-10-12): passed as a list (`["explorer", f"/select,{path}"]`), subprocess's
    own Windows quoting wraps the whole `/select,<path>` token in quotes whenever the path has a
    space - which is almost always, since a managed folder is named after the company/role
    (D-146). explorer.exe can't parse that and silently falls back to its default folder instead
    of the one requested. Passing one pre-built string, with the path quoted on its own right
    after the comma, is the syntax explorer.exe actually wants."""
    import subprocess as subprocess_module
    import sys

    from llmjobtracker import profile_files

    monkeypatch.setattr(sys, "platform", "win32")
    calls: list[object] = []
    monkeypatch.setattr(subprocess_module, "run", lambda *args, **kwargs: calls.append(args))

    path = Path(r"C:\Users\jonat\files\Acme Inc\Senior Analyst\listing.txt")
    profile_files.reveal_in_file_manager(path)

    assert calls == [
        (r'explorer /select,"C:\Users\jonat\files\Acme Inc\Senior Analyst\listing.txt"',)
    ]
