"""Job Applications: one tracker row per listing, and their status history (D-44, D-45, D-46).

A Claude Job is a different thing (D-49). It is not stored here.
"""

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from llmjobtracker.job_files import JobApplicationFile, list_job_files, managed_folder

DEFAULT_STATUS = "Identified"
# D-44: forward order. A Job Application's current status (D-117) is the furthest of these it has
# a status_history date for, unless an end state applies.
MAIN_STATUSES = ("Identified", "Applied", "Screening", "Interview", "Offer")
# D-223: three end states, none of which counts as further progress than any other.
END_STATUSES = ("Rejected", "Withdrawn", "Expired")

# Columns a PATCH may touch, grouped the way the job page's Edit forms are (D-116). fit, gaps,
# unclear and interview_prep are stored as JSON; the rest are plain columns. match_score and
# status are not here: match_score is meant to be code-computed from weights/matches (D-47), not
# typed in by hand, and a status change goes through status_history, not a bare column write
# (D-45). interview_prep (D-168) added alongside the other three - the structured per-requirement
# positioning_scores stays deliberately out of this set, since it has no manual Edit form of its
# own (D-47 computes match_score from it, never the user by hand). lane (D-178) lives in Job
# details' own Edit dialog, free text, same as the rest of that form. role_title (D-207) lives
# there too - unlike every other field here it is NOT NULL and renames the managed files folder
# on disk (update_job_application below), so it gets its own validation rather than a bare
# column write. company is deliberately not included: nothing asked for renaming it, and doing so
# would need the same folder-rename treatment.
_EDITABLE_JSON_COLUMNS = frozenset({"requirements", "fit", "gaps", "unclear", "interview_prep"})
_EDITABLE_COLUMNS = frozenset(
    {
        "lane",
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
        "role_title",
    }
)


class StatusHistoryEntry(BaseModel):
    status: str
    changed_at: str


class JobApplication(BaseModel):
    """One row of the Applications table (D-227): every field any of its 26 selectable columns
    might need, so the frontend's column registry can show, hide, and reorder them freely without
    a second request per row. `status_history` backs the eight per-status-date columns, derived
    client-side the same way the job page's own timeline already is. The six `has_*` booleans
    match the semantics job_revise_pipeline.py's own `_job_details_has_data`/
    `_positioning_has_data`/`_tailored_cv_has_data`/`_cover_letter_has_data`/
    `_interview_prep_has_data` already use for the job page's flags (D-48)."""

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
    notes: str | None
    next_action: str | None
    due_date: str | None
    status_history: list[StatusHistoryEntry]
    has_listing: bool
    has_details: bool
    has_analysis: bool
    has_tailored_cv: bool
    has_cover_letter: bool
    has_interview_prep: bool


class InterviewPrepPair(BaseModel):
    """One of Interview preparation's ten question/answer pairs (D-166, job-llm-steps.md §7).

    `score` (D-173) is out of 10, how strong the answer is for this role - set by Claude when the
    pair is generated or revised, null for a pair added by hand through the Edit dialog, which has
    no model judgment behind it.
    """

    question: str
    answer: str
    score: int | None = None


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
    # Interview preparation (D-166): ten question/answer pairs, generated the same way as the
    # fields above and manually editable through its own Edit button (D-168).
    interview_prep: list[InterviewPrepPair]


class JobApplicationEdit(BaseModel):
    """A PATCH body from one of the job page's Edit forms (D-116).

    Every field is optional; only the ones the caller actually sends are written
    (`model_dump(exclude_unset=True)`), so omitting a field leaves it untouched, and a form only
    ever needs to send the fields its own section owns.
    """

    lane: str | None = None
    # D-207: the job title, editable from Job details like the rest of this form. Unlike every
    # other field here it can never actually be cleared (None/blank is rejected, not written) -
    # see update_job_application.
    role_title: str | None = None
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
    interview_prep: list[InterviewPrepPair] | None = None


class MasterCvSelection(BaseModel):
    """D-116: which Profile page master CV (by profile_files.id) this application uses, or None
    to clear the selection."""

    profile_file_id: int | None


class StatusHistoryEdit(BaseModel):
    """D-117: the full set of stage dates from Application history's Edit form — at most one
    entry per status, replacing whatever status_history held before."""

    entries: list[StatusHistoryEntry]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_job_applications(conn: sqlite3.Connection) -> list[JobApplication]:
    rows = conn.execute(
        """
        SELECT
            a.id, a.company, a.role_title, a.lane, a.location, a.status, a.match_score,
            a.portal_name, a.portal_url, a.work_mode, a.contract_type,
            a.notes, a.next_action, a.due_date,
            a.description, a.requirements, a.fit, a.gaps, a.strategy, a.unclear,
            a.interview_prep,
            COALESCE(
                (SELECT MAX(h.changed_at) FROM status_history h WHERE h.job_application_id = a.id),
                a.created_at
            ) AS last_updated,
            EXISTS(
                SELECT 1 FROM job_files f WHERE f.job_application_id = a.id AND f.kind = 'listing'
            ) AS has_listing,
            EXISTS(
                SELECT 1 FROM job_files f
                WHERE f.job_application_id = a.id AND f.kind = 'tailored_cv'
            ) AS has_tailored_cv,
            EXISTS(
                SELECT 1 FROM job_files f
                WHERE f.job_application_id = a.id AND f.kind = 'cover_letter'
            ) AS has_cover_letter
        FROM job_applications a
        ORDER BY last_updated DESC, a.id DESC
        """
    ).fetchall()
    history_by_application = _status_history_by_application(conn)
    return [_application_row(row, history_by_application.get(row["id"], [])) for row in rows]


def _status_history_by_application(
    conn: sqlite3.Connection,
) -> dict[int, list[StatusHistoryEntry]]:
    """Every application's status history, grouped by application id, in one query - not one
    query per row (D-227's per-status-date columns need every row's full history)."""
    rows = conn.execute(
        "SELECT job_application_id, status, changed_at FROM status_history ORDER BY changed_at"
    ).fetchall()
    grouped: dict[int, list[StatusHistoryEntry]] = {}
    for row in rows:
        grouped.setdefault(row["job_application_id"], []).append(
            StatusHistoryEntry(status=row["status"], changed_at=row["changed_at"])
        )
    return grouped


def _application_row(row: sqlite3.Row, history: list[StatusHistoryEntry]) -> JobApplication:
    """Builds one table row from `list_job_applications`'s query, deriving the Details/Analysis/
    Interview preparation status booleans from already-fetched columns the same way
    job_revise_pipeline.py's own `_job_details_has_data`/`_positioning_has_data`/
    `_interview_prep_has_data` do, rather than three more subqueries."""
    requirements = json.loads(row["requirements"])
    return JobApplication(
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
        notes=row["notes"],
        next_action=row["next_action"],
        due_date=row["due_date"],
        status_history=history,
        has_listing=bool(row["has_listing"]),
        has_details=bool(row["description"]) and requirements != [],
        has_analysis=(
            row["match_score"] is not None
            or json.loads(row["fit"]) != []
            or json.loads(row["gaps"]) != []
            or row["strategy"] is not None
            or json.loads(row["unclear"]) != []
        ),
        has_tailored_cv=bool(row["has_tailored_cv"]),
        has_cover_letter=bool(row["has_cover_letter"]),
        has_interview_prep=json.loads(row["interview_prep"]) != [],
    )


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


def delete_job_application(conn: sqlite3.Connection, files_root: Path, application_id: int) -> bool:
    """Removes the row and everything that belongs to it: status_history, claude_jobs (and their
    prompts), job_files and job_revise_turns are all `ON DELETE CASCADE` on job_applications
    (migrations.py) and so go with it in the same transaction. The managed folder's files on disk
    are not a database row, so a DB cascade can't reach them - removed here directly, after the
    row is gone. Returns False if there is no such application.
    """
    row = conn.execute(
        "SELECT company, role_title FROM job_applications WHERE id = ?", (application_id,)
    ).fetchone()
    if row is None:
        return False
    with conn:
        conn.execute("DELETE FROM job_applications WHERE id = ?", (application_id,))
    shutil.rmtree(managed_folder(files_root, row["company"], row["role_title"]), ignore_errors=True)
    return True


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
            a.fit, a.gaps, a.strategy, a.unclear, a.interview_prep,
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
            JobApplicationFile(
                id=f["id"],
                kind=f["kind"],
                name=f["name"],
                date=f["date"],
                extraction_status=f["extraction_status"],
                extraction_message=f["extraction_message"],
            )
            for f in files
        ],
        master_cv_profile_file_id=row["master_cv_profile_file_id"],
        master_cv_name=row["master_cv_name"],
        fit=json.loads(row["fit"]),
        gaps=json.loads(row["gaps"]),
        strategy=row["strategy"],
        unclear=json.loads(row["unclear"]),
        interview_prep=[InterviewPrepPair(**pair) for pair in json.loads(row["interview_prep"])],
    )


class UnknownField(Exception):
    """A PATCH body named a field update_job_application doesn't know how to write."""


class InvalidRoleTitle(Exception):
    """A role_title edit (D-207) was blank, or would collide with another application's
    already-existing managed folder under the same company."""


def update_job_application(
    conn: sqlite3.Connection,
    application_id: int,
    patch: dict[str, Any],
    files_root: Path | None = None,
) -> JobApplicationDetail | None:
    """Apply a partial edit from one of the job page's Edit forms (D-116) and return the result.

    `patch` is already filtered to the fields the caller actually sent (Pydantic's
    `exclude_unset`), so a field left out of the request is left untouched, not cleared.

    A role_title edit (D-207) also renames the managed files folder on disk, so existing job
    files stay reachable under the new title - `files_root` is only needed for that; every
    caller that never touches role_title (every LLM pipeline today) can omit it.
    """
    if not patch:
        return get_job_application_detail(conn, application_id)
    current = get_job_application_detail(conn, application_id)
    if current is None:
        return None
    if "role_title" in patch:
        new_title = (patch["role_title"] or "").strip()
        if not new_title:
            raise InvalidRoleTitle("Job title cannot be blank.")
        patch = {**patch, "role_title": new_title}
        if files_root is not None and new_title != current.role_title:
            old_folder = managed_folder(files_root, current.company, current.role_title)
            new_folder = managed_folder(files_root, current.company, new_title)
            if old_folder != new_folder:
                if new_folder.exists():
                    raise InvalidRoleTitle(
                        f"Another application already has a folder for {new_title!r}."
                    )
                if old_folder.exists():
                    new_folder.parent.mkdir(parents=True, exist_ok=True)
                    old_folder.rename(new_folder)
                    # job_files.stored_path is a path relative to files_root, set once when each
                    # file was stored (job_files.py) - it doesn't follow the folder on its own.
                    old_rel = old_folder.relative_to(files_root).as_posix()
                    new_rel = new_folder.relative_to(files_root).as_posix()
                    with conn:
                        for row in conn.execute(
                            "SELECT id, stored_path FROM job_files WHERE job_application_id = ?",
                            (application_id,),
                        ).fetchall():
                            stored = str(row["stored_path"])
                            if stored == old_rel or stored.startswith(old_rel + "/"):
                                conn.execute(
                                    "UPDATE job_files SET stored_path = ? WHERE id = ?",
                                    (new_rel + stored[len(old_rel) :], row["id"]),
                                )
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


class NoStatusEntries(Exception):
    """Raised when a status-history replace (D-117) is given no entries at all — a Job
    Application must always have some current status."""


def _derive_current_status(entries: list[tuple[str, str]]) -> str:
    """The furthest-reached main status, or the latest-dated end state if one or more is given
    a date — matching the progress rule D-44 already uses (and StatusTimeline mirrors client
    side): reaching further counts, regardless of which has the most recent date."""
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
) -> JobApplicationDetail | None:
    """Replace every status_history row for this application with `entries` (D-117's stage
    editor): at most one row per status, not D-45's append-only multiple-rows-per-status model —
    the editor shows and edits one date per stage. Recomputes the application's current `status`
    to match (`_derive_current_status`).
    """
    if get_job_application_detail(conn, application_id) is None:
        return None
    if not entries:
        raise NoStatusEntries()
    current_status = _derive_current_status(entries)
    with conn:
        conn.execute("DELETE FROM status_history WHERE job_application_id = ?", (application_id,))
        conn.executemany(
            "INSERT INTO status_history (job_application_id, status, changed_at) VALUES (?, ?, ?)",
            [(application_id, status, changed_at) for status, changed_at in entries],
        )
        conn.execute(
            "UPDATE job_applications SET status = ? WHERE id = ?", (current_status, application_id)
        )
    return get_job_application_detail(conn, application_id)
