"""A Job Application's own files: the listing, CVs, cover letters, the positioning breakdown
document, and filed emails (Agent/specs/files.md, D-111/D-112). Table `job_files`.
"""

import re
import sqlite3
from pathlib import Path

# Characters Windows rejects in a file or folder name (files.md).
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_path_part(value: str) -> str:
    """One folder or file name component, safe to put under the managed files folder."""
    return _UNSAFE_CHARS.sub("_", value).rstrip(" .")


def managed_folder(files_root: Path, company: str, role_title: str) -> Path:
    """`%LOCALAPPDATA%\\LocalJobTracker\\files\\<company>\\<role_title>` (files.md)."""
    return files_root / sanitize_path_part(company) / sanitize_path_part(role_title)


def insert_job_file(
    conn: sqlite3.Connection,
    job_application_id: int,
    *,
    kind: str,
    name: str,
    stored_path: str,
    date: str | None = None,
) -> int:
    """Record one file already copied into the managed folder. Returns its id."""
    cursor = conn.execute(
        """
        INSERT INTO job_files (job_application_id, kind, name, stored_path, date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_application_id, kind, name, stored_path, date),
    )
    file_id = cursor.lastrowid
    if file_id is None:
        raise RuntimeError("SQLite did not return the new row id")
    return file_id


def list_job_files(conn: sqlite3.Connection, job_application_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, kind, name, stored_path, date FROM job_files "
        "WHERE job_application_id = ? ORDER BY id",
        (job_application_id,),
    ).fetchall()
