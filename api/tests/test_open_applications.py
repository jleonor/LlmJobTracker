from pathlib import Path

from llmjobtracker.open_applications import (
    NoStatusEntries,
    UnknownField,
    count_open_applications,
    delete_open_application,
    get_open_application_detail,
    insert_open_application,
    list_open_applications,
    replace_status_history,
    update_open_application,
)
from llmjobtracker.storage import connect


def test_insert_creates_a_bare_row_with_identified_status(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.status == "Identified"
    assert detail.target_name is None
    assert len(detail.status_history) == 1
    assert detail.status_history[0].status == "Identified"


def test_insert_keeps_whatever_fields_were_pre_filled(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(
        conn, {"target_name": "Acme Talent Pool", "target_type": "talent_pool"}
    )
    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.target_name == "Acme Talent Pool"
    assert detail.target_type == "talent_pool"


def test_list_orders_by_last_updated_and_reports_has_flags(db_path: Path) -> None:
    conn = connect(db_path)
    insert_open_application(conn, {"target_name": "Older"})
    insert_open_application(conn, {"target_name": "Newer"})
    rows = list_open_applications(conn)
    assert [row.target_name for row in rows] == ["Newer", "Older"]
    assert rows[0].has_company_details is True
    assert rows[0].has_tailored_cv is False
    assert rows[0].has_cover_letter is False
    assert rows[0].has_introduction_message is False


def test_list_carries_status_history_for_the_dashboard(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    rows = list_open_applications(conn)
    assert len(rows) == 1
    assert len(rows[0].status_history) == 1
    assert rows[0].status_history[0].status == "Identified"
    assert rows[0].id == application_id


def test_count_matches_the_number_of_rows(db_path: Path) -> None:
    conn = connect(db_path)
    assert count_open_applications(conn) == 0
    insert_open_application(conn, {})
    insert_open_application(conn, {})
    assert count_open_applications(conn) == 2


def test_update_only_writes_fields_actually_sent(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    update_open_application(conn, application_id, {"angle": "A mutual contact introduced me."})
    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.target_name == "Acme"
    assert detail.angle == "A mutual contact introduced me."


def test_update_rejects_an_unknown_field(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    try:
        update_open_application(conn, application_id, {"match_score": 80})
        raised = False
    except UnknownField:
        raised = True
    assert raised


def test_update_returns_none_for_a_missing_application(db_path: Path) -> None:
    conn = connect(db_path)
    assert update_open_application(conn, 999, {"target_name": "x"}) is None


def test_replace_status_history_recomputes_the_current_status(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    replace_status_history(
        conn,
        application_id,
        [("Identified", "2026-10-01T00:00:00Z"), ("Applied", "2026-10-05T00:00:00Z")],
    )
    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.status == "Applied"
    assert len(detail.status_history) == 2


def test_replace_status_history_an_end_state_wins_regardless_of_date(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    replace_status_history(
        conn,
        application_id,
        [
            ("Identified", "2026-10-01T00:00:00Z"),
            ("Applied", "2026-10-05T00:00:00Z"),
            ("Expired", "2026-10-03T00:00:00Z"),
        ],
    )
    detail = get_open_application_detail(conn, application_id)
    assert detail is not None
    assert detail.status == "Expired"


def test_replace_status_history_rejects_an_empty_list(db_path: Path) -> None:
    conn = connect(db_path)
    application_id = insert_open_application(conn, {})
    try:
        replace_status_history(conn, application_id, [])
        raised = False
    except NoStatusEntries:
        raised = True
    assert raised


def test_delete_removes_the_row_and_its_managed_folder(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    files_root = tmp_path / "files"
    application_id = insert_open_application(conn, {"target_name": "Acme"})
    folder = files_root / "Open Applications" / f"Acme ({application_id})"
    folder.mkdir(parents=True)
    (folder / "placeholder.txt").write_text("x", encoding="utf-8")

    assert delete_open_application(conn, files_root, application_id) is True
    assert get_open_application_detail(conn, application_id) is None
    assert not folder.exists()


def test_delete_returns_false_for_a_missing_application(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    assert delete_open_application(conn, tmp_path / "files", 999) is False
