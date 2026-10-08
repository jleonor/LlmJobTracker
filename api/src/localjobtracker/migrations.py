"""Versioned SQLite migrations, each with an up and a down step.

Applied versions are recorded in `schema_migrations`. Add new migrations to the end of
MIGRATIONS and never edit one that has been applied. Each migration runs in one transaction.
"""

import sqlite3
from dataclasses import dataclass

# Allowed values, from D-44 (statuses), D-54 (work mode and contract type).
# "Not Started" as migrations 1 and 2 named it (D-05, D-44). Migration 13 renames it to
# "Identified" (D-101); this frozen tuple keeps migration 2's own SQL exactly as it was applied.
_V2_STATUSES = (
    "Not Started",
    "Applied",
    "Screening",
    "Interview",
    "Offer",
    "Rejected",
    "Withdrawn",
)
# Current values (D-101 renames "Not Started" to "Identified", matching the reference
# spreadsheet's own word for a listing that hasn't been applied to yet).
STATUSES = ("Identified", "Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn")
WORK_MODES = ("Onsite", "Hybrid", "Remote", "Unknown")
CONTRACT_TYPES = ("Full-Time", "Part-Time", "Contract/Short Term", "Other", "Unknown")

# Phase 2 values (D-62, D-64, D-66; Agent/specs/profile-steps.md).
CLAUDE_JOB_STATUSES = ("queued", "processing", "paused", "cancelled", "done", "failed")
PROMPT_STATUSES = ("queued", "running", "done", "failed", "cancelled")
# Kinds as migration 3 defined them. Kept here so that migration stays as it was applied.
_V3_FILE_KINDS = (
    "master_cv_en",
    "master_cv_fr",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
)
# Master CVs are one kind (English and French alike), and the user's own outputs have kinds of
# their own (2026-10-06, D-67, D-68). Migration 4 moves the rows over.
# Kinds as migration 4 defined them.
_V4_FILE_KINDS = (
    "master_cv",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
    "own_full_cv_history",
    "own_questionnaire_analysis",
    "own_strategy",
)
# The user may also upload their own Fact Sheet (D-70). Migration 5 adds it.
# Kinds as migration 5 defined them.
_V5_FILE_KINDS = (
    "master_cv",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
    "own_full_cv_history",
    "own_questionnaire_analysis",
    "own_strategy",
    "own_fact_sheet",
)
# The cover letter template is the user's own template for letters (Phase 5 uses it, D-71).
# Kinds as migration 9 defined them (migration 6 added the cover letter template, unchanged since).
_V9_FILE_KINDS = (*_V5_FILE_KINDS, "cover_letter_template")
EXTRACTION_STATUSES = ("ok", "no_text", "unsupported", "failed")
# Kinds as migration 9 defined them. The Fact Sheet is dropped as its own output (D-86).
_V9_OUTPUT_KINDS = ("full_cv_history", "fact_sheet", "questionnaire_analysis", "strategy")
# There is no own_fact_sheet upload kind: the career history is the one evidentiary document, and
# there is no schema for the user's own version of an output to be converted into (D-86). Migration
# 10 drops own_fact_sheet and the Fact Sheet output kind.
PROFILE_FILE_KINDS = tuple(kind for kind in _V9_FILE_KINDS if kind != "own_fact_sheet")
PROFILE_OUTPUT_KINDS = tuple(kind for kind in _V9_OUTPUT_KINDS if kind != "fact_sheet")
FACT_STATUSES = ("unverified", "verified", "rejected")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: tuple[str, ...]
    down: tuple[str, ...]
    # A migration that rebuilds a table other tables reference (a CHECK can only change that way).
    # Foreign keys are switched off for it, and checked again before it commits.
    rebuild: bool = False


_V1_JOBS = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started',
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V2_JOB_APPLICATIONS = f"""
CREATE TABLE job_applications (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ({_in_list(_V2_STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V2_STATUS_HISTORY = f"""
CREATE TABLE status_history (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(_V2_STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"

_V3_CLAUDE_JOBS = f"""
CREATE TABLE claude_jobs (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    job_application_id INTEGER REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ({_in_list(CLAUDE_JOB_STATUSES)})),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    updated_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""

_V3_CLAUDE_JOB_PROMPTS = f"""
CREATE TABLE claude_job_prompts (
    id INTEGER PRIMARY KEY,
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    prompt_kind TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ({_in_list(PROMPT_STATUSES)})),
    result_text TEXT,
    error TEXT,
    cost_usd REAL,
    duration_ms INTEGER,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE (claude_job_id, position)
)
"""

_V3_PROFILE_FILES = f"""
CREATE TABLE profile_files (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(_V3_FILE_KINDS)})),
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT ({_NOW}),
    extraction_status TEXT CHECK (
        extraction_status IS NULL OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
    ),
    extraction_message TEXT,
    extracted_text TEXT
)
"""

_V3_PROFILE_OUTPUTS = f"""
CREATE TABLE profile_outputs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(PROFILE_OUTPUT_KINDS)})),
    version INTEGER NOT NULL CHECK (version >= 1),
    claude_job_id INTEGER REFERENCES claude_jobs(id) ON DELETE SET NULL,
    body_json TEXT NOT NULL,
    input_sha256s TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (kind, version)
)
"""

_V3_FACTS = f"""
CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    profile_output_id INTEGER NOT NULL REFERENCES profile_outputs(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    text TEXT NOT NULL,
    date TEXT NOT NULL CHECK (date <> ''),
    source_file_id INTEGER NOT NULL REFERENCES profile_files(id),
    source_location TEXT NOT NULL CHECK (source_location <> ''),
    status TEXT NOT NULL DEFAULT 'unverified' CHECK (status IN ({_in_list(FACT_STATUSES)})),
    updated_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (profile_output_id, fact_key)
)
"""


def _profile_outputs_table(table: str, kinds: tuple[str, ...], column: str) -> str:
    return f"""
CREATE TABLE {table} (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(kinds)})),
    version INTEGER NOT NULL CHECK (version >= 1),
    claude_job_id INTEGER REFERENCES claude_jobs(id) ON DELETE SET NULL,
    {column} TEXT NOT NULL,
    input_sha256s TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ({_NOW}),
    UNIQUE (kind, version)
)
"""


def _profile_files_table(table: str, kinds: tuple[str, ...]) -> str:
    return f"""
CREATE TABLE {table} (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ({_in_list(kinds)})),
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT ({_NOW}),
    extraction_status TEXT CHECK (
        extraction_status IS NULL OR extraction_status IN ({_in_list(EXTRACTION_STATUSES)})
    ),
    extraction_message TEXT,
    extracted_text TEXT
)
"""


# Migration 13 (D-101): job_applications and status_history both have a status CHECK, so renaming
# the value needs a rebuild of both, same as the profile_files/profile_outputs kind renames above.
_V13_JOB_APPLICATIONS_NEW = f"""
CREATE TABLE job_applications_new (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Identified' CHECK (status IN ({_in_list(STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V13_STATUS_HISTORY_NEW = f"""
CREATE TABLE status_history_new (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

# The pre-D-101 shape, for migration 13's down step.
_V13_JOB_APPLICATIONS_OLD = f"""
CREATE TABLE job_applications_old (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    role_title TEXT NOT NULL,
    lane TEXT,
    location TEXT,
    work_mode TEXT NOT NULL DEFAULT 'Unknown' CHECK (work_mode IN ({_in_list(WORK_MODES)})),
    contract_type TEXT NOT NULL DEFAULT 'Unknown'
        CHECK (contract_type IN ({_in_list(CONTRACT_TYPES)})),
    portal_name TEXT,
    portal_url TEXT,
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ({_in_list(_V2_STATUSES)})),
    match_score REAL CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 100)),
    next_action TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_V13_STATUS_HISTORY_OLD = f"""
CREATE TABLE status_history_old (
    id INTEGER PRIMARY KEY,
    job_application_id INTEGER NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ({_in_list(_V2_STATUSES)})),
    changed_at TEXT NOT NULL
)
"""

_V14_REVISE_TURNS = f"""
CREATE TABLE revise_turns (
    id INTEGER PRIMARY KEY,
    output_kind TEXT NOT NULL CHECK (output_kind IN ({_in_list(PROFILE_OUTPUT_KINDS)})),
    claude_job_id INTEGER NOT NULL REFERENCES claude_jobs(id) ON DELETE CASCADE,
    message TEXT NOT NULL CHECK (message <> ''),
    created_at TEXT NOT NULL DEFAULT ({_NOW})
)
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create jobs",
        up=(_V1_JOBS,),
        down=("DROP TABLE jobs",),
    ),
    Migration(
        version=2,
        name="rename jobs to job_applications, add table fields and status history",
        up=(
            _V2_JOB_APPLICATIONS,
            """
            INSERT INTO job_applications
                (id, company, role_title, lane, status, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, status, next_action, due_date, created_at
            FROM jobs
            """,
            "DROP TABLE jobs",
            _V2_STATUS_HISTORY,
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
            """
            INSERT INTO status_history (job_application_id, status, changed_at)
            SELECT id, status, created_at FROM job_applications
            """,
        ),
        down=(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                lane TEXT,
                status TEXT NOT NULL DEFAULT 'Not Started',
                next_action TEXT,
                due_date TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            )
            """,
            """
            INSERT INTO jobs
                (id, company, role_title, lane, status, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, status, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE status_history",
            "DROP TABLE job_applications",
        ),
    ),
    Migration(
        version=3,
        name="add Claude Jobs, profile files, profile outputs and facts",
        up=(
            _V3_CLAUDE_JOBS,
            _V3_CLAUDE_JOB_PROMPTS,
            _V3_PROFILE_FILES,
            _V3_PROFILE_OUTPUTS,
            _V3_FACTS,
        ),
        down=(
            "DROP TABLE facts",
            "DROP TABLE profile_outputs",
            "DROP TABLE profile_files",
            "DROP TABLE claude_job_prompts",
            "DROP TABLE claude_jobs",
        ),
    ),
    Migration(
        version=4,
        name="one master CV kind, and kinds for the user's own outputs",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id,
                   CASE WHEN kind IN ('master_cv_en', 'master_cv_fr')
                        THEN 'master_cv' ELSE kind END,
                   original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            # The English/French split cannot be recovered, so master CVs go back to English.
            # The user's own outputs have no place in the older kinds, so their rows are removed,
            # along with any fact that cites one of them.
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind LIKE 'own_%')",
            "DELETE FROM profile_files WHERE kind LIKE 'own_%'",
            _profile_files_table("profile_files_old", _V3_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, CASE WHEN kind = 'master_cv' THEN 'master_cv_en' ELSE kind END,
                   original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=5,
        name="add the user's own Fact Sheet as an upload kind",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            # Facts that cite the user's own Fact Sheet go with it.
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind = 'own_fact_sheet')",
            "DELETE FROM profile_files WHERE kind = 'own_fact_sheet'",
            _profile_files_table("profile_files_old", _V4_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=6,
        name="add the cover letter template as an upload kind",
        rebuild=True,
        up=(
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
        ),
        down=(
            "DELETE FROM facts WHERE source_file_id IN "
            "(SELECT id FROM profile_files WHERE kind = 'cover_letter_template')",
            "DELETE FROM profile_files WHERE kind = 'cover_letter_template'",
            _profile_files_table("profile_files_old", _V5_FILE_KINDS),
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
        ),
    ),
    Migration(
        version=7,
        name="record the model each prompt ran on",
        up=("ALTER TABLE claude_job_prompts ADD COLUMN model TEXT",),
        down=("ALTER TABLE claude_job_prompts DROP COLUMN model",),
    ),
    Migration(
        version=8,
        name="record when a paused job resumes by itself",
        up=("ALTER TABLE claude_jobs ADD COLUMN resume_at TEXT",),
        down=("ALTER TABLE claude_jobs DROP COLUMN resume_at",),
    ),
    Migration(
        version=9,
        name="mark a profile file as generated, not uploaded",
        up=("ALTER TABLE profile_files ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",),
        down=("ALTER TABLE profile_files DROP COLUMN generated",),
    ),
    Migration(
        version=10,
        name="drop the Fact Sheet: three documents, not four (D-85, D-86)",
        rebuild=True,
        up=(
            "DROP TABLE facts",
            "DELETE FROM profile_files WHERE kind = 'own_fact_sheet'",
            _profile_files_table("profile_files_new", PROFILE_FILE_KINDS),
            # The table builder predates migration 9's column; add it here too (as 9 itself did).
            "ALTER TABLE profile_files_new ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",
            """
            INSERT INTO profile_files_new
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text, generated)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text, generated
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_new RENAME TO profile_files",
            "DELETE FROM profile_outputs WHERE kind = 'fact_sheet'",
            _profile_outputs_table("profile_outputs_new", PROFILE_OUTPUT_KINDS, "document"),
            """
            INSERT INTO profile_outputs_new
                (id, kind, version, claude_job_id, document, input_sha256s, created_at)
            SELECT id, kind, version, claude_job_id, body_json, input_sha256s, created_at
            FROM profile_outputs
            """,
            "DROP TABLE profile_outputs",
            "ALTER TABLE profile_outputs_new RENAME TO profile_outputs",
        ),
        down=(
            # The Fact Sheet's own rows and every fact cannot be recovered (same as migrations 4
            # and 5's irreversible splits): they were deleted going up, not merely hidden.
            _profile_outputs_table("profile_outputs_old", _V9_OUTPUT_KINDS, "body_json"),
            """
            INSERT INTO profile_outputs_old
                (id, kind, version, claude_job_id, body_json, input_sha256s, created_at)
            SELECT id, kind, version, claude_job_id, document, input_sha256s, created_at
            FROM profile_outputs
            """,
            "DROP TABLE profile_outputs",
            "ALTER TABLE profile_outputs_old RENAME TO profile_outputs",
            _profile_files_table("profile_files_old", _V9_FILE_KINDS),
            "ALTER TABLE profile_files_old ADD COLUMN generated INTEGER NOT NULL DEFAULT 0",
            """
            INSERT INTO profile_files_old
                (id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                 extraction_status, extraction_message, extracted_text, generated)
            SELECT id, kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                   extraction_status, extraction_message, extracted_text, generated
            FROM profile_files
            """,
            "DROP TABLE profile_files",
            "ALTER TABLE profile_files_old RENAME TO profile_files",
            _V3_FACTS,
        ),
    ),
    Migration(
        version=11,
        name="record whether a document was generated or copied from your own file",
        up=(
            "ALTER TABLE profile_outputs ADD COLUMN source TEXT NOT NULL DEFAULT 'generated' "
            "CHECK (source IN ('generated', 'imported'))",
        ),
        down=("ALTER TABLE profile_outputs DROP COLUMN source",),
    ),
    Migration(
        version=12,
        name="add a settings table for the user's display name",
        up=(
            "CREATE TABLE settings ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "user_name TEXT NOT NULL DEFAULT 'YourName'"
            ")",
            "INSERT INTO settings (id, user_name) VALUES (1, 'YourName')",
        ),
        down=("DROP TABLE settings",),
    ),
    Migration(
        version=13,
        name="rename the Not Started status to Identified (D-101)",
        rebuild=True,
        up=(
            _V13_JOB_APPLICATIONS_NEW,
            """
            INSERT INTO job_applications_new
                (id, company, role_title, lane, location, work_mode, contract_type,
                 portal_name, portal_url, status, match_score, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, location, work_mode, contract_type,
                   portal_name, portal_url,
                   CASE WHEN status = 'Not Started' THEN 'Identified' ELSE status END,
                   match_score, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_new RENAME TO job_applications",
            _V13_STATUS_HISTORY_NEW,
            """
            INSERT INTO status_history_new (id, job_application_id, status, changed_at)
            SELECT id, job_application_id,
                   CASE WHEN status = 'Not Started' THEN 'Identified' ELSE status END,
                   changed_at
            FROM status_history
            """,
            "DROP TABLE status_history",
            "ALTER TABLE status_history_new RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
        down=(
            _V13_JOB_APPLICATIONS_OLD,
            """
            INSERT INTO job_applications_old
                (id, company, role_title, lane, location, work_mode, contract_type,
                 portal_name, portal_url, status, match_score, next_action, due_date, created_at)
            SELECT id, company, role_title, lane, location, work_mode, contract_type,
                   portal_name, portal_url,
                   CASE WHEN status = 'Identified' THEN 'Not Started' ELSE status END,
                   match_score, next_action, due_date, created_at
            FROM job_applications
            """,
            "DROP TABLE job_applications",
            "ALTER TABLE job_applications_old RENAME TO job_applications",
            _V13_STATUS_HISTORY_OLD,
            """
            INSERT INTO status_history_old (id, job_application_id, status, changed_at)
            SELECT id, job_application_id,
                   CASE WHEN status = 'Identified' THEN 'Not Started' ELSE status END,
                   changed_at
            FROM status_history
            """,
            "DROP TABLE status_history",
            "ALTER TABLE status_history_old RENAME TO status_history",
            "CREATE INDEX status_history_by_job ON status_history (job_application_id, changed_at)",
        ),
    ),
    Migration(
        version=14,
        name="add revise_turns for the Revise (LLM) chat (D-106)",
        up=(
            _V14_REVISE_TURNS,
            "CREATE INDEX revise_turns_by_kind ON revise_turns (output_kind, id)",
        ),
        down=("DROP TABLE revise_turns",),
    ),
)

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    conn.execute(_LEDGER)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row[0]) for row in rows]


def _run(
    conn: sqlite3.Connection,
    statements: tuple[str, ...],
    ledger_sql: str,
    params: tuple[object, ...],
    rebuild: bool = False,
) -> None:
    if rebuild:
        # Must be set outside a transaction. It is restored below, whatever happens.
        conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        if rebuild and conn.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("The rebuild would leave rows with broken references.")
        conn.execute(ledger_sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if rebuild:
            conn.execute("PRAGMA foreign_keys = ON")


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration not yet recorded. Returns the versions applied now."""
    done = set(applied_versions(conn))
    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in done:
            continue
        _run(
            conn,
            migration.up,
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
            migration.rebuild,
        )
        applied.append(migration.version)
    return applied


def rollback(conn: sqlite3.Connection, steps: int = 1) -> list[int]:
    """Undo the newest `steps` applied migrations. Returns the versions reverted."""
    by_version = {m.version: m for m in MIGRATIONS}
    reverted: list[int] = []
    for version in sorted(applied_versions(conn), reverse=True)[:steps]:
        migration = by_version[version]
        _run(
            conn,
            migration.down,
            "DELETE FROM schema_migrations WHERE version = ?",
            (version,),
            migration.rebuild,
        )
        reverted.append(version)
    return reverted
