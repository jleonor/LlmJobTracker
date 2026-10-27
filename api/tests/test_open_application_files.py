from pathlib import Path

from llmjobtracker.open_application_files import (
    OpenApplicationFileUploadError,
    delete_open_application_file,
    latest_open_application_file_of_kind,
    list_open_application_files,
    managed_folder,
    store_open_application_file,
    write_generated_open_application_file,
)
from llmjobtracker.open_applications import insert_open_application
from llmjobtracker.storage import connect


def test_write_generated_file_replaces_a_prior_one_of_the_same_kind(
    db_path: Path, tmp_path: Path
) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})

    write_generated_open_application_file(
        conn, files_root, application_id, "Acme", "introduction_message", "Intro.md", b"first"
    )
    write_generated_open_application_file(
        conn, files_root, application_id, "Acme", "introduction_message", "Intro.md", b"second"
    )

    files = list_open_application_files(conn, application_id)
    intro_files = [f for f in files if f.kind == "introduction_message"]
    assert len(intro_files) == 1

    latest = latest_open_application_file_of_kind(conn, application_id, "introduction_message")
    assert latest is not None
    assert latest["extraction_status"] is None  # no extracted_text was passed


def test_write_generated_file_stores_subject_and_extracted_text(
    db_path: Path, tmp_path: Path
) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})

    write_generated_open_application_file(
        conn,
        files_root,
        application_id,
        "Acme",
        "introduction_message",
        "Intro.md",
        b"Hello there",
        subject="Following up on your talent pool",
        extracted_text="Hello there",
    )

    latest = latest_open_application_file_of_kind(conn, application_id, "introduction_message")
    assert latest is not None
    assert latest["subject"] == "Following up on your talent pool"
    assert latest["extracted_text"] == "Hello there"
    assert latest["extraction_status"] == "ok"


def test_store_upload_rejects_a_disallowed_extension(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    try:
        store_open_application_file(
            conn, tmp_path / "files", application_id, "Acme", "photo.png", b"not really a photo"
        )
        raised = False
    except OpenApplicationFileUploadError as error:
        raised = True
        assert error.status == 415
    assert raised


def test_store_upload_accepts_an_eml_file(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    result = store_open_application_file(
        conn, files_root, application_id, "Acme", "recruiter.eml", b"From: a@b.com\n\nHi"
    )
    assert result.kind == "other"
    assert (managed_folder(files_root, "Acme", application_id) / "recruiter.eml").exists()


def test_store_upload_keeps_the_managed_folder_keyed_by_id(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    result = store_open_application_file(
        conn, files_root, application_id, "Acme", "notes.txt", b"some notes"
    )
    assert result.kind == "other"
    expected_folder = managed_folder(files_root, "Acme", application_id)
    assert (expected_folder / "notes.txt").read_bytes() == b"some notes"


def test_delete_removes_the_row_and_the_file_on_disk(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    uploaded = store_open_application_file(
        conn, files_root, application_id, "Acme", "notes.txt", b"some notes"
    )
    kind = delete_open_application_file(conn, files_root, application_id, uploaded.id)
    assert kind == "other"
    assert list_open_application_files(conn, application_id) == []
