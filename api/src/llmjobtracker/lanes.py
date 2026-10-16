"""Lanes: the approved, named list of positioning directions a Job Application's `lane` field
picks from (D-182, D-214). Stored in their own table, edited by hand on the Profile page, and
(re)populated in bulk from the positioning strategy document by `extract_lanes`
(`lane_pipeline.py`) - never read live from the strategy document's prose.
"""

import sqlite3
from typing import Final

from pydantic import BaseModel

_COLUMNS = "id, name, description, reasoning, position"

# The code-guaranteed catch-all lane (D-219): seeded by migration 29 so it exists from the
# start, and re-added by replace_all_lanes below whenever Sync from strategy wipes the table.
# Not written by the strategy prompt itself - it's a catalog-completeness fallback, not a real
# positioning direction. Deleting it by hand between syncs is allowed; it isn't protected.
OTHER_LANE_NAME: Final = "Other"
OTHER_LANE_DESCRIPTION: Final = "Roles that don't clearly fit any of the lanes above."


class Lane(BaseModel):
    id: int
    name: str
    description: str | None
    reasoning: str | None
    position: int


class LaneEdit(BaseModel):
    """Every field optional - only the ones actually sent are written (`model_dump
    (exclude_unset=True)`), the same partial-PATCH convention `job_applications.py`'s
    `JobApplicationEdit` already uses."""

    name: str | None = None
    description: str | None = None
    reasoning: str | None = None
    position: int | None = None


def _row_to_lane(row: sqlite3.Row) -> Lane:
    return Lane(**dict(row))


def list_lanes(conn: sqlite3.Connection) -> list[Lane]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM lanes ORDER BY position").fetchall()
    return [_row_to_lane(row) for row in rows]


def lane_names(conn: sqlite3.Connection) -> list[str]:
    """Just the names, in position order - what the LLM lane-matching prompts list
    (`Agent/specs/lane-steps.md`)."""
    rows = conn.execute("SELECT name FROM lanes ORDER BY position").fetchall()
    return [row["name"] for row in rows]


def get_lane(conn: sqlite3.Connection, lane_id: int) -> Lane | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM lanes WHERE id = ?", (lane_id,)).fetchone()
    return _row_to_lane(row) if row is not None else None


def create_lane(
    conn: sqlite3.Connection, name: str, description: str | None, reasoning: str | None
) -> Lane:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("A lane needs a name.")
    with conn:
        next_position = conn.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM lanes").fetchone()[
            0
        ]
        lane_id = conn.execute(
            "INSERT INTO lanes (name, description, reasoning, position) VALUES (?, ?, ?, ?)",
            (cleaned_name, description, reasoning, next_position),
        ).lastrowid
    assert lane_id is not None
    lane = get_lane(conn, lane_id)
    assert lane is not None
    return lane


def update_lane(conn: sqlite3.Connection, lane_id: int, edit: LaneEdit) -> Lane | None:
    fields = edit.model_dump(exclude_unset=True)
    if "name" in fields:
        cleaned_name = (fields["name"] or "").strip()
        if not cleaned_name:
            raise ValueError("A lane needs a name.")
        fields["name"] = cleaned_name
    if fields:
        columns = ", ".join(f"{key} = ?" for key in fields)
        with conn:
            cursor = conn.execute(
                f"UPDATE lanes SET {columns}, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                "WHERE id = ?",
                (*fields.values(), lane_id),
            )
        if cursor.rowcount == 0:
            return None
    return get_lane(conn, lane_id)


def delete_lane(conn: sqlite3.Connection, lane_id: int) -> bool:
    """Leaves every other lane's `position` untouched - no renumbering, matching how deleting a
    row elsewhere in this app never compacts a sibling's ordering column."""
    with conn:
        cursor = conn.execute("DELETE FROM lanes WHERE id = ?", (lane_id,))
    return cursor.rowcount == 1


def ensure_other_lane(conn: sqlite3.Connection) -> None:
    """Re-adds the Other lane (D-219) if it's missing, appended after every other lane. A
    case-insensitive check, matching `validate_lane_name`'s own matching convention - a lane the
    strategy document itself happened to name "Other" counts, no duplicate is added."""
    names = lane_names(conn)
    if any(name.casefold() == OTHER_LANE_NAME.casefold() for name in names):
        return
    with conn:
        next_position = conn.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM lanes").fetchone()[
            0
        ]
        conn.execute(
            "INSERT INTO lanes (name, description, position) VALUES (?, ?, ?)",
            (OTHER_LANE_NAME, OTHER_LANE_DESCRIPTION, next_position),
        )


def replace_all_lanes(
    conn: sqlite3.Connection, lanes: list[tuple[str, str | None, str | None]]
) -> None:
    """Used by `extract_lanes`'s `on_result` (Sync from strategy, D-214): replaces every stored
    lane with the parsed list, in the given order (`position` 0, 1, 2, ...). A full replace, not
    a merge - the frontend confirms before running Sync, since this can overwrite manual edits.
    Always ends with the Other lane (D-219) present, even though this wipes the whole table."""
    with conn:
        conn.execute("DELETE FROM lanes")
        conn.executemany(
            "INSERT INTO lanes (name, description, reasoning, position) VALUES (?, ?, ?, ?)",
            [
                (name, description, reasoning, position)
                for position, (name, description, reasoning) in enumerate(lanes)
            ],
        )
    ensure_other_lane(conn)
