"""Versioned SQLite migrations, each with an up and a down step.

Applied versions are recorded in `schema_migrations`. Add new migrations to the end of
MIGRATIONS and never edit one that has been applied.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    up: str
    down: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="create jobs",
        up="""
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
        down="DROP TABLE jobs",
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


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration not yet recorded. Returns the versions applied now."""
    done = set(applied_versions(conn))
    applied: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in done:
            continue
        with conn:
            conn.execute(migration.up)
            conn.execute(
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
        with conn:
            conn.execute(migration.down)
            conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
        reverted.append(version)
    return reverted
