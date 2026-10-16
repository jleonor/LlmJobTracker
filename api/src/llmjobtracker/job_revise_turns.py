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

from llmjobtracker.revise_turns_shared import TurnTable


@dataclass(frozen=True)
class JobReviseTurn:
    id: int
    job_application_id: int
    section_kind: str
    claude_job_id: int
    message: str
    attachment_job_file_id: int | None
    created_at: str


_TABLE: TurnTable[JobReviseTurn] = TurnTable(
    name="job_revise_turns",
    select_columns=(
        "id",
        "job_application_id",
        "section_kind",
        "claude_job_id",
        "message",
        "attachment_job_file_id",
        "created_at",
    ),
    scope_columns=("job_application_id", "section_kind"),
    build=lambda row: JobReviseTurn(**dict(row)),
)


def create_turn(
    conn: sqlite3.Connection,
    job_application_id: int,
    section_kind: str,
    claude_job_id: int,
    message: str,
    attachment_job_file_id: int | None = None,
) -> int:
    return _TABLE.create(
        conn,
        (
            "job_application_id",
            "section_kind",
            "claude_job_id",
            "message",
            "attachment_job_file_id",
        ),
        (job_application_id, section_kind, claude_job_id, message, attachment_job_file_id),
    )


def turn_for_job(conn: sqlite3.Connection, claude_job_id: int) -> JobReviseTurn | None:
    return _TABLE.by_job(conn, claude_job_id)


def prior_messages(
    conn: sqlite3.Connection, job_application_id: int, section_kind: str, before_turn_id: int
) -> list[str]:
    """Earlier turns in this conversation, oldest first — not including `before_turn_id` itself."""
    return _TABLE.prior_messages(conn, (job_application_id, section_kind), before_turn_id)


def turns_for_section(
    conn: sqlite3.Connection, job_application_id: int, section_kind: str
) -> list[JobReviseTurn]:
    return _TABLE.list_for_scope(conn, (job_application_id, section_kind))
