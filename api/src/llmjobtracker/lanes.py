"""Lanes: the approved, named list of positioning directions a Job Application's `lane` field
picks from (D-182, D-214). Stored in their own table, edited by hand on the Profile page, and
(re)populated in bulk from the positioning strategy document by `extract_lanes`
(`lane_pipeline.py`) - never read live from the strategy document's prose.
"""

import sqlite3
from typing import Final

from pydantic import BaseModel

_COLUMNS = (
    "id, name, description, reasoning, position, fit_gap_summary, fit_gap_summary_generated_at"
)

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
    # The Dashboard's per-lane strengths/weaknesses summary (D-238, Agent/specs/lane-steps.md
    # §3) - null until "Analyze lanes" has run for this lane at least once.
    fit_gap_summary: str | None
    fit_gap_summary_generated_at: str | None


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


def set_fit_gap_summary(conn: sqlite3.Connection, lane_id: int, summary: str) -> None:
    """analyze_lane's own write (D-238, Agent/specs/lane-steps.md §3): a later run replaces both
    columns outright - there is no history of past summaries kept, the same "at most one current
    version" convention `positioning_breakdown` already uses."""
    with conn:
        conn.execute(
            "UPDATE lanes SET fit_gap_summary = ?, "
            "fit_gap_summary_generated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (summary, lane_id),
        )


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


def count_applications_with_a_lane(conn: sqlite3.Connection) -> int:
    """The "Clear all lanes" action's preview count (D-222)."""
    row = conn.execute("SELECT COUNT(*) FROM job_applications WHERE lane IS NOT NULL").fetchone()
    return int(row[0])


def clear_all_lanes(conn: sqlite3.Connection) -> int:
    """Clears `job_applications.lane` on every application, regardless of its current value -
    including one already set to Other (D-222). Returns the number actually cleared."""
    with conn:
        cursor = conn.execute("UPDATE job_applications SET lane = NULL WHERE lane IS NOT NULL")
    return cursor.rowcount


def _stale_lane_application_ids(conn: sqlite3.Connection) -> list[int]:
    """Applications whose stored `lane` doesn't match any approved name, case-insensitively -
    the same matching convention `validate_lane_name` uses. Left over from before a lane was
    renamed or removed from the catalog (D-222)."""
    approved = {name.casefold() for name in lane_names(conn)}
    rows = conn.execute("SELECT id, lane FROM job_applications WHERE lane IS NOT NULL").fetchall()
    return [row["id"] for row in rows if row["lane"].casefold() not in approved]


def count_lanes_not_in_list(conn: sqlite3.Connection) -> int:
    """The "Clear all not in list" action's preview count (D-222)."""
    return len(_stale_lane_application_ids(conn))


def clear_lanes_not_in_list(conn: sqlite3.Connection) -> int:
    """Clears `job_applications.lane` only where it doesn't match any approved name (D-222).
    Returns the number actually cleared."""
    stale_ids = _stale_lane_application_ids(conn)
    if stale_ids:
        placeholders = ", ".join("?" for _ in stale_ids)
        with conn:
            conn.execute(
                f"UPDATE job_applications SET lane = NULL WHERE id IN ({placeholders})",
                stale_ids,
            )
    return len(stale_ids)


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


## Lane overview (summarize_lanes, Phase 10, D-245) #############################################
# A single cross-lane report, not per-lane - stored in its own singleton table (the same
# `id INTEGER PRIMARY KEY CHECK (id = 1)` pattern `settings` already uses), since it isn't a
# per-row lane field.


class LaneOverview(BaseModel):
    summary: str | None
    generated_at: str | None


def get_lane_overview(conn: sqlite3.Connection) -> LaneOverview:
    row = conn.execute("SELECT summary, generated_at FROM lane_overview WHERE id = 1").fetchone()
    return LaneOverview(**dict(row))


def set_lane_overview(conn: sqlite3.Connection, summary: str) -> None:
    """summarize_lanes's own write (D-245): a later run replaces the stored report outright -
    there is no history of past overviews kept, the same "at most one current version"
    convention `lanes.fit_gap_summary` (D-238) already uses."""
    with conn:
        conn.execute(
            "UPDATE lane_overview SET summary = ?, "
            "generated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = 1",
            (summary,),
        )
