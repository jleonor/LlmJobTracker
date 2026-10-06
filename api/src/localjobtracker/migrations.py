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


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: tuple[str, ...]
    down: tuple[str, ...]


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
) -> None:
    conn.execute("BEGIN")
    try:
        for statement in statements:
            conn.execute(statement)
        conn.execute(ledger_sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
        )
        applied.append(migration.version)
    return applied


def rollback(conn: sqlite3.Connection, steps: int = 1) -> list[int]:
    """Undo the newest `steps` applied migrations. Returns the versions reverted."""
    by_version = {m.version: m for m in MIGRATIONS}
    reverted: list[int] = []
    for version in sorted(applied_versions(conn), reverse=True)[:steps]:
        migration = by_version[version]
        _run(conn, migration.down, "DELETE FROM schema_migrations WHERE version = ?", (version,))
        reverted.append(version)
    return reverted
