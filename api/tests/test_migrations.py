import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from localjobtracker.migrations import MIGRATIONS, applied_versions, migrate, rollback
from localjobtracker.storage import connect, data_dir, database_path

ALL_VERSIONS = [m.version for m in MIGRATIONS]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path(tmp_path))
    yield connection
    connection.close()


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_migrate_creates_all_tables(conn: sqlite3.Connection) -> None:
    assert migrate(conn) == ALL_VERSIONS
    names = table_names(conn)
    assert {"job_applications", "status_history"} <= names
    assert {"claude_jobs", "claude_job_prompts", "profile_files"} <= names
    assert {"profile_outputs", "facts"} <= names
    assert "jobs" not in names
    assert applied_versions(conn) == ALL_VERSIONS


def test_migrate_twice_applies_nothing_new(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert migrate(conn) == []


def test_rollback_one_step_removes_only_the_latest_migration(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=1) == [7]
    assert {"claude_jobs", "profile_files", "facts"} <= table_names(conn)
    assert applied_versions(conn) == [1, 2, 3, 4, 5, 6]


def test_rollback_three_steps_restores_the_jobs_table(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=6) == [7, 6, 5, 4, 3, 2]
    names = table_names(conn)
    assert "jobs" in names
    assert "job_applications" not in names
    assert applied_versions(conn) == [1]


def test_rollback_all_steps_empties_the_schema(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=7) == [7, 6, 5, 4, 3, 2, 1]
    assert "jobs" not in table_names(conn)
    assert applied_versions(conn) == []


def test_migrate_again_after_rollback(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=7)
    assert migrate(conn) == ALL_VERSIONS
    assert "job_applications" in table_names(conn)


def test_existing_jobs_survive_the_upgrade_with_a_history_row(conn: sqlite3.Connection) -> None:
    # Build a database as it was after version 1 only, with one job in it.
    conn.execute(MIGRATIONS[0].up[0])
    applied_versions(conn)  # creates the ledger table
    conn.execute("INSERT INTO schema_migrations (version, name) VALUES (1, 'create jobs')")
    conn.execute(
        "INSERT INTO jobs (company, role_title, status, created_at) "
        "VALUES ('Old Co', 'Analyst', 'Applied', '2026-09-01T09:00:00Z')"
    )
    conn.commit()

    assert migrate(conn) == [2, 3, 4, 5, 6, 7]

    row = conn.execute(
        "SELECT company, status, location, work_mode FROM job_applications"
    ).fetchone()
    assert tuple(row) == ("Old Co", "Applied", None, "Unknown")
    history = conn.execute("SELECT status, changed_at FROM status_history").fetchall()
    assert [tuple(h) for h in history] == [("Applied", "2026-09-01T09:00:00Z")]


def test_status_must_be_a_known_value(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, status) "
            "VALUES ('Co', 'Analyst', 'Maybe later')"
        )


def test_work_mode_and_contract_type_must_be_known_values(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, work_mode) "
            "VALUES ('Co', 'Analyst', 'Flexible')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, contract_type) "
            "VALUES ('Co', 'Analyst', 'Freelance')"
        )


def test_match_score_must_be_between_0_and_100(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, match_score) "
            "VALUES ('Co', 'A', 101)"
        )


def test_history_rows_require_an_existing_application(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO status_history (job_application_id, status, changed_at) "
            "VALUES (999, 'Applied', '2026-10-06T09:00:00Z')"
        )


def test_data_dir_defaults_to_local_app_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LJT_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert data_dir() == tmp_path / "LocalJobTracker"


def test_data_dir_override_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "ignored"))
    monkeypatch.setenv("LJT_DATA_DIR", str(tmp_path / "override"))
    assert data_dir() == tmp_path / "override"


def test_claude_job_status_must_be_a_known_value(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claude_jobs (label, kind, status) VALUES ('x', 'profile', 'lost')"
        )


def test_profile_file_kind_must_be_a_known_value(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
            "VALUES ('cv_other', 'a.pdf', 'p/a.pdf', 'abc', 1)"
        )


def test_fact_needs_a_source_file_and_a_date(conn: sqlite3.Connection) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO profile_outputs (kind, version, body_json, input_sha256s) "
        "VALUES ('fact_sheet', 1, '{}', '')"
    )
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('master_cv', 'cv.pdf', 'profile/cv.pdf', 'abc', 10)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
            "source_location) VALUES (1, 'F-001', 'x', '', 1, 'p. 1')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
            "source_location) VALUES (1, 'F-001', 'x', '2024', 99, 'p. 1')"
        )
    conn.execute(
        "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
        "source_location) VALUES (1, 'F-001', 'x', '2024', 1, 'p. 1')"
    )
    row = conn.execute("SELECT status FROM facts WHERE fact_key = 'F-001'").fetchone()
    assert row[0] == "unverified"


def test_the_master_cv_split_is_merged_and_facts_survive(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=4)  # back to version 3, the English/French kinds
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('master_cv_fr', 'cv fr.pdf', 'profile/fr.pdf', 'f1', 10)"
    )
    file_id = conn.execute("SELECT id FROM profile_files").fetchone()[0]
    conn.execute(
        "INSERT INTO profile_outputs (kind, version, body_json, input_sha256s) "
        "VALUES ('fact_sheet', 1, '{}', '')"
    )
    conn.execute(
        "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
        "source_location) VALUES (1, 'F-001', 'x', '2024', ?, 'p. 1')",
        (file_id,),
    )
    conn.commit()

    assert migrate(conn) == [4, 5, 6, 7]
    assert conn.execute("SELECT kind FROM profile_files").fetchone()[0] == "master_cv"
    assert (
        conn.execute("SELECT COUNT(*) FROM facts WHERE source_file_id = ?", (file_id,)).fetchone()[
            0
        ]
        == 1
    )
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    rollback(conn, steps=4)
    assert conn.execute("SELECT kind FROM profile_files").fetchone()[0] == "master_cv_en"
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1


def test_own_output_uploads_are_accepted_after_migration_four(conn: sqlite3.Connection) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('own_strategy', 'my strategy.docx', 'profile/s.docx', 'abc', 10)"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
            "VALUES ('master_cv_en', 'x.pdf', 'profile/x.pdf', 'def', 10)"
        )
