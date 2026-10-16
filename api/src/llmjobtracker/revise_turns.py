"""revise_turns: one row per chat turn in a Revise (LLM) conversation (D-106, migration 14).

A row is the user's message plus the Claude Job it queued. The job's own prompt and result
carry the model's side of the turn (read through claude_jobs.py, the same as any other Claude
Job); this table only remembers which document the turn is about, and in what order, so a
later turn's prompt can replay the earlier ones (Agent/specs/revise-steps.md).
"""

import sqlite3
from dataclasses import dataclass

from llmjobtracker.revise_turns_shared import TurnTable


@dataclass(frozen=True)
class ReviseTurn:
    id: int
    output_kind: str
    claude_job_id: int
    message: str
    created_at: str


_TABLE: TurnTable[ReviseTurn] = TurnTable(
    name="revise_turns",
    select_columns=("id", "output_kind", "claude_job_id", "message", "created_at"),
    scope_columns=("output_kind",),
    build=lambda row: ReviseTurn(**dict(row)),
)


def create_turn(
    conn: sqlite3.Connection, output_kind: str, claude_job_id: int, message: str
) -> int:
    return _TABLE.create(
        conn, ("output_kind", "claude_job_id", "message"), (output_kind, claude_job_id, message)
    )


def turn_for_job(conn: sqlite3.Connection, claude_job_id: int) -> ReviseTurn | None:
    return _TABLE.by_job(conn, claude_job_id)


def prior_messages(conn: sqlite3.Connection, output_kind: str, before_turn_id: int) -> list[str]:
    """Earlier turns in this conversation, oldest first — not including `before_turn_id` itself."""
    return _TABLE.prior_messages(conn, (output_kind,), before_turn_id)


def turns_for_kind(conn: sqlite3.Connection, output_kind: str) -> list[ReviseTurn]:
    return _TABLE.list_for_scope(conn, (output_kind,))
