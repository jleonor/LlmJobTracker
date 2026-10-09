"""A Job Application's own files: the listing, CVs, cover letters, the positioning breakdown
document, and filed emails (Agent/specs/files.md, D-111/D-112). Table `job_files`.
"""

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from localjobtracker.extraction import extract
from localjobtracker.migrations import JOB_FILE_KINDS

# Characters Windows rejects in a file or folder name (files.md).
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

MAX_UPLOAD_BYTES: Final = 25 * 1024 * 1024
# Unlike profile_files.ALLOWED_EXTENSIONS, this also takes .eml/.msg (D-116's Emails subsection)
# and .html/.htm (a saved listing page, D-122, job-llm-steps.md).
ALLOWED_EXTENSIONS: Final = frozenset(
    {".pdf", ".docx", ".txt", ".md", ".eml", ".msg", ".html", ".htm"}
)
# Only the listing is read back as prompt input today (job-llm-steps.md, Job details and
# Positioning analysis). Extracting every kind would mean extracting .eml/.msg too, which
# file_preview.py already parses for its own purpose at preview time, not at upload time.
EXTRACTED_KINDS: Final = frozenset({"listing"})


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
    # Set only for an extracted kind (EXTRACTED_KINDS); null for everything else, the same as a
    # file that has never been read. Mirrors profile_files.ProfileFile's own two fields; the
    # extracted text itself is read server-side (job_file_text below), not served here.
    extraction_status: str | None = None
    extraction_message: str | None = None


def sanitize_path_part(value: str) -> str:
    """One folder or file name component, safe to put under the managed files folder."""
    return _UNSAFE_CHARS.sub("_", value).rstrip(" .")


def managed_folder(files_root: Path, company: str, role_title: str) -> Path:
    """`%LOCALAPPDATA%\\LocalJobTracker\\files\\<company>\\<role_title>` (files.md)."""
    return files_root / sanitize_path_part(company) / sanitize_path_part(role_title)


class JobFileText(BaseModel):
    id: int
    extraction_status: str | None
    extraction_message: str | None
    text: str


def insert_job_file(
    conn: sqlite3.Connection,
    job_application_id: int,
    *,
    kind: str,
    name: str,
    stored_path: str,
    date: str | None = None,
    sha256: str | None = None,
    extraction_status: str | None = None,
    extraction_message: str | None = None,
    extracted_text: str | None = None,
) -> int:
    """Record one file already copied into the managed folder. Returns its id."""
    cursor = conn.execute(
        """
        INSERT INTO job_files (
            job_application_id, kind, name, stored_path, date,
            sha256, extraction_status, extraction_message, extracted_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_application_id,
            kind,
            name,
            stored_path,
            date,
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


def list_job_files(conn: sqlite3.Connection, job_application_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, kind, name, stored_path, date, extraction_status, extraction_message "
        "FROM job_files WHERE job_application_id = ? ORDER BY id",
        (job_application_id,),
    ).fetchall()


def clear_job_files_of_kind(
    conn: sqlite3.Connection, files_root: Path, application_id: int, kind: str
) -> None:
    """Remove every file of this kind for one application (mirrors profile_files._clear_kind).

    Used by a Generate (LLM) step whose kind holds at most one current file (D-115: Listing,
    Tailored CV, Cover letter) before it writes the new one.
    """
    rows = conn.execute(
        "SELECT id, stored_path FROM job_files WHERE job_application_id = ? AND kind = ?",
        (application_id, kind),
    ).fetchall()
    if not rows:
        return
    with conn:
        conn.execute(
            "DELETE FROM job_files WHERE job_application_id = ? AND kind = ?",
            (application_id, kind),
        )
    for row in rows:
        (files_root / str(row["stored_path"])).unlink(missing_ok=True)


def job_file_text(conn: sqlite3.Connection, file_id: int) -> JobFileText | None:
    """The extracted text for one of a Job Application's own files (D-122), for a later prompt
    to read as context (job-llm-steps.md) — mirrors profile_files.profile_file_text."""
    row = conn.execute(
        "SELECT id, extraction_status, extraction_message, extracted_text "
        "FROM job_files WHERE id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return JobFileText(
        id=row["id"],
        extraction_status=row["extraction_status"],
        extraction_message=row["extraction_message"],
        text=row["extracted_text"] or "",
    )


def _safe_name(name: str) -> str:
    """The file name as the user gave it, without any folder part. Used only for display."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return base[:200] or "upload"


def job_file_path(conn: sqlite3.Connection, files_root: Path, file_id: int) -> Path | None:
    row = conn.execute("SELECT stored_path FROM job_files WHERE id = ?", (file_id,)).fetchone()
    return None if row is None else files_root / str(row["stored_path"])


def latest_job_file_of_kind(
    conn: sqlite3.Connection, application_id: int, kind: str
) -> sqlite3.Row | None:
    """The one current file of this kind for an application (D-115: Listing, Tailored CV, Cover
    letter and the positioning breakdown each hold at most one), or None."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, name, stored_path, extraction_status, extraction_message, extracted_text "
        "FROM job_files WHERE job_application_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
        (application_id, kind),
    ).fetchone()
    return row


def _unique_target(folder: Path, name: str, content: bytes) -> tuple[Path, str]:
    """`folder / name`, or a short-suffixed variant if something unrelated already has that name
    (files.md's shared-folder layout isn't keyed by kind) — never overwrites."""
    target = folder / name
    if not target.exists():
        return target, name
    stem, suffix = Path(name).stem, Path(name).suffix
    unique_name = f"{stem} ({hashlib.sha256(content).hexdigest()[:8]}){suffix}"
    return folder / unique_name, unique_name


def write_generated_job_file(
    conn: sqlite3.Connection,
    files_root: Path,
    application_id: int,
    kind: str,
    name: str,
    content: bytes,
    *,
    extracted_text: str | None = None,
) -> JobApplicationFile:
    """Save a Claude-generated result as the one file in its kind's slot, replacing whatever was
    there (D-115) — used by job_pipeline.py's Generate (LLM) steps, the same way
    store_generated_file does for a profile document (D-84).

    `extracted_text` is the file's own text when it has one to read back later (a Markdown
    listing or positioning breakdown, read as itself); left out for a binary result (a Tailored
    CV or Cover letter `.docx`, D-130), which isn't prompt input for anything downstream.
    """
    clear_job_files_of_kind(conn, files_root, application_id, kind)
    app_row = conn.execute(
        "SELECT company, role_title FROM job_applications WHERE id = ?", (application_id,)
    ).fetchone()
    if app_row is None:
        raise JobFileUploadError(404, "No such Job Application.")
    folder = managed_folder(files_root, app_row["company"], app_row["role_title"])
    folder.mkdir(parents=True, exist_ok=True)
    target, final_name = _unique_target(folder, name, content)
    target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    extraction_status = "ok" if extracted_text is not None else None
    file_id = insert_job_file(
        conn,
        application_id,
        kind=kind,
        name=final_name,
        stored_path=target.relative_to(files_root).as_posix(),
        sha256=digest,
        extraction_status=extraction_status,
        extracted_text=extracted_text,
    )
    conn.commit()
    return JobApplicationFile(
        id=file_id,
        kind=kind,
        name=final_name,
        date=None,
        extraction_status=extraction_status,
        extraction_message=None,
    )


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
    Only an EXTRACTED_KINDS upload (the listing) is read for its text (D-122): a Job
    Application's other files aren't prompt input yet (D-109).
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
        raise JobFileUploadError(415, "Use a PDF, DOCX, TXT, MD, HTML, EML or MSG file.")
    if not content:
        raise JobFileUploadError(400, "The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise JobFileUploadError(413, "The file is larger than 25 MB.")

    folder = managed_folder(files_root, app_row["company"], app_row["role_title"])
    folder.mkdir(parents=True, exist_ok=True)
    target, name = _unique_target(folder, name, content)
    target.write_bytes(content)

    extraction_status = extraction_message = extracted_text = None
    sha256 = None
    if kind in EXTRACTED_KINDS:
        sha256 = hashlib.sha256(content).hexdigest()
        result = extract(target)
        extraction_status, extraction_message, extracted_text = (
            result.status,
            result.message,
            result.text,
        )

    file_id = insert_job_file(
        conn,
        application_id,
        kind=kind,
        name=name,
        stored_path=target.relative_to(files_root).as_posix(),
        sha256=sha256,
        extraction_status=extraction_status,
        extraction_message=extraction_message,
        extracted_text=extracted_text,
    )
    conn.commit()
    return JobApplicationFile(
        id=file_id,
        kind=kind,
        name=name,
        date=None,
        extraction_status=extraction_status,
        extraction_message=extraction_message,
    )
