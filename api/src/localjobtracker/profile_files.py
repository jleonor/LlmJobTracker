"""Profile uploads: the CVs, letters, questionnaire and writing rules the user provides (D-07).

An upload is copied into the app's data folder, next to the database. The browser sends the
bytes, so the user's original file is never opened or changed. Each stored file is named by
its SHA-256, so the same content is never stored twice.
"""

import hashlib
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from localjobtracker.extraction import extract
from localjobtracker.migrations import PROFILE_FILE_KINDS

PROFILE_FOLDER_NAME: Final = "profile"
MAX_UPLOAD_BYTES: Final = 25 * 1024 * 1024
ALLOWED_EXTENSIONS: Final = frozenset({".pdf", ".docx", ".txt", ".md"})
# These kinds hold one file at a time (D-84). A new one, uploaded or generated, replaces it.
SINGLE_FILE_KINDS: Final = frozenset(
    {"own_full_cv_history", "own_questionnaire_analysis", "own_strategy"}
)


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
    generated: bool


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

    if kind in SINGLE_FILE_KINDS:
        # This kind holds one file. A new upload replaces whatever was there (D-84).
        _clear_kind(conn, data_folder, kind)

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
        generated=False,
    )


def list_profile_files(conn: sqlite3.Connection) -> list[ProfileFile]:
    rows = conn.execute(
        """
        SELECT id, kind, original_name, sha256, size_bytes, uploaded_at,
               extraction_status, extraction_message, generated
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


def profile_file_path(conn: sqlite3.Connection, data_folder: Path, file_id: int) -> Path | None:
    row = conn.execute("SELECT stored_path FROM profile_files WHERE id = ?", (file_id,)).fetchone()
    return None if row is None else data_folder / str(row["stored_path"])


def open_in_default_app(path: Path) -> None:
    """Open a file in the program the system uses for it (D-82)."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def delete_profile_file(conn: sqlite3.Connection, data_folder: Path, file_id: int) -> None:
    """Remove an upload and its copy (D-82).

    Later outputs keep the snapshot they were made from. They are rebuilt on the next run that
    changes what they depend on.
    """
    row = conn.execute("SELECT stored_path FROM profile_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise ProfileUploadError(404, "No such file.")
    with conn:
        conn.execute("DELETE FROM profile_files WHERE id = ?", (file_id,))
    (data_folder / str(row["stored_path"])).unlink(missing_ok=True)


def _clear_kind(conn: sqlite3.Connection, data_folder: Path, kind: str) -> None:
    """Remove every file of this kind, uploaded or generated."""
    rows = conn.execute(
        "SELECT id, stored_path FROM profile_files WHERE kind = ?", (kind,)
    ).fetchall()
    if not rows:
        return
    with conn:
        conn.execute("DELETE FROM profile_files WHERE kind = ?", (kind,))
    for row in rows:
        (data_folder / str(row["stored_path"])).unlink(missing_ok=True)


def store_generated_file(
    conn: sqlite3.Connection, data_folder: Path, kind: str, name: str, content: bytes
) -> ProfileFile:
    """Save a generated output as the one file in its kind's slot, readable like an upload (D-84).

    Used only when nothing of the user's own is there (the caller checks this). It replaces
    whatever was in the slot before, since a kind in SINGLE_FILE_KINDS holds one file.
    """
    _clear_kind(conn, data_folder, kind)
    digest = hashlib.sha256(content).hexdigest()
    relative = Path(PROFILE_FOLDER_NAME) / kind / f"{digest}.md"
    target = data_folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    uploaded_at = _now()
    text = content.decode("utf-8")
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO profile_files (
                kind, original_name, stored_path, sha256, size_bytes, uploaded_at,
                extraction_status, extraction_message, extracted_text, generated
            ) VALUES (?, ?, ?, ?, ?, ?, 'ok', NULL, ?, 1)
            """,
            (kind, name, relative.as_posix(), digest, len(content), uploaded_at, text),
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
        extraction_status="ok",
        extraction_message=None,
        generated=True,
    )


def refresh_extracted_text(conn: sqlite3.Connection, data_folder: Path) -> None:
    """Read every upload again from its stored copy (D-83). Used when an analysis starts, so a
    file uploaded before an extraction fix is read with the fixed code."""
    rows = conn.execute("SELECT id, stored_path FROM profile_files").fetchall()
    with conn:
        for row in rows:
            result = extract(data_folder / str(row["stored_path"]))
            conn.execute(
                "UPDATE profile_files SET extraction_status = ?, extraction_message = ?, "
                "extracted_text = ? WHERE id = ?",
                (result.status, result.message, result.text, row["id"]),
            )
