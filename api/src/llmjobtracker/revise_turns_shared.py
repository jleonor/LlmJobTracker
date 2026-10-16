"""Shared CRUD shape for a chat-turn table (D-225).

revise_turns.py (profile documents, scoped by output_kind) and job_revise_turns.py (job-page
sections, scoped by job_application_id + section_kind) store one row per chat turn - the user's
message plus the Claude Job it queued - and offer the same four operations: insert a turn, find
the turn a given Claude Job belongs to, list earlier messages in the same conversation, and list
every turn in a scope. They differed only in which columns scope a turn and which extra columns a
row carries; this module owns the query shape once, parameterized per table, and each module keeps
its own dataclass, row-building, and the public function names its callers already use.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class TurnTable[T]:
    name: str
    select_columns: tuple[str, ...]
    scope_columns: tuple[str, ...]
    build: Callable[[sqlite3.Row], T]

    def _select_clause(self) -> str:
        return ", ".join(self.select_columns)

    def _scope_where(self) -> str:
        return " AND ".join(f"{column} = ?" for column in self.scope_columns)

    def create(
        self, conn: sqlite3.Connection, insert_columns: tuple[str, ...], values: tuple[object, ...]
    ) -> int:
        placeholders = ", ".join("?" for _ in values)
        with conn:
            cursor = conn.execute(
                f"INSERT INTO {self.name} ({', '.join(insert_columns)}) VALUES ({placeholders})",
                values,
            )
        turn_id = cursor.lastrowid
        if turn_id is None:
            raise RuntimeError("SQLite did not return the new row id")
        return turn_id

    def by_job(self, conn: sqlite3.Connection, claude_job_id: int) -> T | None:
        row = conn.execute(
            f"SELECT {self._select_clause()} FROM {self.name} WHERE claude_job_id = ?",
            (claude_job_id,),
        ).fetchone()
        return None if row is None else self.build(row)

    def prior_messages(
        self, conn: sqlite3.Connection, scope_values: tuple[object, ...], before_turn_id: int
    ) -> list[str]:
        """Earlier turns in this conversation, oldest first — not including `before_turn_id`."""
        rows = conn.execute(
            f"SELECT message FROM {self.name} WHERE {self._scope_where()} AND id < ? "
            "ORDER BY id",
            (*scope_values, before_turn_id),
        ).fetchall()
        return [str(row["message"]) for row in rows]

    def list_for_scope(self, conn: sqlite3.Connection, scope_values: tuple[object, ...]) -> list[T]:
        rows = conn.execute(
            f"SELECT {self._select_clause()} FROM {self.name} WHERE {self._scope_where()} "
            "ORDER BY id",
            scope_values,
        ).fetchall()
        return [self.build(row) for row in rows]
