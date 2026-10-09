"""A Job Application's own files: the listing, CVs, cover letters, the positioning breakdown
document, and filed emails (Agent/specs/files.md, D-111/D-112). Table `job_files`.
"""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from localjobtracker.migrations import JOB_FILE_KINDS

# Characters Windows rejects in a file or folder name (files.md).
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

MAX_UPLOAD_BYTES: Final = 25 * 1024 * 1024
# Unlike profile_files.ALLOWED_EXTENSIONS, this also takes .eml/.msg (D-116's Emails subsection).
ALLOWED_EXTENSIONS: Final = frozenset({".pdf", ".docx", ".txt", ".md", ".eml", ".msg"})


class JobFileUploadError(Exception):
    """A rejected upload. `status` is the HTTP status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class JobApplicationFile(BaseModel):
    id: int
    kind: str
    name: str
    date: str | None


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


def _safe_name(name: str) -> str:
    """The file name as the user gave it, without any folder part. Used only for display."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base[:200] or "upload"


def job_file_path(conn: sqlite3.Connection, files_root: Path, file_id: int) -> Path | None:
    row = conn.execute("SELECT stored_path FROM job_files WHERE id = ?", (file_id,)).fetchone()
    return None if row is None else files_root / str(row["stored_path"])


def store_job_file(
    conn: sqlite3.Connection,
    files_root: Path,
    application_id: int,
    kind: str,
    original_name: str,
    content: bytes,
) -> JobApplicationFile:
    """Copy an uploaded file into the application's managed folder and record it.

    Unlike profile_files.store_profile_file, the file keeps its own readable name on disk
    (files.md: "the folder holds real, openable files with readable names... not generated ids"),
    not a content hash — a clash with an existing name gets a short suffix instead of overwriting.
    No text extraction (D-109): a Job Application's own files aren't read by Claude yet.
    """
    if kind not in JOB_FILE_KINDS:
        raise JobFileUploadError(400, f"Unknown file kind: {kind}.")
    app_row = conn.execute(
        "SELECT company, role_title FROM job_applications WHERE id = ?", (application_id,)
    ).fetchone()
    if app_row is None:
        raise JobFileUploadError(404, "No such Job Application.")

    name = _safe_name(original_name)
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise JobFileUploadError(415, "Use a PDF, DOCX, TXT, MD, EML or MSG file.")
    if not content:
        raise JobFileUploadError(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise JobFileUploadError(413, "The file is larger than 25 MB.")

    folder = managed_folder(files_root, app_row["company"], app_row["role_title"])
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if target.exists():
        stem, suffix = Path(name).stem, Path(name).suffix
        name = f"{stem} ({hashlib.sha256(content).hexdigest()[:8]}){suffix}"
        target = folder / name
    target.write_bytes(content)

    file_id = insert_job_file(
        conn,
        application_id,
        kind=kind,
        name=name,
        stored_path=target.relative_to(files_root).as_posix(),
    )
    conn.commit()
    return JobApplicationFile(id=file_id, kind=kind, name=name, date=None)
