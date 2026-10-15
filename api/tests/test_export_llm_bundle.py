import shutil
import sqlite3
import sys
import winreg
from pathlib import Path

import pytest

import llmjobtracker.export_llm_bundle as export_module
from llmjobtracker.export_llm_bundle import (
    LLM_APP_SCHEMES,
    LlmExportBundleBusy,
    _url_scheme_registered,
    export_llm_bundle,
    llm_app_status,
    llm_export_folder,
)
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file, managed_folder
from llmjobtracker.migrations import migrate
from llmjobtracker.profile_files import store_profile_file
from llmjobtracker.settings import save_settings
from llmjobtracker.storage import connect


def _migrated_conn(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn)
    return conn


def _set_export_path(conn: sqlite3.Connection, path: Path) -> None:
    """Points Settings' llm_export_path (D-212) at a tmp_path location, so tests never touch
    the real Downloads folder the unconfigured default would otherwise resolve to."""
    save_settings(
        conn,
        "YourName",
        "claude_code",
        "reset_time",
        60,
        24,
        "claude-sonnet-5",
        "gpt-6.1-sol",
        str(path),
    )


# --- Where the export goes (D-212) --------------------------------------------------------------


def test_llm_export_folder_defaults_to_downloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert llm_export_folder(None) == tmp_path / "Downloads" / "LlmJobTrackerExport"


def test_llm_export_folder_defaults_when_the_configured_path_is_blank(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert llm_export_folder("") == tmp_path / "Downloads" / "LlmJobTrackerExport"


def test_llm_export_folder_uses_the_configured_path_exactly(tmp_path: Path) -> None:
    configured = tmp_path / "wherever" / "MyExport"
    assert llm_export_folder(str(configured)) == configured


# --- Building the bundle -------------------------------------------------------------------------


def test_export_writes_a_seed_file_and_db_snapshot(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)

        bundle_root = export_llm_bundle(conn, db_path.parent)

        assert bundle_root == target
        seed_text = (bundle_root / "seed.md").read_text(encoding="utf-8")
        assert "YourName" in seed_text
        assert "CREATE TABLE" in seed_text
        assert "sqlite3" in seed_text
        assert (bundle_root / "tracker.db").exists()
    finally:
        conn.close()


def test_export_copies_job_files_under_files_company_role(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        app_id = insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        folder = managed_folder(db_path.parent / "files", "Co", "Analyst")
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

        bundle_root = export_llm_bundle(conn, db_path.parent)

        exported_file = bundle_root / "files" / "Co" / "Analyst" / "Job Listing.md"
        assert exported_file.read_text(encoding="utf-8") == "Some listing text."
        assert not exported_file.is_symlink()
    finally:
        conn.close()


def test_export_skips_a_job_with_no_files_yet(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})

        bundle_root = export_llm_bundle(conn, db_path.parent)

        assert not (bundle_root / "files" / "Co").exists()
    finally:
        conn.close()


def test_export_copies_profile_files(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        store_profile_file(conn, db_path.parent, "master_cv", "CV.pdf", b"cv bytes")
        conn.commit()

        bundle_root = export_llm_bundle(conn, db_path.parent)

        copied = list((bundle_root / "profile" / "master_cv").iterdir())
        assert len(copied) == 1
        assert copied[0].read_bytes() == b"cv bytes"
        assert not copied[0].is_symlink()
    finally:
        conn.close()


def test_export_db_snapshot_does_not_change_when_the_live_db_changes_later(
    db_path: Path,
) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        save_settings(
            conn,
            "Before",
            "claude_code",
            "reset_time",
            60,
            24,
            "claude-sonnet-5",
            "gpt-6.1-sol",
            str(target),
        )
        bundle_root = export_llm_bundle(conn, db_path.parent)

        save_settings(
            conn,
            "After",
            "claude_code",
            "reset_time",
            60,
            24,
            "claude-sonnet-5",
            "gpt-6.1-sol",
            str(target),
        )

        snapshot_conn = connect(bundle_root / "tracker.db")
        try:
            row = snapshot_conn.execute("SELECT user_name FROM settings WHERE id = 1").fetchone()
            assert row["user_name"] == "Before"
        finally:
            snapshot_conn.close()
    finally:
        conn.close()


def test_writing_into_the_exported_db_never_reaches_the_live_database(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        bundle_root = export_llm_bundle(conn, db_path.parent)

        snapshot_conn = connect(bundle_root / "tracker.db")
        try:
            snapshot_conn.execute("UPDATE settings SET user_name = 'Tampered' WHERE id = 1")
            snapshot_conn.commit()
        finally:
            snapshot_conn.close()

        live_row = conn.execute("SELECT user_name FROM settings WHERE id = 1").fetchone()
        assert live_row["user_name"] != "Tampered"
    finally:
        conn.close()


def test_export_rebuilds_from_scratch_each_time(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        bundle_root = export_llm_bundle(conn, db_path.parent)
        stale = bundle_root / "stale.txt"
        stale.write_text("leftover", encoding="utf-8")

        export_llm_bundle(conn, db_path.parent)

        assert not stale.exists()
    finally:
        conn.close()


def test_export_skips_a_duplicate_company_role_folder_without_erroring(db_path: Path) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        insert_job_application(conn, {"company": "Co", "role_title": "Analyst"})
        folder = managed_folder(db_path.parent / "files", "Co", "Analyst")
        folder.mkdir(parents=True)
        (folder / "x.txt").write_text("x", encoding="utf-8")

        bundle_root = export_llm_bundle(conn, db_path.parent)

        assert (bundle_root / "files" / "Co" / "Analyst" / "x.txt").read_text(
            encoding="utf-8"
        ) == "x"
    finally:
        conn.close()


def test_export_never_leaves_the_target_half_wiped_if_the_build_crashes(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old approach (wipe the live target, then rebuild in place) could crash between
    those two steps and leave the target empty. Staging-then-swap means a crash while building
    leaves the previous export untouched."""
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        export_llm_bundle(conn, db_path.parent)
        assert (target / "seed.md").exists()

        monkeypatch.setattr(
            export_module,
            "_write_seed_file",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with pytest.raises(RuntimeError):
            export_llm_bundle(conn, db_path.parent)

        # The previous export is still intact - never wiped in anticipation of a rebuild that
        # didn't finish.
        assert (target / "seed.md").exists()
        assert (target / "tracker.db").exists()
    finally:
        conn.close()


def test_export_raises_a_clear_error_when_the_target_cannot_be_replaced(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = _migrated_conn(db_path)
    try:
        target = db_path.parent / "export-target"
        _set_export_path(conn, target)
        export_llm_bundle(conn, db_path.parent)

        # Simulate a locked file: rmtree can't actually clear the old target.
        monkeypatch.setattr(shutil, "rmtree", lambda *args, **kwargs: None)

        with pytest.raises(LlmExportBundleBusy):
            export_llm_bundle(conn, db_path.parent)
    finally:
        conn.close()


# --- Desktop-app install status (D-210) --------------------------------------------------------


def test_url_scheme_registered_true_when_the_registry_key_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeKey:
        def __enter__(self) -> "FakeKey":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(winreg, "OpenKey", lambda *args, **kwargs: FakeKey())
    monkeypatch.setattr(winreg, "QueryValueEx", lambda *args, **kwargs: ("", 1))

    assert _url_scheme_registered("claude") is True


def test_url_scheme_registered_false_when_the_registry_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError()

    monkeypatch.setattr(winreg, "OpenKey", raise_not_found)

    assert _url_scheme_registered("no-such-scheme") is False


def test_url_scheme_registered_assumes_available_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")

    assert _url_scheme_registered("claude") is True


def test_llm_app_status_reports_both_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export_module, "_url_scheme_registered", lambda scheme: scheme == "claude")

    result = llm_app_status()

    assert set(result.keys()) == set(LLM_APP_SCHEMES.keys())
    assert result["claude_code"].installed is True
    assert result["codex"].installed is False
    assert "Not installed" in result["codex"].detail
