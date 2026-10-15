import sqlite3
from pathlib import Path

import pytest

from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import (
    JobFileUploadError,
    delete_job_file,
    find_duplicate_listing,
    insert_job_file,
    list_job_files,
    listing_text_sha256,
    managed_folder,
    sanitize_path_part,
)
from llmjobtracker.migrations import migrate
from llmjobtracker.storage import connect


def test_sanitize_path_part_replaces_windows_unsafe_characters() -> None:
    assert (
        sanitize_path_part('Associate - Tech & AI: "Geneva"?') == "Associate - Tech & AI_ _Geneva__"
    )


def test_sanitize_path_part_trims_trailing_dots_and_spaces() -> None:
    assert sanitize_path_part("Infomaniak. ") == "Infomaniak"


def test_managed_folder_nests_by_company_then_role(tmp_path: Path) -> None:
    folder = managed_folder(tmp_path / "files", "FIA / Motorsport", "F1 Data Scientist")
    assert folder == tmp_path / "files" / "FIA _ Motorsport" / "F1 Data Scientist"


def test_insert_and_list_job_files(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.pdf",
            stored_path="Co/Analyst/Job Listing.pdf",
        )
        insert_job_file(
            conn,
            app_id,
            kind="eml",
            name="Confirmation.eml",
            stored_path="Co/Analyst/Confirmation.eml",
            date="2026-10-01T12:03:00Z",
        )
        conn.commit()
        files = list_job_files(conn, app_id)
    finally:
        conn.close()
    assert [f["kind"] for f in files] == ["listing", "eml"]
    assert files[1]["date"] == "2026-10-01T12:03:00Z"
    assert files[0]["date"] is None


def test_delete_job_file_removes_the_row_and_the_copy_on_disk(
    db_path: Path, tmp_path: Path
) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        files_root = tmp_path / "files"
        folder = managed_folder(files_root, "Co", "Analyst")
        folder.mkdir(parents=True)
        (folder / "notes.txt").write_text("x", encoding="utf-8")
        file_id = insert_job_file(
            conn, app_id, kind="other", name="notes.txt", stored_path="Co/Analyst/notes.txt"
        )
        conn.commit()

        kind = delete_job_file(conn, files_root, app_id, file_id)

        assert kind == "other"
        assert list_job_files(conn, app_id) == []
        assert not (folder / "notes.txt").exists()
    finally:
        conn.close()


def test_delete_job_file_rejects_an_unknown_id(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        with pytest.raises(JobFileUploadError):
            delete_job_file(conn, tmp_path / "files", app_id, 999999)
    finally:
        conn.close()


def test_delete_job_file_rejects_a_file_from_a_different_application(
    db_path: Path, tmp_path: Path
) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        other_id = insert_job_application(conn, {"company": "Other", "role_title": "Role"})
        file_id = insert_job_file(
            conn, app_id, kind="other", name="notes.txt", stored_path="Co/Analyst/notes.txt"
        )
        conn.commit()

        with pytest.raises(JobFileUploadError):
            delete_job_file(conn, tmp_path / "files", other_id, file_id)
    finally:
        conn.close()


def test_job_file_rejects_an_unknown_kind(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        with pytest.raises(sqlite3.IntegrityError):
            insert_job_file(conn, app_id, kind="not_a_kind", name="x", stored_path="x")
    finally:
        conn.close()


def test_job_files_are_dropped_with_their_application(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        migrate(conn)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        insert_job_file(conn, app_id, kind="listing", name="x.pdf", stored_path="Co/Analyst/x.pdf")
        conn.commit()
        conn.execute("DELETE FROM job_applications WHERE id = ?", (app_id,))
        assert list_job_files(conn, app_id) == []
    finally:
        conn.close()


def test_listing_text_sha256_only_strips_surrounding_whitespace() -> None:
    assert listing_text_sha256("Senior Data Analyst.") == listing_text_sha256(
        "  Senior Data Analyst.  "
    )
    assert listing_text_sha256("Senior Data Analyst.") != listing_text_sha256(
        "Senior  Data Analyst."  # an internal difference still changes the fingerprint
    )


def test_find_duplicate_listing_matches_by_content_then_by_url(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        insert_job_file(
            conn,
            app_id,
            kind="listing",
            name="Job Listing.md",
            stored_path="Acme Inc/Analyst/Job Listing.md",
            sha256="content-hash-1",
            source_url="https://example.com/jobs/123",
        )
        conn.commit()

        by_content = find_duplicate_listing(conn, sha256="content-hash-1", source_url=None)
        assert by_content is not None
        assert by_content.application_id == app_id
        assert by_content.matched_by == "content"

        by_url = find_duplicate_listing(
            conn, sha256="unrelated-hash", source_url="https://example.com/jobs/123"
        )
        assert by_url is not None
        assert by_url.matched_by == "url"

        assert (
            find_duplicate_listing(
                conn, sha256="unrelated-hash", source_url="https://example.com/jobs/999"
            )
            is None
        )
    finally:
        conn.close()


def test_find_duplicate_listing_never_matches_on_company_and_role(db_path: Path) -> None:
    """D-146: two genuine postings can share a company and role title. Only content/URL count."""
    conn = connect(db_path)
    try:
        insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        conn.commit()
        assert find_duplicate_listing(conn, sha256="some-other-hash", source_url=None) is None
    finally:
        conn.close()
