import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from localjobtracker.migrations import MIGRATIONS, applied_versions, migrate, rollback
from localjobtracker.storage import connect, data_dir, database_path


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path(tmp_path))
    yield connection
    connection.close()


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_migrate_creates_jobs_table(conn: sqlite3.Connection) -> None:
    assert migrate(conn) == [m.version for m in MIGRATIONS]
    assert "jobs" in table_names(conn)
    assert applied_versions(conn) == [m.version for m in MIGRATIONS]


def test_migrate_twice_applies_nothing_new(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert migrate(conn) == []


def test_rollback_removes_the_newest_migration(conn: sqlite3.Connection) -> None:
    migrate(conn)
    reverted = rollback(conn, steps=1)
    assert reverted == [MIGRATIONS[-1].version]
    assert "jobs" not in table_names(conn)
    assert applied_versions(conn) == []


def test_migrate_again_after_rollback(conn: sqlite3.Connection) -> None:
    migrate(conn)
    rollback(conn, steps=1)
    assert migrate(conn) == [m.version for m in MIGRATIONS]
    assert "jobs" in table_names(conn)


def test_jobs_rows_respect_not_null(conn: sqlite3.Connection) -> None:
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO jobs (company, role_title) VALUES (NULL, 'Analyst')")


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
