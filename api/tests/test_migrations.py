import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from llmjobtracker.migrations import MIGRATIONS, applied_versions, migrate, rollback
from llmjobtracker.storage import connect, data_dir, database_path

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
    assert "profile_outputs" in names
    assert "revise_turns" in names
    assert "job_files" in names
    assert "job_revise_turns" in names
    assert "facts" not in names  # dropped by migration 10 (D-86)
    assert "jobs" not in names
    assert applied_versions(conn) == ALL_VERSIONS


def test_migrate_twice_applies_nothing_new(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert migrate(conn) == []


def test_rollback_one_step_removes_only_the_latest_migration(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=1) == [29]
    names = table_names(conn)
    assert "lanes" in names  # migration 28 still applied, just its seeded row (29) undone
    assert conn.execute("SELECT 1 FROM lanes WHERE name = 'Other'").fetchone() is None
    assert applied_versions(conn) == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
    ]


def test_rollback_three_steps_restores_the_jobs_table(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=28) == [
        29,
        28,
        27,
        26,
        25,
        24,
        23,
        22,
        21,
        20,
        19,
        18,
        17,
        16,
        15,
        14,
        13,
        12,
        11,
        10,
        9,
        8,
        7,
        6,
        5,
        4,
        3,
        2,
    ]
    names = table_names(conn)
    assert "jobs" in names
    assert "job_applications" not in names
    assert applied_versions(conn) == [1]


def test_rollback_all_steps_empties_the_schema(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert rollback(conn, steps=29) == list(range(29, 0, -1))
    assert "jobs" not in table_names(conn)
    assert applied_versions(conn) == []


def test_migrate_again_after_rollback(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=29)
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

    assert migrate(conn) == [
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
    ]

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


def test_migration_thirteen_renames_not_started_to_identified(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=17)  # back to version 12, where the status is still "Not Started"
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title, status) "
        "VALUES ('Old Co', 'Analyst', 'Not Started')"
    ).lastrowid
    conn.execute(
        "INSERT INTO status_history (job_application_id, status, changed_at) "
        "VALUES (?, 'Not Started', '2026-10-06T09:00:00Z')",
        (app_id,),
    )
    conn.commit()

    assert migrate(conn) == [13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
    row = conn.execute("SELECT status FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    assert row["status"] == "Identified"
    history = conn.execute(
        "SELECT status FROM status_history WHERE job_application_id = ?", (app_id,)
    ).fetchall()
    assert [h["status"] for h in history] == ["Identified"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, status) "
            "VALUES ('New Co', 'Analyst', 'Not Started')"
        )
    conn.rollback()  # clears the transaction the failed insert left open

    rollback(conn, steps=17)
    row = conn.execute("SELECT status FROM job_applications WHERE id = ?", (app_id,)).fetchone()
    assert row["status"] == "Not Started"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_applications (company, role_title, status) "
            "VALUES ('New Co', 'Analyst', 'Identified')"
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
    assert data_dir() == tmp_path / "LlmJobTracker"


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


def test_the_master_cv_split_is_merged(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=26)  # back to version 3, the English/French kinds
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('master_cv_fr', 'cv fr.pdf', 'profile/fr.pdf', 'f1', 10)"
    )
    conn.commit()

    assert migrate(conn) == [
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
    ]
    assert conn.execute("SELECT kind FROM profile_files").fetchone()[0] == "master_cv"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    rollback(conn, steps=26)
    assert conn.execute("SELECT kind FROM profile_files").fetchone()[0] == "master_cv_en"


def test_migration_ten_drops_the_fact_sheet(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=20)  # back to version 9, where the Fact Sheet still exists
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('own_fact_sheet', 'mine.md', 'profile/mine.md', 'f1', 10)"
    )
    output_id = conn.execute(
        "INSERT INTO profile_outputs (kind, version, body_json, input_sha256s) "
        "VALUES ('fact_sheet', 1, '{}', '')"
    ).lastrowid
    conn.execute(
        "INSERT INTO profile_outputs (kind, version, body_json, input_sha256s) "
        "VALUES ('full_cv_history', 1, '{}', '')"
    )
    file_id = conn.execute("SELECT id FROM profile_files WHERE kind = 'own_fact_sheet'").fetchone()[
        0
    ]
    conn.execute(
        "INSERT INTO facts (profile_output_id, fact_key, text, date, source_file_id, "
        "source_location) VALUES (?, 'F-001', 'x', '2024', ?, 'p. 1')",
        (output_id, file_id),
    )
    conn.commit()

    assert migrate(conn) == [
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
    ]
    assert "facts" not in table_names(conn)
    rows = conn.execute("SELECT kind FROM profile_outputs ORDER BY kind").fetchall()
    assert [tuple(row) for row in rows] == [("full_cv_history",)]
    assert conn.execute("SELECT COUNT(*) FROM profile_files").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
            "VALUES ('own_fact_sheet', 'x.md', 'profile/x.md', 'abc', 1)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_outputs (kind, version, document, input_sha256s) "
            "VALUES ('fact_sheet', 1, 'x', '')"
        )
    conn.rollback()  # clears the transaction the failed inserts left open

    rollback(conn, steps=20)
    assert "facts" in table_names(conn)
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
    conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('own_fact_sheet', 'x.md', 'profile/x.md', 'abc', 1)"
    )


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


def test_a_document_defaults_to_generated_and_rejects_an_unknown_source(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO profile_outputs (kind, version, document, input_sha256s) "
        "VALUES ('strategy', 1, 'x', '[]')"
    )
    row = conn.execute("SELECT source FROM profile_outputs").fetchone()
    assert row["source"] == "generated"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO profile_outputs (kind, version, document, input_sha256s, source) "
            "VALUES ('strategy', 2, 'x', '[]', 'uploaded')"
        )


def test_settings_has_one_row_defaulting_to_your_name(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rows = conn.execute("SELECT id, user_name FROM settings").fetchall()
    assert [tuple(row) for row in rows] == [(1, "YourName")]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO settings (id, user_name) VALUES (2, 'Someone')")


def test_revise_turns_requires_a_known_output_kind_and_a_real_job(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO claude_jobs (label, kind) VALUES ('revise', 'revise_own_full_cv_history')"
    )
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.execute(
        "INSERT INTO revise_turns (output_kind, claude_job_id, message) VALUES (?, ?, ?)",
        ("full_cv_history", job_id, "Make the summary punchier."),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO revise_turns (output_kind, claude_job_id, message) "
            "VALUES ('not_a_kind', ?, 'x')",
            (job_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO revise_turns (output_kind, claude_job_id, message) "
            "VALUES ('full_cv_history', 999999, 'x')"
        )


def test_revise_turns_are_dropped_with_their_job(conn: sqlite3.Connection) -> None:
    migrate(conn)
    conn.execute(
        "INSERT INTO claude_jobs (label, kind) VALUES ('revise', 'revise_own_full_cv_history')"
    )
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.execute(
        "INSERT INTO revise_turns (output_kind, claude_job_id, message) VALUES (?, ?, 'hi')",
        ("full_cv_history", job_id),
    )
    conn.execute("DELETE FROM claude_jobs WHERE id = ?", (job_id,))
    assert conn.execute("SELECT 1 FROM revise_turns").fetchall() == []


def test_migration_fifteen_adds_description_requirements_notes_and_job_files(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.commit()

    # requirements defaults to an empty JSON array; description and notes default to null.
    row = conn.execute(
        "SELECT description, requirements, notes FROM job_applications WHERE id = ?", (app_id,)
    ).fetchone()
    assert tuple(row) == (None, "[]", None)

    conn.execute(
        "UPDATE job_applications SET description = ?, requirements = ?, notes = ? WHERE id = ?",
        ("What the role is.", '["Python", "SQL"]', "Keep an eye on the deadline.", app_id),
    )
    file_id = conn.execute(
        "INSERT INTO job_files (job_application_id, kind, name, stored_path) "
        "VALUES (?, 'listing', 'Job Listing.pdf', 'Co/Analyst/Job Listing.pdf')",
        (app_id,),
    ).lastrowid
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_files (job_application_id, kind, name, stored_path) "
            "VALUES (?, 'not_a_kind', 'x', 'x')",
            (app_id,),
        )
    conn.rollback()  # clears the transaction the failed insert left open

    conn.execute("DELETE FROM job_applications WHERE id = ?", (app_id,))
    assert conn.execute("SELECT 1 FROM job_files WHERE id = ?", (file_id,)).fetchall() == []
    conn.commit()

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17 and 16 (layered on top)
    # and migration 15 itself
    rollback(conn, steps=15)
    assert "job_files" not in table_names(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_applications)").fetchall()}
    assert not ({"description", "requirements", "notes"} & columns)


def test_migration_sixteen_adds_master_cv_reference_and_manual_positioning_fields(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    profile_file_id = conn.execute(
        "INSERT INTO profile_files (kind, original_name, stored_path, sha256, size_bytes) "
        "VALUES ('master_cv', 'cv.pdf', 'profile/cv.pdf', 'abc', 10)"
    ).lastrowid
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.commit()

    # Defaults: no master CV chosen, empty fit/gaps/unclear, no strategy.
    row = conn.execute(
        "SELECT master_cv_profile_file_id, fit, gaps, strategy, unclear "
        "FROM job_applications WHERE id = ?",
        (app_id,),
    ).fetchone()
    assert tuple(row) == (None, "[]", "[]", None, "[]")

    conn.execute(
        "UPDATE job_applications SET master_cv_profile_file_id = ?, fit = ?, gaps = ?, "
        "strategy = ?, unclear = ? WHERE id = ?",
        (
            profile_file_id,
            '["Strong SQL"]',
            '["No retail"]',
            "Lead with the data work.",
            "[]",
            app_id,
        ),
    )
    conn.commit()

    # Deleting the referenced profile file clears the reference, not the Job Application (D-116).
    conn.execute("DELETE FROM profile_files WHERE id = ?", (profile_file_id,))
    conn.commit()
    row = conn.execute(
        "SELECT master_cv_profile_file_id FROM job_applications WHERE id = ?", (app_id,)
    ).fetchone()
    assert row["master_cv_profile_file_id"] is None

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18 and 17 (layered on top) and
    # migration 16 itself
    rollback(conn, steps=14)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_applications)").fetchall()}
    assert not ({"master_cv_profile_file_id", "fit", "gaps", "strategy", "unclear"} & columns)


def test_migration_seventeen_adds_extraction_columns_to_job_files(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    file_id = conn.execute(
        "INSERT INTO job_files (job_application_id, kind, name, stored_path) "
        "VALUES (?, 'listing', 'Job Listing.pdf', 'Co/Analyst/Job Listing.pdf')",
        (app_id,),
    ).lastrowid
    conn.commit()

    # Defaults: nothing extracted yet.
    row = conn.execute(
        "SELECT sha256, extraction_status, extraction_message, extracted_text "
        "FROM job_files WHERE id = ?",
        (file_id,),
    ).fetchone()
    assert tuple(row) == (None, None, None, None)

    conn.execute(
        "UPDATE job_files SET sha256 = ?, extraction_status = 'ok', extracted_text = ? "
        "WHERE id = ?",
        ("abc123", "Senior Data Analyst...", file_id),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE job_files SET extraction_status = 'not_a_status' WHERE id = ?", (file_id,)
        )
    conn.rollback()

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19 and 18 (layered on top) and
    # migration 17 itself
    rollback(conn, steps=13)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_files)").fetchall()}
    assert not ({"sha256", "extraction_status", "extraction_message", "extracted_text"} & columns)


def test_job_revise_turns_requires_a_known_section_kind_and_a_real_job(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.execute(
        "INSERT INTO claude_jobs (label, kind, job_application_id) "
        "VALUES ('revise', 'revise_job_details', ?)",
        (app_id,),
    )
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.commit()
    conn.execute(
        "INSERT INTO job_revise_turns (job_application_id, section_kind, claude_job_id, message) "
        "VALUES (?, 'job_details', ?, 'Drop the French requirement.')",
        (app_id, job_id),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_revise_turns "
            "(job_application_id, section_kind, claude_job_id, message) "
            "VALUES (?, 'not_a_kind', ?, 'x')",
            (app_id, job_id),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_revise_turns "
            "(job_application_id, section_kind, claude_job_id, message) "
            "VALUES (?, 'job_details', 999999, 'x')",
            (app_id,),
        )
    conn.rollback()


def test_job_revise_turns_are_dropped_with_their_job_and_clear_a_deleted_attachment(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    file_id = conn.execute(
        "INSERT INTO job_files (job_application_id, kind, name, stored_path) "
        "VALUES (?, 'eml', 'Note.eml', 'Co/Analyst/Note.eml')",
        (app_id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO claude_jobs (label, kind, job_application_id) "
        "VALUES ('revise', 'revise_application_history', ?)",
        (app_id,),
    )
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.commit()
    conn.execute(
        "INSERT INTO job_revise_turns "
        "(job_application_id, section_kind, claude_job_id, message, attachment_job_file_id) "
        "VALUES (?, 'application_history', ?, 'See the attached note.', ?)",
        (app_id, job_id, file_id),
    )
    conn.commit()

    conn.execute("DELETE FROM job_files WHERE id = ?", (file_id,))
    conn.commit()
    row = conn.execute(
        "SELECT attachment_job_file_id FROM job_revise_turns WHERE claude_job_id = ?", (job_id,)
    ).fetchone()
    assert row[0] is None  # ON DELETE SET NULL, not a cascade - the turn itself still happened

    conn.execute("DELETE FROM claude_jobs WHERE id = ?", (job_id,))
    conn.commit()
    assert conn.execute("SELECT 1 FROM job_revise_turns").fetchall() == []

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22, 21, 20 and 19 (layered on top) and
    # migration 18 itself
    rollback(conn, steps=12)
    assert "job_revise_turns" not in table_names(conn)


def test_migration_nineteen_adds_positioning_scores(conn: sqlite3.Connection) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.commit()

    row = conn.execute(
        "SELECT positioning_scores FROM job_applications WHERE id = ?", (app_id,)
    ).fetchone()
    assert row[0] == "[]"

    conn.execute(
        "UPDATE job_applications SET positioning_scores = ? WHERE id = ?",
        ('[{"text": "Strong SQL", "weight": 8, "match": 6, "reasoning": "x"}]', app_id),
    )
    conn.commit()

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22, 21 and 20 (layered on top) and migration
    # 19 itself
    rollback(conn, steps=11)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_applications)").fetchall()}
    assert "positioning_scores" not in columns


def test_migration_twenty_adds_source_url(conn: sqlite3.Connection) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    file_id = conn.execute(
        "INSERT INTO job_files (job_application_id, kind, name, stored_path) "
        "VALUES (?, 'listing', 'Job Listing.md', 'Co/Analyst/Job Listing.md')",
        (app_id,),
    ).lastrowid
    conn.commit()

    row = conn.execute("SELECT source_url FROM job_files WHERE id = ?", (file_id,)).fetchone()
    assert row[0] is None

    conn.execute(
        "UPDATE job_files SET source_url = ? WHERE id = ?",
        ("https://example.com/jobs/123", file_id),
    )
    conn.commit()

    # undoes migrations 29, 28, 27, 26, 25, 24, 23, 22 and 21 (layered on top) and migration 20
    # itself
    rollback(conn, steps=10)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_files)").fetchall()}
    assert "source_url" not in columns


def test_migration_twenty_one_adds_interview_prep(conn: sqlite3.Connection) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.commit()

    row = conn.execute(
        "SELECT interview_prep FROM job_applications WHERE id = ?", (app_id,)
    ).fetchone()
    assert row[0] == "[]"

    conn.execute(
        "UPDATE job_applications SET interview_prep = ? WHERE id = ?",
        ('[{"question": "Why this role?", "answer": "x"}]', app_id),
    )
    conn.commit()

    # undoes migrations 29, 28, 27, 26, 25, 24, 23 and 22 (layered on top) and migration 21 itself
    rollback(conn, steps=9)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_applications)").fetchall()}
    assert "interview_prep" not in columns


def test_migration_twenty_two_widens_job_revise_turns_to_interview_prep(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)
    app_id = conn.execute(
        "INSERT INTO job_applications (company, role_title) VALUES ('Co', 'Analyst')"
    ).lastrowid
    conn.execute(
        "INSERT INTO claude_jobs (label, kind, job_application_id) "
        "VALUES ('revise', 'revise_job_details', ?)",
        (app_id,),
    )
    old_job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.commit()
    # A pre-existing turn, from before this migration, survives the rebuild.
    conn.execute(
        "INSERT INTO job_revise_turns (job_application_id, section_kind, claude_job_id, message) "
        "VALUES (?, 'job_details', ?, 'Drop the French requirement.')",
        (app_id, old_job_id),
    )
    conn.commit()

    conn.execute(
        "INSERT INTO claude_jobs (label, kind, job_application_id) "
        "VALUES ('revise', 'revise_interview_prep', ?)",
        (app_id,),
    )
    new_job_id = conn.execute(
        "SELECT id FROM claude_jobs WHERE kind = 'revise_interview_prep'"
    ).fetchone()[0]
    conn.commit()
    conn.execute(
        "INSERT INTO job_revise_turns (job_application_id, section_kind, claude_job_id, message) "
        "VALUES (?, 'interview_prep', ?, 'Make the second answer shorter.')",
        (app_id, new_job_id),
    )
    conn.commit()

    rows = conn.execute("SELECT section_kind FROM job_revise_turns ORDER BY id").fetchall()
    assert [row[0] for row in rows] == ["job_details", "interview_prep"]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_revise_turns "
            "(job_application_id, section_kind, claude_job_id, message) "
            "VALUES (?, 'not_a_kind', ?, 'x')",
            (app_id, new_job_id),
        )
    conn.rollback()

    # Rolling back migration 22 rebuilds down to the narrower CHECK - which can't hold an
    # "interview_prep" row, the same way any down migration can fail against data the newer shape
    # allowed. Cleared first, since this test is checking the CHECK reverts, not that rollback
    # survives incompatible data.
    conn.execute("DELETE FROM job_revise_turns WHERE section_kind = 'interview_prep'")
    conn.commit()

    # undoes migrations 29, 28, 27, 26, 25, 24 and 23 (layered on top) and migration 22 itself
    rollback(conn, steps=8)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(job_revise_turns)").fetchall()}
    assert "section_kind" in columns
    row = conn.execute("SELECT section_kind FROM job_revise_turns").fetchone()
    assert row[0] == "job_details"  # survived the rebuild back down
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO job_revise_turns "
            "(job_application_id, section_kind, claude_job_id, message) "
            "VALUES (?, 'interview_prep', ?, 'x')",
            (app_id, old_job_id),
        )
    conn.rollback()


def test_migration_twenty_three_adds_backend_tokens_and_model_prices(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)

    # Defaults: Claude Code, reset-time retry, hourly/24-attempt fallback values, no tokens yet.
    row = conn.execute(
        "SELECT backend, retry_policy, retry_interval_minutes, retry_max_attempts FROM settings"
    ).fetchone()
    assert tuple(row) == ("claude_code", "reset_time", 60, 24)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE settings SET backend = 'chatgpt' WHERE id = 1")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE settings SET retry_policy = 'never' WHERE id = 1")
    conn.rollback()

    conn.execute(
        "UPDATE settings SET backend = 'codex', retry_policy = 'fixed_interval' WHERE id = 1"
    )
    conn.commit()

    conn.execute(
        "INSERT INTO claude_jobs (label, kind) VALUES ('listing check', 'check_job_listing_text')"
    )
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]
    conn.execute(
        "INSERT INTO claude_job_prompts (claude_job_id, position, prompt_kind, prompt_text) "
        "VALUES (?, 0, 'check_job_listing_text', 'x')",
        (job_id,),
    )
    prompt_id = conn.execute("SELECT id FROM claude_job_prompts").fetchone()[0]
    row = conn.execute(
        "SELECT input_tokens, output_tokens FROM claude_job_prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    assert tuple(row) == (None, None)
    conn.execute(
        "UPDATE claude_job_prompts SET input_tokens = 120, output_tokens = 40 WHERE id = ?",
        (prompt_id,),
    )
    conn.commit()

    conn.execute(
        "INSERT INTO model_prices (provider, model, input_price_per_token, "
        "output_price_per_token) "
        "VALUES ('codex', 'gpt-6.1-sol', 0.000003, 0.000015)"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO model_prices (provider, model) VALUES ('codex', 'gpt-6.1-sol')"
        )  # UNIQUE (provider, model)
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO model_prices (provider, model) VALUES ('chatgpt', 'gpt-6.1-sol')"
        )  # provider must be a known backend
    conn.rollback()

    # undoes migrations 29, 28, 27, 26, 25 and 24 (layered on top) and migration 23 itself
    rollback(conn, steps=7)
    assert "model_prices" not in table_names(conn)
    settings_columns = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    assert not (
        {"backend", "retry_policy", "retry_interval_minutes", "retry_max_attempts"}
        & settings_columns
    )
    prompt_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(claude_job_prompts)").fetchall()
    }
    assert not ({"input_tokens", "output_tokens"} & prompt_columns)


def test_migration_twenty_four_moves_pricing_url_to_its_own_table(
    conn: sqlite3.Connection,
) -> None:
    migrate(conn)

    # Seeded for every known backend, URL unset.
    rows = conn.execute(
        "SELECT provider, pricing_url FROM provider_pricing ORDER BY provider"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("claude_code", None), ("codex", None)]

    model_price_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(model_prices)").fetchall()
    }
    assert "pricing_url" not in model_price_columns

    conn.execute(
        "UPDATE provider_pricing SET pricing_url = ? WHERE provider = 'codex'",
        ("https://openai.com/api/pricing",),
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO provider_pricing (provider) VALUES ('chatgpt')"
        )  # provider must be a known backend
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO provider_pricing (provider) VALUES ('codex')"
        )  # one row per provider
    conn.rollback()

    # undoes migrations 29, 28, 27, 26 and 25 (layered on top) and migration 24 itself
    rollback(conn, steps=6)
    assert "provider_pricing" not in table_names(conn)
    model_price_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(model_prices)").fetchall()
    }
    assert "pricing_url" in model_price_columns


def test_migration_twenty_five_adds_retry_attempts(conn: sqlite3.Connection) -> None:
    migrate(conn)

    conn.execute("INSERT INTO claude_jobs (label, kind) VALUES ('listing check', 'x')")
    job_id = conn.execute("SELECT id FROM claude_jobs").fetchone()[0]

    row = conn.execute("SELECT retry_attempts FROM claude_jobs WHERE id = ?", (job_id,)).fetchone()
    assert row[0] == 0

    conn.execute("UPDATE claude_jobs SET retry_attempts = 3 WHERE id = ?", (job_id,))
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE claude_jobs SET retry_attempts = -1 WHERE id = ?", (job_id,))
    conn.rollback()

    # undoes migrations 29, 28, 27 and 26 (layered on top) and migration 25 itself
    rollback(conn, steps=5)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(claude_jobs)").fetchall()}
    assert "retry_attempts" not in columns


def test_migration_twenty_six_adds_selectable_models(conn: sqlite3.Connection) -> None:
    migrate(conn)

    row = conn.execute(
        "SELECT claude_code_model, codex_model FROM settings WHERE id = 1"
    ).fetchone()
    assert tuple(row) == ("claude-sonnet-5", "gpt-6.1-sol")

    conn.execute(
        "UPDATE settings SET claude_code_model = 'claude-opus-5', codex_model = 'gpt-5-codex' "
        "WHERE id = 1"
    )
    conn.commit()
    row = conn.execute(
        "SELECT claude_code_model, codex_model FROM settings WHERE id = 1"
    ).fetchone()
    assert tuple(row) == ("claude-opus-5", "gpt-5-codex")

    # undoes migrations 29, 28 and 27 (layered on top) and migration 26 itself
    rollback(conn, steps=4)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    assert not ({"claude_code_model", "codex_model"} & columns)


def test_migration_twenty_seven_adds_llm_export_path(conn: sqlite3.Connection) -> None:
    migrate(conn)

    row = conn.execute("SELECT llm_export_path FROM settings WHERE id = 1").fetchone()
    assert row[0] is None

    conn.execute("UPDATE settings SET llm_export_path = ? WHERE id = 1", ("D:\\Exports\\Tracker",))
    conn.commit()
    row = conn.execute("SELECT llm_export_path FROM settings WHERE id = 1").fetchone()
    assert row[0] == "D:\\Exports\\Tracker"

    # undoes migrations 29 and 28 (layered on top) and migration 27 itself
    rollback(conn, steps=3)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()}
    assert "llm_export_path" not in columns


def test_migration_twenty_eight_adds_lanes(conn: sqlite3.Connection) -> None:
    migrate(conn)

    # migration 29 seeds the default Other lane (D-219) - the table isn't empty.
    assert [row["name"] for row in conn.execute("SELECT name FROM lanes")] == ["Other"]

    conn.execute(
        "INSERT INTO lanes (name, description, reasoning, position) "
        "VALUES ('Data Analytics', 'Reporting and dashboard roles', 'Matches past BI work', 1)"
    )
    conn.commit()
    row = conn.execute(
        "SELECT name, description, reasoning, position FROM lanes WHERE name = 'Data Analytics'"
    ).fetchone()
    assert tuple(row) == (
        "Data Analytics",
        "Reporting and dashboard roles",
        "Matches past BI work",
        1,
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lanes (description) VALUES ('missing a name')")  # name required
    conn.rollback()

    rollback(conn, steps=2)  # undoes migration 29 (layered on top) and migration 28 itself
    names = table_names(conn)
    assert "lanes" not in names


def test_migration_twenty_nine_seeds_the_other_lane(conn: sqlite3.Connection) -> None:
    migrate(conn)

    row = conn.execute(
        "SELECT name, description, position FROM lanes WHERE name = 'Other'"
    ).fetchone()
    assert row is not None
    assert row["description"] == "Roles that don't clearly fit any of the lanes above."

    rollback(conn, steps=1)  # undoes migration 29 only
    assert "lanes" in table_names(conn)  # migration 28 still applied
    assert conn.execute("SELECT 1 FROM lanes WHERE name = 'Other'").fetchone() is None
