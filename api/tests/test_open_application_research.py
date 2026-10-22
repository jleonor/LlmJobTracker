from pathlib import Path

from llmjobtracker.open_application_research import (
    InvalidResearchItem,
    ResearchItemInput,
    concatenated_research_text,
    list_research_items,
    replace_research_items,
)
from llmjobtracker.open_applications import insert_open_application
from llmjobtracker.storage import connect


def test_replace_research_items_extracts_pasted_text(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    items = replace_research_items(
        conn,
        application_id,
        [
            ResearchItemInput(source_type="text", content="Acme is a fintech startup."),
            ResearchItemInput(source_type="text", content="They just raised a Series B."),
        ],
    )
    assert [item.position for item in items] == [1, 2]
    assert items[0].extraction_status == "ok"
    assert items[0].extracted_text == "Acme is a fintech startup."


def test_replace_research_items_rejects_more_than_five(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    items = [ResearchItemInput(source_type="text", content=f"item {i}") for i in range(6)]
    try:
        replace_research_items(conn, application_id, items)
        raised = False
    except InvalidResearchItem:
        raised = True
    assert raised


def test_concatenated_research_text_joins_items_in_position_order(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    replace_research_items(
        conn,
        application_id,
        [
            ResearchItemInput(source_type="text", content="First item."),
            ResearchItemInput(source_type="text", content="Second item."),
        ],
    )
    text = concatenated_research_text(conn, application_id)
    assert text.index("First item.") < text.index("Second item.")


def test_replace_research_items_replaces_the_whole_set(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    replace_research_items(
        conn, application_id, [ResearchItemInput(source_type="text", content="Old item.")]
    )
    replace_research_items(
        conn, application_id, [ResearchItemInput(source_type="text", content="New item.")]
    )
    items = list_research_items(conn, application_id)
    assert len(items) == 1
    assert items[0].content == "New item."
