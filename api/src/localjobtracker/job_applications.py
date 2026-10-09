"""Job Applications: one tracker row per listing, and their status history (D-44, D-45, D-46).

A Claude Job is a different thing (D-49). It is not stored here.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from localjobtracker.job_files import JobApplicationFile, list_job_files

DEFAULT_STATUS = "Identified"

# Columns a PATCH may touch, grouped the way the job page's three Edit forms are (D-116). fit,
# gaps and unclear are stored as JSON; the rest are plain columns. match_score and status are not
# here: match_score is meant to be code-computed from weights/matches (D-47), not typed in by
# hand, and a status change goes through status_history, not a bare column write (D-45).
_EDITABLE_JSON_COLUMNS = frozenset({"requirements", "fit", "gaps", "unclear"})
_EDITABLE_COLUMNS = frozenset(
    {
        "portal_name",
        "portal_url",
        "location",
        "work_mode",
        "contract_type",
        "description",
        "notes",
        "next_action",
        "due_date",
        "strategy",
    }
)


class JobApplication(BaseModel):
    """One row of the Applications table, in the D-46 column order."""

    id: int
    company: str
    role_title: str
    lane: str | None
    location: str | None
    status: str
    last_updated: str
    match_score: float | None


class StatusHistoryEntry(BaseModel):
    status: str
    changed_at: str


class JobApplicationDetail(BaseModel):
    """One Job Application's full record, for the job page (D-56, D-113, D-116)."""

    id: int
    company: str
    role_title: str
    lane: str | None
    location: str | None
    status: str
    last_updated: str
    match_score: float | None
    portal_name: str | None
    portal_url: str | None
    work_mode: str
    contract_type: str
    description: str | None
    requirements: list[str]
    notes: str | None
    next_action: str | None
    due_date: str | None
    status_history: list[StatusHistoryEntry]
    files: list[JobApplicationFile]
    # D-116: a reference to a Profile page master CV (profile_files.id), not a copied job file —
    # the Profile page is where it's previewed and opened.
    master_cv_profile_file_id: int | None
    master_cv_name: str | None
    # Manual positioning fields (D-116): typed in by the user for now, through Positioning
    # analysis's Edit button. match_score stays separate (D-47).
    fit: list[str]
    gaps: list[str]
    strategy: str | None
    unclear: list[str]


class JobApplicationEdit(BaseModel):
    """A PATCH body from one of the job page's Edit forms (D-116).

    Every field is optional; only the ones the caller actually sends are written
    (`model_dump(exclude_unset=True)`), so omitting a field leaves it untouched, and a form only
    ever needs to send the fields its own section owns.
    """

    portal_name: str | None = None
    portal_url: str | None = None
    location: str | None = None
    work_mode: str | None = None
    contract_type: str | None = None
    description: str | None = None
    requirements: list[str] | None = None
    notes: str | None = None
    next_action: str | None = None
    due_date: str | None = None
    fit: list[str] | None = None
    gaps: list[str] | None = None
    strategy: str | None = None
    unclear: list[str] | None = None


class MasterCvSelection(BaseModel):
    """D-116: which Profile page master CV (by profile_files.id) this application uses, or None
    to clear the selection."""

    profile_file_id: int | None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_job_applications(conn: sqlite3.Connection) -> list[JobApplication]:
    rows = conn.execute(
        """
        SELECT
            a.id, a.company, a.role_title, a.lane, a.location, a.status, a.match_score,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM status_history h WHERE h.job_application_id = a.id),
                a.created_at
            ) AS last_updated
        FROM job_applications a
        ORDER BY last_updated DESC, a.id DESC
        """
    ).fetchall()
    return [JobApplication(**dict(row)) for row in rows]


def insert_job_application(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    history: list[tuple[str, str]] | None = None,
) -> int:
    """Insert one application and its status history in one transaction.

    `history` is a list of (status, changed_at) pairs, oldest first. The current status is
    the last one. With no history, the application starts as Identified, dated now.
    """
    steps = history or [(DEFAULT_STATUS, _now())]
    current_status = steps[-1][0]
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO job_applications (
                company, role_title, lane, location, work_mode, contract_type,
                portal_name, portal_url, status, match_score, next_action, due_date,
                description, requirements, notes
            ) VALUES (
                :company, :role_title, :lane, :location, :work_mode, :contract_type,
                :portal_name, :portal_url, :status, :match_score, :next_action, :due_date,
                :description, :requirements, :notes
            )
            """,
            {
                "company": row["company"],
                "role_title": row["role_title"],
                "lane": row.get("lane"),
                "location": row.get("location"),
                "work_mode": row.get("work_mode", "Unknown"),
                "contract_type": row.get("contract_type", "Unknown"),
                "portal_name": row.get("portal_name"),
                "portal_url": row.get("portal_url"),
                "status": current_status,
                "match_score": row.get("match_score"),
                "next_action": row.get("next_action"),
                "due_date": row.get("due_date"),
                "description": row.get("description"),
                "requirements": json.dumps(row.get("requirements", [])),
                "notes": row.get("notes"),
            },
        )
        application_id = cursor.lastrowid
        if application_id is None:
            raise RuntimeError("SQLite did not return the new row id")
        conn.executemany(
            "INSERT INTO status_history (job_application_id, status, changed_at) VALUES (?, ?, ?)",
            [(application_id, status, changed_at) for status, changed_at in steps],
        )
    return application_id


def count_job_applications(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM job_applications").fetchone()[0])


def get_job_application_detail(
    conn: sqlite3.Connection, application_id: int
) -> JobApplicationDetail | None:
    """The job page's full record for one application (D-113, D-116), or None if it's missing."""
    row = conn.execute(
        """
        SELECT
            a.id, a.company, a.role_title, a.lane, a.location, a.work_mode, a.contract_type,
            a.portal_name, a.portal_url, a.status, a.match_score, a.next_action, a.due_date,
            a.description, a.requirements, a.notes,
            a.master_cv_profile_file_id, p.original_name AS master_cv_name,
            a.fit, a.gaps, a.strategy, a.unclear,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM status_history h WHERE h.job_application_id = a.id),
                a.created_at
            ) AS last_updated
        FROM job_applications a
        LEFT JOIN profile_files p ON p.id = a.master_cv_profile_file_id
        WHERE a.id = ?
        """,
        (application_id,),
    ).fetchone()
    if row is None:
        return None

    history = conn.execute(
        "SELECT status, changed_at FROM status_history "
        "WHERE job_application_id = ? ORDER BY changed_at",
        (application_id,),
    ).fetchall()
    files = list_job_files(conn, application_id)

    return JobApplicationDetail(
        id=row["id"],
        company=row["company"],
        role_title=row["role_title"],
        lane=row["lane"],
        location=row["location"],
        status=row["status"],
        last_updated=row["last_updated"],
        match_score=row["match_score"],
        portal_name=row["portal_name"],
        portal_url=row["portal_url"],
        work_mode=row["work_mode"],
        contract_type=row["contract_type"],
        description=row["description"],
        requirements=json.loads(row["requirements"]),
        notes=row["notes"],
        next_action=row["next_action"],
        due_date=row["due_date"],
        status_history=[
            StatusHistoryEntry(status=h["status"], changed_at=h["changed_at"]) for h in history
        ],
        files=[
            JobApplicationFile(id=f["id"], kind=f["kind"], name=f["name"], date=f["date"])
            for f in files
        ],
        master_cv_profile_file_id=row["master_cv_profile_file_id"],
        master_cv_name=row["master_cv_name"],
        fit=json.loads(row["fit"]),
        gaps=json.loads(row["gaps"]),
        strategy=row["strategy"],
        unclear=json.loads(row["unclear"]),
    )


class UnknownField(Exception):
    """A PATCH body named a field update_job_application doesn't know how to write."""


def update_job_application(
    conn: sqlite3.Connection, application_id: int, patch: dict[str, Any]
) -> JobApplicationDetail | None:
    """Apply a partial edit from one of the job page's Edit forms (D-116) and return the result.

    `patch` is already filtered to the fields the caller actually sent (Pydantic's
    `exclude_unset`), so a field left out of the request is left untouched, not cleared.
    """
    if not patch:
        return get_job_application_detail(conn, application_id)
    assignments: list[str] = []
    params: dict[str, Any] = {"id": application_id}
    for key, value in patch.items():
        if key in _EDITABLE_JSON_COLUMNS:
            params[key] = json.dumps(value)
        elif key in _EDITABLE_COLUMNS:
            params[key] = value
        else:
            raise UnknownField(key)
        assignments.append(f"{key} = :{key}")
    with conn:
        conn.execute(f"UPDATE job_applications SET {', '.join(assignments)} WHERE id = :id", params)
    return get_job_application_detail(conn, application_id)


def set_master_cv(
    conn: sqlite3.Connection, application_id: int, profile_file_id: int | None
) -> JobApplicationDetail | None:
    """Point this application's Master CV selector at a Profile page master CV, or clear it.

    A reference only (D-116) — no bytes are copied, and Preview/Open aren't offered for it; the
    Profile page is where the file itself lives and is viewed.
    """
    with conn:
        conn.execute(
            "UPDATE job_applications SET master_cv_profile_file_id = ? WHERE id = ?",
            (profile_file_id, application_id),
        )
    return get_job_application_detail(conn, application_id)
