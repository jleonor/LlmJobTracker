"""Job Applications: one tracker row per listing, and their status history (D-44, D-45, D-46).

A Claude Job is a different thing (D-49). It is not stored here.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from localjobtracker.job_files import list_job_files

DEFAULT_STATUS = "Identified"


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


class JobApplicationFile(BaseModel):
    kind: str
    name: str
    date: str | None


class JobApplicationDetail(BaseModel):
    """One Job Application's full record, for the job page (D-56, D-113)."""

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
    """The job page's full record for one application (D-113), or None if it doesn't exist.

    Positioning fields (fit, gaps, unclear, match_score's breakdown) are Phase 5's (D-48); this
    returns only what is actually stored today.
    """
    row = conn.execute(
        """
        SELECT
            a.id, a.company, a.role_title, a.lane, a.location, a.work_mode, a.contract_type,
            a.portal_name, a.portal_url, a.status, a.match_score, a.next_action, a.due_date,
            a.description, a.requirements, a.notes,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM status_history h WHERE h.job_application_id = a.id),
                a.created_at
            ) AS last_updated
        FROM job_applications a
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
        files=[JobApplicationFile(kind=f["kind"], name=f["name"], date=f["date"]) for f in files],
    )
