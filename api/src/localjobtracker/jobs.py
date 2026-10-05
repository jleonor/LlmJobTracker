"""Job rows: the model returned by the API and the queries behind it."""

import sqlite3
from typing import Any

from pydantic import BaseModel


class Job(BaseModel):
    id: int
    company: str
    role_title: str
    lane: str | None
    status: str
    next_action: str | None
    due_date: str | None


def list_jobs(conn: sqlite3.Connection) -> list[Job]:
    rows = conn.execute(
        "SELECT id, company, role_title, lane, status, next_action, due_date "
        "FROM jobs ORDER BY due_date IS NULL, due_date, id"
    ).fetchall()
    return [Job(**dict(row)) for row in rows]


def insert_jobs(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
    """Insert job rows in one transaction. Returns the number of rows added."""
    with conn:
        conn.executemany(
            "INSERT INTO jobs (company, role_title, lane, status, next_action, due_date) "
            "VALUES (:company, :role_title, :lane, :status, :next_action, :due_date)",
            rows,
        )
    return len(rows)


def count_jobs(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
