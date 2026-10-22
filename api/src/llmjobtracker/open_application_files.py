"""An Open Application's own files: Tailored CV, Cover letter, Introduction message, and
anything else filed under Additional files (open-application-domain.md). Table
`open_application_files`. Mirrors job_files.py, trimmed: no eml/msg/html kinds, no source_url
dedup (there is no listing to dedup against), and `subject` instead (introduction_message only).
"""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Final

from pydantic import BaseModel

# Characters Windows rejects in a file or folder name (same as job_files.py's own).
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

MAX_UPLOAD_BYTES: Final = 25 * 1024 * 1024
ALLOWED_EXTENSIONS: Final = frozenset({".pdf", ".docx", ".txt", ".md"})


class OpenApplicationFileUploadError(Exception):
    """A rejected upload. `status` is the HTTP status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class OpenApplicationFile(BaseModel):
    id: int
    kind: str
    name: str
    subject: str | None = None
    extraction_status: str | None = None
    extraction_message: str | None = None


def sanitize_path_part(value: str) -> str:
    return _UNSAFE_CHARS.sub("_", value).rstrip(" .")


def managed_folder(files_root: Path, target_name: str | None, application_id: int) -> Path:
    """`%LOCALAPPDATA%\\LlmJobTracker\\files\\Open Applications\\<target name> (<id>)`.

    Keyed by id rather than name alone (unlike job_files.managed_folder's company/role_title
    pair) — Target name may be inferred and later revised (D-251), and a stable folder means no
    rename-on-edit dance is needed the way update_job_application's role_title edit needs one.
    """
    label = sanitize_path_part(target_name or "Untitled")
    return files_root / "Open Applications" / f"{label} ({application_id})"


def insert_open_application_file(
    conn: sqlite3.Connection,
    application_id: int,
    *,
    kind: str,
    name: str,
    stored_path: str,
    subject: str | None = None,
    sha256: str | None = None,
    extraction_status: str | None = None,
    extraction_message: str | None = None,
    extracted_text: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO open_application_files (
            open_application_id, kind, name, stored_path, subject,
            sha256, extraction_status, extraction_message, extracted_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            kind,
            name,
            stored_path,
            subject,
            sha256,
            extraction_status,
            extraction_message,
            extracted_text,
        ),
    )
    file_id = cursor.lastrowid
    if file_id is None:
        raise RuntimeError("SQLite did not return the new row id")
    return file_id


def list_open_application_files(
    conn: sqlite3.Connection, application_id: int
) -> list[OpenApplicationFile]:
    rows = conn.execute(
        "SELECT id, kind, name, subject, extraction_status, extraction_message "
        "FROM open_application_files WHERE open_application_id = ? ORDER BY id",
        (application_id,),
    ).fetchall()
    return [
        OpenApplicationFile(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            subject=row["subject"],
            extraction_status=row["extraction_status"],
            extraction_message=row["extraction_message"],
        )
        for row in rows
    ]


def clear_open_application_files_of_kind(
    conn: sqlite3.Connection, files_root: Path, application_id: int, kind: str
) -> None:
    """Mirrors job_files.clear_job_files_of_kind: removes every file of this kind before a fresh
    Generate writes the new one (D-115's one-current-file-per-kind convention, except `other`,
    which this is never called for)."""
    rows = conn.execute(
        "SELECT id, stored_path FROM open_application_files "
        "WHERE open_application_id = ? AND kind = ?",
        (application_id, kind),
    ).fetchall()
    if not rows:
        return
    with conn:
        conn.execute(
            "DELETE FROM open_application_files WHERE open_application_id = ? AND kind = ?",
            (application_id, kind),
        )
    for row in rows:
        (files_root / str(row["stored_path"])).unlink(missing_ok=True)


def delete_open_application_file(
    conn: sqlite3.Connection, files_root: Path, application_id: int, file_id: int
) -> str:
    row = conn.execute(
        "SELECT open_application_id, stored_path, kind FROM open_application_files WHERE id = ?",
        (file_id,),
    ).fetchone()
    if row is None or row["open_application_id"] != application_id:
        raise OpenApplicationFileUploadError(404, "No such file.")
    with conn:
        conn.execute("DELETE FROM open_application_files WHERE id = ?", (file_id,))
    (files_root / str(row["stored_path"])).unlink(missing_ok=True)
    return str(row["kind"])


def open_application_file_path(
    conn: sqlite3.Connection, files_root: Path, file_id: int
) -> Path | None:
    row = conn.execute(
        "SELECT stored_path FROM open_application_files WHERE id = ?", (file_id,)
    ).fetchone()
    return None if row is None else files_root / str(row["stored_path"])


def latest_open_application_file_of_kind(
    conn: sqlite3.Connection, application_id: int, kind: str
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, name, stored_path, subject, sha256, extraction_status, "
        "extraction_message, extracted_text "
        "FROM open_application_files WHERE open_application_id = ? AND kind = ? "
        "ORDER BY id DESC LIMIT 1",
        (application_id, kind),
    ).fetchone()
    return row


def _unique_target(folder: Path, name: str, content: bytes) -> tuple[Path, str]:
    target = folder / name
    if not target.exists():
        return target, name
    stem, suffix = Path(name).stem, Path(name).suffix
    unique_name = f"{stem} ({hashlib.sha256(content).hexdigest()[:8]}){suffix}"
    return folder / unique_name, unique_name


def write_generated_open_application_file(
    conn: sqlite3.Connection,
    files_root: Path,
    application_id: int,
    target_name: str | None,
    kind: str,
    name: str,
    content: bytes,
    *,
    subject: str | None = None,
    extracted_text: str | None = None,
) -> OpenApplicationFile:
    """Mirrors job_files.write_generated_job_file: saves a Claude-generated result as the one
    file in its kind's slot, replacing whatever was there."""
    clear_open_application_files_of_kind(conn, files_root, application_id, kind)
    folder = managed_folder(files_root, target_name, application_id)
    folder.mkdir(parents=True, exist_ok=True)
    target, final_name = _unique_target(folder, name, content)
    target.write_bytes(content)
    extraction_status = "ok" if extracted_text is not None else None
    file_id = insert_open_application_file(
        conn,
        application_id,
        kind=kind,
        name=final_name,
        stored_path=target.relative_to(files_root).as_posix(),
        subject=subject,
        sha256=hashlib.sha256(content).hexdigest(),
        extraction_status=extraction_status,
        extracted_text=extracted_text,
    )
    conn.commit()
    return OpenApplicationFile(
        id=file_id,
        kind=kind,
        name=final_name,
        subject=subject,
        extraction_status=extraction_status,
        extraction_message=None,
    )


def store_open_application_file(
    conn: sqlite3.Connection,
    files_root: Path,
    application_id: int,
    target_name: str | None,
    original_name: str,
    content: bytes,
) -> OpenApplicationFile:
    """An Additional files upload (kind `other`) — mirrors job_files.store_job_file, trimmed to
    this app's own four allowed extensions (no eml/msg/html: Open Applications file emails and
    saved listing pages nowhere, D-253)."""
    name = (original_name or "").strip().replace("\\", "/").rsplit("/", 1)[-1][:200] or "upload"
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise OpenApplicationFileUploadError(415, "Use a PDF, DOCX, TXT or MD file.")
    if not content:
        raise OpenApplicationFileUploadError(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise OpenApplicationFileUploadError(413, "The file is larger than 25 MB.")

    folder = managed_folder(files_root, target_name, application_id)
    folder.mkdir(parents=True, exist_ok=True)
    target, name = _unique_target(folder, name, content)
    target.write_bytes(content)

    file_id = insert_open_application_file(
        conn,
        application_id,
        kind="other",
        name=name,
        stored_path=target.relative_to(files_root).as_posix(),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    conn.commit()
    return OpenApplicationFile(id=file_id, kind="other", name=name)
