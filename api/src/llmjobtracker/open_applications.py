"""Open Applications: a second application type for talent pools, unsolicited CV drops and
cold outreach — not tied to a specific listing (D-249, open-application-domain.md).

Mirrors job_applications.py, trimmed: no lane, no match_score, no positioning fields, and a
smaller status set (migrations.OPEN_APPLICATION_STATUSES).
"""

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from llmjobtracker.open_application_files import (
    OpenApplicationFile,
    list_open_application_files,
    managed_folder,
)

DEFAULT_STATUS = "Identified"
# D-249: the furthest-reached of these counts as progress, same rule as job_applications.py's
# MAIN_STATUSES, trimmed to the two this entity actually uses.
MAIN_STATUSES = ("Identified", "Applied")
END_STATUSES = ("Rejected", "Withdrawn", "Expired")

_EDITABLE_COLUMNS = frozenset(
    {
        "target_name",
        "target_type",
        "contact_name",
        "contact_title",
        "contact_email",
        "angle",
        "why_this_company",
        "other_notes",
        "notes",
        "next_action",
        "due_date",
    }
)


class StatusHistoryEntry(BaseModel):
    status: str
    changed_at: str


class OpenApplication(BaseModel):
    """One row of the Open Applications table (D-250)."""

    id: int
    target_name: str | None
    target_type: str | None
    status: str
    last_updated: str
    has_company_details: bool
    has_tailored_cv: bool
    has_cover_letter: bool
    has_introduction_message: bool


class OpenApplicationDetail(BaseModel):
    """One Open Application's full record, for its detail page."""

    id: int
    target_name: str | None
    target_type: str | None
    contact_name: str | None
    contact_title: str | None
    contact_email: str | None
    angle: str | None
    why_this_company: str | None
    other_notes: str | None
    status: str
    last_updated: str
    notes: str | None
    next_action: str | None
    due_date: str | None
    status_history: list[StatusHistoryEntry]
    files: list[OpenApplicationFile]
    master_cv_profile_file_id: int | None
    master_cv_name: str | None


class OpenApplicationEdit(BaseModel):
    """A PATCH body from the Company details or Application history Edit forms. Every field is
    optional; only the ones actually sent are written (model_dump(exclude_unset=True))."""

    target_name: str | None = None
    target_type: str | None = None
    contact_name: str | None = None
    contact_title: str | None = None
    contact_email: str | None = None
    angle: str | None = None
    why_this_company: str | None = None
    other_notes: str | None = None
    notes: str | None = None
    next_action: str | None = None
    due_date: str | None = None


class MasterCvSelection(BaseModel):
    profile_file_id: int | None


class StatusHistoryEdit(BaseModel):
    entries: list[StatusHistoryEntry]


class UnknownField(Exception):
    pass


class NoStatusEntries(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_open_applications(conn: sqlite3.Connection) -> list[OpenApplication]:
    rows = conn.execute(
        """
        SELECT
            a.id, a.target_name, a.target_type, a.status,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM open_application_status_history h
                 WHERE h.open_application_id = a.id),
                a.created_at
            ) AS last_updated,
            EXISTS(
                SELECT 1 FROM open_application_files f
                WHERE f.open_application_id = a.id AND f.kind = 'tailored_cv'
            ) AS has_tailored_cv,
            EXISTS(
                SELECT 1 FROM open_application_files f
                WHERE f.open_application_id = a.id AND f.kind = 'cover_letter'
            ) AS has_cover_letter,
            EXISTS(
                SELECT 1 FROM open_application_files f
                WHERE f.open_application_id = a.id AND f.kind = 'introduction_message'
            ) AS has_introduction_message
        FROM open_applications a
        ORDER BY last_updated DESC, a.id DESC
        """
    ).fetchall()
    return [
        OpenApplication(
            id=row["id"],
            target_name=row["target_name"],
            target_type=row["target_type"],
            status=row["status"],
            last_updated=row["last_updated"],
            has_company_details=bool(row["target_name"]),
            has_tailored_cv=bool(row["has_tailored_cv"]),
            has_cover_letter=bool(row["has_cover_letter"]),
            has_introduction_message=bool(row["has_introduction_message"]),
        )
        for row in rows
    ]


def count_open_applications(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM open_applications").fetchone()[0])


def insert_open_application(conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
    """Insert a bare row — "Add Open Application" creates this, then immediately queues
    `generate_open_application_company_details` (D-251). `fields` carries whatever the user
    pre-typed; every column defaults to null when omitted."""
    now = _now()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO open_applications (
                target_name, target_type, contact_name, contact_title, contact_email,
                angle, why_this_company, other_notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("target_name"),
                fields.get("target_type"),
                fields.get("contact_name"),
                fields.get("contact_title"),
                fields.get("contact_email"),
                fields.get("angle"),
                fields.get("why_this_company"),
                fields.get("other_notes"),
                DEFAULT_STATUS,
            ),
        )
        application_id = cursor.lastrowid
        if application_id is None:
            raise RuntimeError("SQLite did not return the new row id")
        conn.execute(
            "INSERT INTO open_application_status_history "
            "(open_application_id, status, changed_at) VALUES (?, ?, ?)",
            (application_id, DEFAULT_STATUS, now),
        )
    return application_id


def delete_open_application(
    conn: sqlite3.Connection, files_root: Path, application_id: int
) -> bool:
    row = conn.execute(
        "SELECT target_name FROM open_applications WHERE id = ?", (application_id,)
    ).fetchone()
    if row is None:
        return False
    with conn:
        conn.execute("DELETE FROM open_applications WHERE id = ?", (application_id,))
    folder = managed_folder(files_root, row["target_name"], application_id)
    shutil.rmtree(folder, ignore_errors=True)
    return True


def get_open_application_detail(
    conn: sqlite3.Connection, application_id: int
) -> OpenApplicationDetail | None:
    row = conn.execute(
        """
        SELECT
            a.id, a.target_name, a.target_type, a.contact_name, a.contact_title,
            a.contact_email, a.angle, a.why_this_company, a.other_notes, a.status,
            a.notes, a.next_action, a.due_date,
            a.master_cv_profile_file_id, p.original_name AS master_cv_name,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM open_application_status_history h
                 WHERE h.open_application_id = a.id),
                a.created_at
            ) AS last_updated
        FROM open_applications a
        LEFT JOIN profile_files p ON p.id = a.master_cv_profile_file_id
        WHERE a.id = ?
        """,
        (application_id,),
    ).fetchone()
    if row is None:
        return None
    history = conn.execute(
        "SELECT status, changed_at FROM open_application_status_history "
        "WHERE open_application_id = ? ORDER BY changed_at",
        (application_id,),
    ).fetchall()
    return OpenApplicationDetail(
        id=row["id"],
        target_name=row["target_name"],
        target_type=row["target_type"],
        contact_name=row["contact_name"],
        contact_title=row["contact_title"],
        contact_email=row["contact_email"],
        angle=row["angle"],
        why_this_company=row["why_this_company"],
        other_notes=row["other_notes"],
        status=row["status"],
        last_updated=row["last_updated"],
        notes=row["notes"],
        next_action=row["next_action"],
        due_date=row["due_date"],
        status_history=[
            StatusHistoryEntry(status=h["status"], changed_at=h["changed_at"]) for h in history
        ],
        files=list_open_application_files(conn, application_id),
        master_cv_profile_file_id=row["master_cv_profile_file_id"],
        master_cv_name=row["master_cv_name"],
    )


def update_open_application(
    conn: sqlite3.Connection, application_id: int, patch: dict[str, Any]
) -> OpenApplicationDetail | None:
    if not patch:
        return get_open_application_detail(conn, application_id)
    if get_open_application_detail(conn, application_id) is None:
        return None
    assignments: list[str] = []
    params: dict[str, Any] = {"id": application_id}
    for key, value in patch.items():
        if key not in _EDITABLE_COLUMNS:
            raise UnknownField(key)
        params[key] = value
        assignments.append(f"{key} = :{key}")
    with conn:
        conn.execute(
            f"UPDATE open_applications SET {', '.join(assignments)} WHERE id = :id", params
        )
    return get_open_application_detail(conn, application_id)


def set_master_cv(
    conn: sqlite3.Connection, application_id: int, profile_file_id: int | None
) -> OpenApplicationDetail | None:
    with conn:
        conn.execute(
            "UPDATE open_applications SET master_cv_profile_file_id = ? WHERE id = ?",
            (profile_file_id, application_id),
        )
    return get_open_application_detail(conn, application_id)


def _derive_current_status(entries: list[tuple[str, str]]) -> str:
    """Mirrors job_applications._derive_current_status, trimmed to this entity's own two main
    statuses (Identified, Applied) plus the three shared end states."""
    end_entries = [entry for entry in entries if entry[0] in END_STATUSES]
    if end_entries:
        return max(end_entries, key=lambda entry: entry[1])[0]
    by_status = dict(entries)
    furthest = -1
    current = DEFAULT_STATUS
    for index, status in enumerate(MAIN_STATUSES):
        if status in by_status and index > furthest:
            furthest = index
            current = status
    return current


def replace_status_history(
    conn: sqlite3.Connection, application_id: int, entries: list[tuple[str, str]]
) -> OpenApplicationDetail | None:
    if get_open_application_detail(conn, application_id) is None:
        return None
    if not entries:
        raise NoStatusEntries()
    current_status = _derive_current_status(entries)
    with conn:
        conn.execute(
            "DELETE FROM open_application_status_history WHERE open_application_id = ?",
            (application_id,),
        )
        conn.executemany(
            "INSERT INTO open_application_status_history "
            "(open_application_id, status, changed_at) VALUES (?, ?, ?)",
            [(application_id, status, changed_at) for status, changed_at in entries],
        )
        conn.execute(
            "UPDATE open_applications SET status = ? WHERE id = ?",
            (current_status, application_id),
        )
    return get_open_application_detail(conn, application_id)
