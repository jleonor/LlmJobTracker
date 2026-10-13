"""revise_turns: one row per chat turn in a Revise (LLM) conversation (D-106, migration 14).

A row is the user's message plus the Claude Job it queued. The job's own prompt and result
carry the model's side of the turn (read through claude_jobs.py, the same as any other Claude
Job); this table only remembers which document the turn is about, and in what order, so a
later turn's prompt can replay the earlier ones (Agent/specs/revise-steps.md).
"""

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviseTurn:
    id: int
    output_kind: str
    claude_job_id: int
    message: str
    created_at: str


def create_turn(
    conn: sqlite3.Connection, output_kind: str, claude_job_id: int, message: str
) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO revise_turns (output_kind, claude_job_id, message) VALUES (?, ?, ?)",
            (output_kind, claude_job_id, message),
        )
    turn_id = cursor.lastrowid
    if turn_id is None:
        raise RuntimeError("SQLite did not return the new row id")
    return turn_id


def _turn_from_row(row: sqlite3.Row) -> ReviseTurn:
    return ReviseTurn(**dict(row))


def turn_for_job(conn: sqlite3.Connection, claude_job_id: int) -> ReviseTurn | None:
    row = conn.execute(
        "SELECT id, output_kind, claude_job_id, message, created_at FROM revise_turns "
        "WHERE claude_job_id = ?",
        (claude_job_id,),
    ).fetchone()
    return None if row is None else _turn_from_row(row)


def prior_messages(conn: sqlite3.Connection, output_kind: str, before_turn_id: int) -> list[str]:
    """Earlier turns in this conversation, oldest first — not including `before_turn_id` itself."""
    rows = conn.execute(
        "SELECT message FROM revise_turns WHERE output_kind = ? AND id < ? ORDER BY id",
        (output_kind, before_turn_id),
    ).fetchall()
    return [str(row["message"]) for row in rows]


def turns_for_kind(conn: sqlite3.Connection, output_kind: str) -> list[ReviseTurn]:
    rows = conn.execute(
        "SELECT id, output_kind, claude_job_id, message, created_at FROM revise_turns "
        "WHERE output_kind = ? ORDER BY id",
        (output_kind,),
    ).fetchall()
    return [_turn_from_row(row) for row in rows]
