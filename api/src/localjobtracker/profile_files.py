"""Profile uploads: the CVs, letters, questionnaire and writing rules the user provides (D-07).

An upload is copied into the app's data folder, next to the database. The browser sends the
bytes, so the user's original file is never opened or changed. Each stored file is named by
its SHA-256, so the same content is never stored twice.
"""

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from localjobtracker.extraction import extract
from localjobtracker.migrations import PROFILE_FILE_KINDS

PROFILE_FOLDER_NAME: Final = "profile"
MAX_UPLOAD_BYTES: Final = 25 * 1024 * 1024
ALLOWED_EXTENSIONS: Final = frozenset({".pdf", ".docx", ".txt", ".md"})


class ProfileUploadError(Exception):
    """A rejected upload. `status` is the HTTP status the API should return."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ProfileFile(BaseModel):
    id: int
    kind: str
    original_name: str
    sha256: str
    size_bytes: int
    uploaded_at: str
    extraction_status: str | None
    extraction_message: str | None


class ProfileFileText(BaseModel):
    id: int
    extraction_status: str | None
    extraction_message: str | None
    text: str


def profile_folder(data_folder: Path) -> Path:
    return data_folder / PROFILE_FOLDER_NAME


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_name(name: str) -> str:
    """The file name as the user gave it, without any folder part. Used only for display."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base[:200] or "upload"


def store_profile_file(
    conn: sqlite3.Connection,
    data_folder: Path,
    kind: str,
    original_name: str,
    content: bytes,
) -> ProfileFile:
    if kind not in PROFILE_FILE_KINDS:
        raise ProfileUploadError(400, f"Unknown file kind: {kind}.")
    name = _safe_name(original_name)
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ProfileUploadError(415, "Use a PDF, DOCX, TXT or MD file.")
    if not content:
        raise ProfileUploadError(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ProfileUploadError(413, "The file is larger than 25 MB.")

    digest = hashlib.sha256(content).hexdigest()
    existing = conn.execute(
        "SELECT 1 FROM profile_files WHERE kind = ? AND sha256 = ?", (kind, digest)
    ).fetchone()
    if existing is not None:
        raise ProfileUploadError(409, "This file is already uploaded.")

    relative = Path(PROFILE_FOLDER_NAME) / kind / f"{digest}{extension}"
    target = data_folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(content)

    uploaded_at = _now()
    result = extract(target)
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO profile_files (
                kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                extraction_status, extraction_message, extracted_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                name,
                relative.as_posix(),
                digest,
                len(content),
                uploaded_at,
                result.status,
                result.message,
                result.text,
            ),
        )
    file_id = cursor.lastrowid
    if file_id is None:
        raise RuntimeError("SQLite did not return the new row id")
    return ProfileFile(
        id=file_id,
        kind=kind,
        original_name=name,
        sha256=digest,
        size_bytes=len(content),
        uploaded_at=uploaded_at,
        extraction_status=result.status,
        extraction_message=result.message,
    )


def list_profile_files(conn: sqlite3.Connection) -> list[ProfileFile]:
    rows = conn.execute(
        """
        SELECT id, kind, original_name, sha256, size_bytes, uploaded_at,
               extraction_status, extraction_message
        FROM profile_files ORDER BY kind, id
        """
    ).fetchall()
    return [ProfileFile(**dict(row)) for row in rows]


def profile_file_text(conn: sqlite3.Connection, file_id: int) -> ProfileFileText | None:
    row = conn.execute(
        """
        SELECT id, extraction_status, extraction_message, extracted_text
        FROM profile_files WHERE id = ?
        """,
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return ProfileFileText(
        id=row["id"],
        extraction_status=row["extraction_status"],
        extraction_message=row["extraction_message"],
        text=row["extracted_text"] or "",
    )
