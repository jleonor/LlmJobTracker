"""Versioned SQLite migrations, each with an up and a down step.

Applied versions are recorded in `schema_migrations`. Add new migrations to the end of
MIGRATIONS and never edit one that has been applied. Each migration runs in one transaction.
"""

import sqlite3
from dataclasses import dataclass

# Allowed values, from D-44 (statuses), D-54 (work mode and contract type).
STATUSES = ("Not Started", "Applied", "Screening", "Interview", "Offer", "Rejected", "Withdrawn")
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
PROFILE_FILE_KINDS = (
    "master_cv",
    "older_cv",
    "older_letter",
    "questionnaire",
    "writing_rules",
    "own_full_cv_history",
    "own_questionnaire_analysis",
    "own_strategy",
)
EXTRACTION_STATUSES = ("ok", "no_text", "unsupported", "failed")
PROFILE_OUTPUT_KINDS = ("full_cv_history", "fact_sheet", "questionnaire_analysis", "strategy")
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
    status TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN ({_in_list(STATUSES)})),
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
    status TEXT NOT NULL CHECK (status IN ({_in_list(STATUSES)})),
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
