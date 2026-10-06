"""The Fact Sheet review: list, edit, verify and reject facts (Phase 2 step 8, D-09).

Only verified facts are usable by later documents. Every later step gets them from
`verified_facts`, and nothing else. A fact's text is the user's to edit. Editing the text
resets its status to unverified, unless the same change also sets the status, so a verification
always applies to the wording the user checked.
"""

import json
import sqlite3
from typing import Any

from pydantic import BaseModel

from localjobtracker.migrations import FACT_STATUSES
from localjobtracker.profile_pipeline import DATE_PATTERN


class FactConflict(BaseModel):
    id: str
    fact_ids: list[str]
    note: str


class Fact(BaseModel):
    id: int
    fact_key: str
    text: str
    date: str
    source_file_id: int
    source_name: str
    source_location: str
    status: str


class FactSheet(BaseModel):
    output_id: int | None
    version: int | None
    facts: list[Fact]
    conflicts: list[FactConflict]


class VerifiedFact(BaseModel):
    """A fact the user has verified. Later documents may cite it by `fact_key`."""

    id: int
    fact_key: str
    text: str
    date: str
    source_file_id: int
    source_location: str


class FactUpdate(BaseModel):
    text: str | None = None
    date: str | None = None
    source_location: str | None = None
    status: str | None = None


class FactError(Exception):
    """A rejected fact change. The API answers 400 or 404 with the message."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _latest_fact_sheet(conn: sqlite3.Connection) -> tuple[int, int, dict[str, Any]] | None:
    row = conn.execute(
        "SELECT id, version, body_json FROM profile_outputs WHERE kind = 'fact_sheet' "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    body: dict[str, Any] = json.loads(row["body_json"])
    return int(row["id"]), int(row["version"]), body


def fact_sheet(conn: sqlite3.Connection) -> FactSheet:
    latest = _latest_fact_sheet(conn)
    if latest is None:
        return FactSheet(output_id=None, version=None, facts=[], conflicts=[])
    output_id, version, body = latest
    rows = conn.execute(
        """
        SELECT f.id, f.fact_key, f.text, f.date, f.source_file_id, p.original_name AS source_name,
               f.source_location, f.status
        FROM facts f JOIN profile_files p ON p.id = f.source_file_id
        WHERE f.profile_output_id = ? ORDER BY f.fact_key
        """,
        (output_id,),
    ).fetchall()
    conflicts = [FactConflict(**item) for item in body.get("conflicts", [])]
    return FactSheet(
        output_id=output_id,
        version=version,
        facts=[Fact(**dict(row)) for row in rows],
        conflicts=conflicts,
    )


def verified_facts(conn: sqlite3.Connection) -> list[VerifiedFact]:
    """The only way later steps read the Fact Sheet: verified facts of the latest version."""
    latest = _latest_fact_sheet(conn)
    if latest is None:
        return []
    output_id, _version, _body = latest
    rows = conn.execute(
        """
        SELECT id, fact_key, text, date, source_file_id, source_location
        FROM facts WHERE profile_output_id = ? AND status = 'verified' ORDER BY fact_key
        """,
        (output_id,),
    ).fetchall()
    return [VerifiedFact(**dict(row)) for row in rows]


def update_fact(conn: sqlite3.Connection, fact_id: int, change: FactUpdate) -> Fact:
    row = conn.execute(
        "SELECT id, profile_output_id, text, date, source_location, status FROM facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    latest = _latest_fact_sheet(conn)
    if row is None or latest is None or row["profile_output_id"] != latest[0]:
        raise FactError("Only facts of the latest Fact Sheet can be changed.", 404)

    text = row["text"] if change.text is None else change.text.strip()
    date = row["date"] if change.date is None else change.date.strip()
    location = (
        row["source_location"] if change.source_location is None else change.source_location.strip()
    )
    if not text:
        raise FactError("A fact needs some text.", 400)
    if not DATE_PATTERN.match(date):
        raise FactError("The date must be YYYY, YYYY-MM or YYYY-MM-DD.", 400)
    if not location:
        raise FactError("A fact needs a source location.", 400)

    if change.status is not None and change.status not in FACT_STATUSES:
        raise FactError("Unknown status.", 400)
    text_changed = text != row["text"] or date != row["date"] or location != row["source_location"]
    if change.status is not None:
        status = change.status
    elif text_changed:
        status = "unverified"
    else:
        status = row["status"]

    with conn:
        conn.execute(
            """
            UPDATE facts SET text = ?, date = ?, source_location = ?, status = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (text, date, location, status, fact_id),
        )
    updated = fact_sheet(conn)
    for fact in updated.facts:
        if fact.id == fact_id:
            return fact
    raise FactError("No such fact.", 404)
