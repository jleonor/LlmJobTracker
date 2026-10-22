"""open_application_revise_turns: one row per chat turn revising one Open Application section
(D-251, D-252, migration 35). Mirrors job_revise_turns.py exactly, scoped by
(open_application_id, section_kind) instead of (job_application_id, section_kind), and with no
attachment column (open-application-domain.md: no section here takes a file attachment).
"""

import sqlite3
from dataclasses import dataclass

from llmjobtracker.revise_turns_shared import TurnTable


@dataclass(frozen=True)
class OpenApplicationReviseTurn:
    id: int
    open_application_id: int
    section_kind: str
    claude_job_id: int
    message: str
    created_at: str


_TABLE: TurnTable[OpenApplicationReviseTurn] = TurnTable(
    name="open_application_revise_turns",
    select_columns=(
        "id",
        "open_application_id",
        "section_kind",
        "claude_job_id",
        "message",
        "created_at",
    ),
    scope_columns=("open_application_id", "section_kind"),
    build=lambda row: OpenApplicationReviseTurn(**dict(row)),
)


def create_turn(
    conn: sqlite3.Connection,
    open_application_id: int,
    section_kind: str,
    claude_job_id: int,
    message: str,
) -> int:
    return _TABLE.create(
        conn,
        ("open_application_id", "section_kind", "claude_job_id", "message"),
        (open_application_id, section_kind, claude_job_id, message),
    )


def turn_for_job(conn: sqlite3.Connection, claude_job_id: int) -> OpenApplicationReviseTurn | None:
    return _TABLE.by_job(conn, claude_job_id)


def prior_messages(
    conn: sqlite3.Connection, open_application_id: int, section_kind: str, before_turn_id: int
) -> list[str]:
    return _TABLE.prior_messages(conn, (open_application_id, section_kind), before_turn_id)


def turns_for_section(
    conn: sqlite3.Connection, open_application_id: int, section_kind: str
) -> list[OpenApplicationReviseTurn]:
    return _TABLE.list_for_scope(conn, (open_application_id, section_kind))
