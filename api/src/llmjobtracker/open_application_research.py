"""An Open Application's up to 5 research items: a URL or pasted text each, extracted the same
way Listing's own intake extracts one (listing_intake.py, reused directly — D-251).
"""

import sqlite3

from pydantic import BaseModel

from llmjobtracker.listing_intake import ListingFetchError, extract_from_paste, extract_from_url

MAX_RESEARCH_ITEMS = 5


class ResearchItemInput(BaseModel):
    """One research item as "Add Open Application" or Company details' Generate overlay
    submits it — a URL or pasted text, not yet extracted."""

    source_type: str  # "url" | "text"
    content: str


class ResearchItem(BaseModel):
    id: int
    position: int
    source_type: str
    content: str
    extracted_text: str | None
    extraction_status: str | None
    extraction_message: str | None


class InvalidResearchItem(Exception):
    """Too many items, or an item whose source_type isn't url/text."""


def extract_research_item(item: ResearchItemInput) -> tuple[str | None, str | None, str | None]:
    """Returns (extracted_text, extraction_status, extraction_message) for one item, reusing
    listing_intake.py's own code-only extraction (D-251: no new extraction logic)."""
    if item.source_type == "url":
        try:
            result = extract_from_url(item.content)
        except ListingFetchError as error:
            return None, "failed", error.message
    elif item.source_type == "text":
        result = extract_from_paste(item.content)
    else:
        raise InvalidResearchItem(f"Unknown source_type: {item.source_type!r}")
    return result.text, result.status, result.message


def replace_research_items(
    conn: sqlite3.Connection, application_id: int, items: list[ResearchItemInput]
) -> list[ResearchItem]:
    """Replace every research item for this application with `items`, in order — "Add Open
    Application" and Company details' Generate overlay both submit the whole set at once rather
    than editing one item at a time (D-251)."""
    if len(items) > MAX_RESEARCH_ITEMS:
        raise InvalidResearchItem(f"At most {MAX_RESEARCH_ITEMS} research items are allowed.")
    extracted = [extract_research_item(item) for item in items]
    with conn:
        conn.execute(
            "DELETE FROM open_application_research_items WHERE open_application_id = ?",
            (application_id,),
        )
        conn.executemany(
            """
            INSERT INTO open_application_research_items (
                open_application_id, position, source_type, content,
                extracted_text, extraction_status, extraction_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    application_id,
                    position,
                    item.source_type,
                    item.content,
                    text,
                    status,
                    message,
                )
                for position, (item, (text, status, message)) in enumerate(
                    zip(items, extracted, strict=True), start=1
                )
            ],
        )
    return list_research_items(conn, application_id)


def list_research_items(conn: sqlite3.Connection, application_id: int) -> list[ResearchItem]:
    rows = conn.execute(
        "SELECT id, position, source_type, content, extracted_text, "
        "extraction_status, extraction_message "
        "FROM open_application_research_items WHERE open_application_id = ? ORDER BY position",
        (application_id,),
    ).fetchall()
    return [
        ResearchItem(
            id=row["id"],
            position=row["position"],
            source_type=row["source_type"],
            content=row["content"],
            extracted_text=row["extracted_text"],
            extraction_status=row["extraction_status"],
            extraction_message=row["extraction_message"],
        )
        for row in rows
    ]


def concatenated_research_text(conn: sqlite3.Connection, application_id: int) -> str:
    """Every research item's extracted text, in position order, unlabeled (D-251) — what a
    prompt builder reads as this application's RESEARCH block."""
    rows = conn.execute(
        "SELECT extracted_text FROM open_application_research_items "
        "WHERE open_application_id = ? ORDER BY position",
        (application_id,),
    ).fetchall()
    texts = [str(row["extracted_text"]) for row in rows if row["extracted_text"]]
    return "\n\n---\n\n".join(texts)
