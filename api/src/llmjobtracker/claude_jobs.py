"""Claude Jobs in SQLite: creating, listing and changing their state (D-49, D-50, D-62).

A Claude Job is one queued unit of Claude work, made of ordered prompts. The worker that runs
them is in claude_job_queue.py. This module only reads and writes the rows, so the states
can be checked without running anything.
"""

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel


class ClaudeJobPrompt(BaseModel):
    position: int
    prompt_kind: str
    status: str
    error: str | None
    cost_usd: float | None
    duration_ms: int | None
    model: str | None
    started_at: str | None
    finished_at: str | None
    skipped: bool
    skip_reason: str | None
    answer_chars: int | None
    # The answer streamed so far, while running (D-105). Not a column: the API layer fills it
    # in from the queue's live state, which is why it is never selected from the database.
    live_text: str | None = None


class ClaudeJob(BaseModel):
    id: int
    label: str
    kind: str
    job_application_id: int | None
    status: str
    error: str | None
    created_at: str
    updated_at: str
    resume_at: str | None
    prompts: list[ClaudeJobPrompt]


@dataclass(frozen=True)
class PromptRow:
    """One prompt as the worker needs it. The text is not sent to the browser."""

    id: int
    claude_job_id: int
    position: int
    prompt_kind: str
    prompt_text: str
    status: str


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_claude_job(
    conn: sqlite3.Connection,
    label: str,
    kind: str,
    prompts: Sequence[tuple[str, str]],
    job_application_id: int | None = None,
) -> int:
    """Queue a Claude Job. `prompts` is a list of (prompt_kind, prompt_text), in run order."""
    if not prompts:
        raise ValueError("A Claude Job needs at least one prompt.")
    now = _now()
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO claude_jobs
                (label, kind, job_application_id, status, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, ?)
            """,
            (label, kind, job_application_id, now, now),
        )
        job_id = cursor.lastrowid
        if job_id is None:
            raise RuntimeError("SQLite did not return the new row id")
        conn.executemany(
            """
            INSERT INTO claude_job_prompts (claude_job_id, position, prompt_kind, prompt_text)
            VALUES (?, ?, ?, ?)
            """,
            [
                (job_id, position, prompt_kind, prompt_text)
                for position, (prompt_kind, prompt_text) in enumerate(prompts)
            ],
        )
    return job_id


def _prompts_for(conn: sqlite3.Connection, job_id: int) -> list[ClaudeJobPrompt]:
    rows = conn.execute(
        """
        SELECT position, prompt_kind, status, error, cost_usd, duration_ms, model,
               started_at, finished_at,
               COALESCE(result_text LIKE 'Skipped%', 0) AS skipped,
               CASE WHEN result_text LIKE 'Skipped%' THEN result_text END AS skip_reason,
               LENGTH(result_text) AS answer_chars
        FROM claude_job_prompts WHERE claude_job_id = ? ORDER BY position
        """,
        (job_id,),
    ).fetchall()
    return [ClaudeJobPrompt(**dict(row)) for row in rows]


def _job_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> ClaudeJob:
    return ClaudeJob(
        id=row["id"],
        label=row["label"],
        kind=row["kind"],
        job_application_id=row["job_application_id"],
        status=row["status"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        resume_at=row["resume_at"],
        prompts=_prompts_for(conn, row["id"]),
    )


def list_claude_jobs(conn: sqlite3.Connection) -> list[ClaudeJob]:
    """All Claude Jobs in creation order, which is the order the queue runs them (D-50)."""
    rows = conn.execute("SELECT * FROM claude_jobs ORDER BY id").fetchall()
    return [_job_from_row(conn, row) for row in rows]


def get_claude_job(conn: sqlite3.Connection, job_id: int) -> ClaudeJob | None:
    row = conn.execute("SELECT * FROM claude_jobs WHERE id = ?", (job_id,)).fetchone()
    return None if row is None else _job_from_row(conn, row)


def job_status(conn: sqlite3.Connection, job_id: int) -> str | None:
    row = conn.execute("SELECT status FROM claude_jobs WHERE id = ?", (job_id,)).fetchone()
    return None if row is None else str(row["status"])


def prompt_rows(conn: sqlite3.Connection, job_id: int) -> list[PromptRow]:
    rows = conn.execute(
        """
        SELECT id, claude_job_id, position, prompt_kind, prompt_text, status
        FROM claude_job_prompts WHERE claude_job_id = ? ORDER BY position
        """,
        (job_id,),
    ).fetchall()
    return [PromptRow(**dict(row)) for row in rows]


class PromptExchange(BaseModel):
    """What was sent to Claude for one prompt, and what came back (D-77)."""

    position: int
    prompt_kind: str
    prompt_text: str
    result_text: str | None
    error: str | None


def store_answer(conn: sqlite3.Connection, prompt_id: int, text: str) -> None:
    """Keep Claude's answer as it came back, before any check runs (D-77)."""
    with conn:
        conn.execute(
            "UPDATE claude_job_prompts SET result_text = ? WHERE id = ?", (text, prompt_id)
        )


def prompt_exchange(conn: sqlite3.Connection, job_id: int, position: int) -> PromptExchange | None:
    row = conn.execute(
        """
        SELECT position, prompt_kind, prompt_text, result_text, error
        FROM claude_job_prompts WHERE claude_job_id = ? AND position = ?
        """,
        (job_id, position),
    ).fetchone()
    return None if row is None else PromptExchange(**dict(row))


def set_prompt_text(conn: sqlite3.Connection, prompt_id: int, text: str) -> None:
    """Store the text a prompt was built into, just before it runs."""
    with conn:
        conn.execute(
            "UPDATE claude_job_prompts SET prompt_text = ? WHERE id = ?", (text, prompt_id)
        )


def next_queued_job_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM claude_jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    return None if row is None else int(row["id"])


def transition(
    conn: sqlite3.Connection,
    job_id: int,
    from_statuses: tuple[str, ...],
    to_status: str,
    error: str | None = None,
) -> bool:
    """Move a job to `to_status` only if it is in one of `from_statuses`. Returns whether it moved.

    The condition makes a cancel that lands during a run win over the worker's own update.
    """
    placeholders = ", ".join("?" for _ in from_statuses)
    with conn:
        cursor = conn.execute(
            f"""
            UPDATE claude_jobs SET status = ?, error = ?, updated_at = ?
            WHERE id = ? AND status IN ({placeholders})
            """,
            (to_status, error, _now(), job_id, *from_statuses),
        )
    return cursor.rowcount == 1


def recover_interrupted(conn: sqlite3.Connection) -> int:
    """At startup, undo what a stopped worker left behind (D-62).

    A job that was processing goes back to queued. Its prompt that was running goes back to
    queued too, so it runs again from the start. Finished prompts are kept. Returns the number
    of jobs that went back to the queue.
    """
    with conn:
        conn.execute(
            """
            UPDATE claude_job_prompts SET status = 'queued', started_at = NULL
            WHERE status = 'running'
              AND claude_job_id IN (SELECT id FROM claude_jobs WHERE status = 'processing')
            """
        )
        cursor = conn.execute(
            """
            UPDATE claude_jobs SET status = 'queued', updated_at = ?
            WHERE status = 'processing'
            """,
            (_now(),),
        )
    return cursor.rowcount


def pause_job(conn: sqlite3.Connection, job_id: int, error: str, resume_at: str | None) -> bool:
    """Pause a running job at a plan limit. `resume_at` is when it resumes by itself (D-75)."""
    with conn:
        cursor = conn.execute(
            """
            UPDATE claude_jobs SET status = 'paused', error = ?, resume_at = ?, updated_at = ?
            WHERE id = ? AND status = 'processing'
            """,
            (error, resume_at, _now(), job_id),
        )
    return cursor.rowcount == 1


def resume_job(conn: sqlite3.Connection, job_id: int) -> bool:
    """Resume a paused job, by the user or at its reset time (D-63, D-75)."""
    resumed = transition(conn, job_id, ("paused",), "queued", error=None)
    if resumed:
        with conn:
            conn.execute("UPDATE claude_jobs SET resume_at = NULL WHERE id = ?", (job_id,))
    return resumed


def resume_due_jobs(conn: sqlite3.Connection) -> list[int]:
    """Resume every paused job whose reset time has passed. Returns the ids resumed."""
    rows = conn.execute(
        """
        SELECT id FROM claude_jobs
        WHERE status = 'paused' AND resume_at IS NOT NULL AND resume_at <= ?
        """,
        (_now(),),
    ).fetchall()
    return [int(row["id"]) for row in rows if resume_job(conn, int(row["id"]))]


def cancel_job(conn: sqlite3.Connection, job_id: int) -> bool:
    """Cancel a job that has not finished. A running prompt is stopped by the worker (runner-notes).

    Returns False if the job is already done, failed or cancelled.
    """
    with conn:
        cursor = conn.execute(
            """
            UPDATE claude_jobs SET status = 'cancelled', error = NULL, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'paused', 'processing')
            """,
            (_now(), job_id),
        )
        if cursor.rowcount != 1:
            return False
        conn.execute(
            """
            UPDATE claude_job_prompts SET status = 'cancelled'
            WHERE claude_job_id = ? AND status IN ('queued', 'running')
            """,
            (job_id,),
        )
    return True


def set_prompt_status(
    conn: sqlite3.Connection,
    prompt_id: int,
    from_statuses: tuple[str, ...],
    to_status: str,
    *,
    result_text: str | None = None,
    error: str | None = None,
    cost_usd: float | None = None,
    duration_ms: int | None = None,
    model: str | None = None,
) -> bool:
    """Change one prompt's status if it is in `from_statuses`. Returns whether it changed."""
    placeholders = ", ".join("?" for _ in from_statuses)
    now = _now()
    with conn:
        cursor = conn.execute(
            f"""
            UPDATE claude_job_prompts SET
                status = ?,
                result_text = COALESCE(?, result_text),
                error = ?,
                cost_usd = COALESCE(?, cost_usd),
                duration_ms = COALESCE(?, duration_ms),
                model = COALESCE(?, model),
                started_at = CASE WHEN ? = 'running' THEN ? ELSE started_at END,
                finished_at = CASE WHEN ? IN ('done', 'failed', 'cancelled') THEN ? ELSE NULL END
            WHERE id = ? AND status IN ({placeholders})
            """,
            (
                to_status,
                result_text,
                error,
                cost_usd,
                duration_ms,
                model,
                to_status,
                now,
                to_status,
                now,
                prompt_id,
                *from_statuses,
            ),
        )
    return cursor.rowcount == 1
