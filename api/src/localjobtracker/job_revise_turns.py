"""job_revise_turns: one row per chat turn revising one job-page section (D-136, migration 18).

A row is the user's message plus the Claude Job it queued, scoped to one Job Application and one
of its five chat-revised sections (job_details, positioning, application_history, tailored_cv,
cover_letter). The job's own prompt and result carry the model's side of the turn (read through
claude_jobs.py, the same as any other Claude Job); this table only remembers which application and
section the turn is about, and in what order, so a later turn's prompt can replay the earlier ones
(Agent/specs/job-revise-steps.md) — the job-scoped counterpart to revise_turns.py.
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class JobReviseTurn:
    id: int
    job_application_id: int
    section_kind: str
    claude_job_id: int
    message: str
    attachment_job_file_id: int | None
    created_at: str


_COLUMNS = (
    "id, job_application_id, section_kind, claude_job_id, message, "
    "attachment_job_file_id, created_at"
)


def create_turn(
    conn: sqlite3.Connection,
    job_application_id: int,
    section_kind: str,
    claude_job_id: int,
    message: str,
    attachment_job_file_id: int | None = None,
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO job_revise_turns "
            "(job_application_id, section_kind, claude_job_id, message, attachment_job_file_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_application_id, section_kind, claude_job_id, message, attachment_job_file_id),
        )
    turn_id = cursor.lastrowid
    if turn_id is None:
        raise RuntimeError("SQLite did not return the new row id")
    return turn_id


def _turn_from_row(row: sqlite3.Row) -> JobReviseTurn:
    return JobReviseTurn(**dict(row))


def turn_for_job(conn: sqlite3.Connection, claude_job_id: int) -> JobReviseTurn | None:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM job_revise_turns WHERE claude_job_id = ?",
        (claude_job_id,),
    ).fetchone()
    return None if row is None else _turn_from_row(row)


def prior_messages(
    conn: sqlite3.Connection, job_application_id: int, section_kind: str, before_turn_id: int
) -> list[str]:
    """Earlier turns in this conversation, oldest first — not including `before_turn_id` itself."""
    rows = conn.execute(
        "SELECT message FROM job_revise_turns "
        "WHERE job_application_id = ? AND section_kind = ? AND id < ? ORDER BY id",
        (job_application_id, section_kind, before_turn_id),
    ).fetchall()
    return [str(row["message"]) for row in rows]


def turns_for_section(
    conn: sqlite3.Connection, job_application_id: int, section_kind: str
) -> list[JobReviseTurn]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM job_revise_turns "
        "WHERE job_application_id = ? AND section_kind = ? ORDER BY id",
        (job_application_id, section_kind),
    ).fetchall()
    return [_turn_from_row(row) for row in rows]
