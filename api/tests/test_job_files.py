import sqlite3
from pathlib import Path

import pytest

from localjobtracker.job_applications import insert_job_application
from localjobtracker.job_files import (
    insert_job_file,
    list_job_files,
    managed_folder,
    sanitize_path_part,
)
from localjobtracker.migrations import migrate
from localjobtracker.storage import connect


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
