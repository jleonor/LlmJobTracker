import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.profile_facts import FactUpdate, fact_sheet, update_fact, verified_facts
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

TOKEN = "test-token"


def seed_fact_sheet(db_path: Path, version: int = 1) -> tuple[int, int, int]:
    """Insert one CV and a Fact Sheet with two facts and a conflict.

    Returns the ids of the CV, the output and the first fact.
    """
    conn = connect(db_path)
    try:
        with conn:
            file_id = conn.execute(
                """
                INSERT INTO profile_files
                    (kind, original_name, stored_path, sha256, size_bytes, extraction_status)
                VALUES ('master_cv', 'cv_en.pdf', 'profile/cv.pdf', 'abc', 10, 'ok')
                """
            ).lastrowid
            body = {
                "facts": [],
                "conflicts": [
                    {"id": "C-01", "fact_ids": ["F-001", "F-002"], "note": "End year differs."}
                ],
            }
            output_id = conn.execute(
                """
                INSERT INTO profile_outputs (kind, version, body_json, input_sha256s)
                VALUES ('fact_sheet', ?, ?, '[]')
                """,
                (version, json.dumps(body)),
            ).lastrowid
            fact_ids = []
            for key, text, date, location in [
                ("F-001", "Worked as an analyst.", "2020", "Line 2"),
                ("F-002", "Analyst role ended in 2022.", "2022", "Line 3"),
            ]:
                fact_ids.append(
                    conn.execute(
                        """
                        INSERT INTO facts
                            (profile_output_id, fact_key, text, date, source_file_id,
                             source_location)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (output_id, key, text, date, file_id, location),
                    ).lastrowid
                )
    finally:
        conn.close()
    assert file_id is not None and output_id is not None and fact_ids[0] is not None
    return int(file_id), int(output_id), int(fact_ids[0])


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    yield connection
    connection.close()


def test_the_fact_sheet_lists_facts_with_source_names_and_conflicts(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    seed_fact_sheet(db_path)
    sheet = fact_sheet(conn)
    assert sheet.version == 1
    assert [fact.fact_key for fact in sheet.facts] == ["F-001", "F-002"]
    assert sheet.facts[0].source_name == "cv_en.pdf"
    assert sheet.facts[0].status == "unverified"
    assert [conflict.id for conflict in sheet.conflicts] == ["C-01"]


def test_an_empty_database_has_an_empty_fact_sheet(conn: sqlite3.Connection) -> None:
    sheet = fact_sheet(conn)
    assert sheet.output_id is None and sheet.facts == []


def test_only_verified_facts_are_usable(db_path: Path, conn: sqlite3.Connection) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    assert verified_facts(conn) == []

    update_fact(conn, first, FactUpdate(status="verified"))
    usable = verified_facts(conn)
    assert [fact.fact_key for fact in usable] == ["F-001"]
    assert usable[0].source_location == "Line 2"


def test_a_rejected_fact_is_not_usable(db_path: Path, conn: sqlite3.Connection) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    update_fact(conn, first, FactUpdate(status="verified"))
    update_fact(conn, first, FactUpdate(status="rejected"))
    assert verified_facts(conn) == []


def test_editing_the_text_makes_a_verified_fact_unverified_again(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    update_fact(conn, first, FactUpdate(status="verified"))

    edited = update_fact(conn, first, FactUpdate(text="Worked as a senior analyst."))
    assert edited.text == "Worked as a senior analyst."
    assert edited.status == "unverified"
    assert verified_facts(conn) == []


def test_editing_and_verifying_in_one_change_keeps_the_verification(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    edited = update_fact(
        conn, first, FactUpdate(text="Worked as a senior analyst.", status="verified")
    )
    assert edited.status == "verified"


def test_a_date_must_have_a_valid_form(db_path: Path, conn: sqlite3.Connection) -> None:
    from localjobtracker.profile_facts import FactError

    _file, _output, first = seed_fact_sheet(db_path)
    with pytest.raises(FactError) as refused:
        update_fact(conn, first, FactUpdate(date="last spring"))
    assert refused.value.status == 400


def test_an_empty_text_or_an_unknown_status_is_refused(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    from localjobtracker.profile_facts import FactError

    _file, _output, first = seed_fact_sheet(db_path)
    with pytest.raises(FactError):
        update_fact(conn, first, FactUpdate(text="   "))
    with pytest.raises(FactError):
        update_fact(conn, first, FactUpdate(status="maybe"))


def test_a_fact_from_an_older_version_cannot_be_changed(
    db_path: Path, conn: sqlite3.Connection
) -> None:
    from localjobtracker.profile_facts import FactError

    _file, _output, old_fact = seed_fact_sheet(db_path, version=1)
    seed_fact_sheet(db_path, version=2)
    with pytest.raises(FactError) as refused:
        update_fact(conn, old_fact, FactUpdate(status="verified"))
    assert refused.value.status == 404
    assert verified_facts(conn) == []


@pytest.fixture
def fact_client(db_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(TOKEN, db_path, FakeRunner())) as test_client:
        test_client.headers[TOKEN_HEADER] = TOKEN
        yield test_client


def test_the_facts_route_returns_the_latest_sheet(db_path: Path, fact_client: TestClient) -> None:
    seed_fact_sheet(db_path)
    body = fact_client.get("/profile/facts").json()
    assert [fact["fact_key"] for fact in body["facts"]] == ["F-001", "F-002"]
    assert body["conflicts"][0]["fact_ids"] == ["F-001", "F-002"]


def test_patching_a_fact_verifies_it(db_path: Path, fact_client: TestClient) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    response = fact_client.patch(f"/profile/facts/{first}", json={"status": "verified"})
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_patching_with_a_bad_date_returns_400(db_path: Path, fact_client: TestClient) -> None:
    _file, _output, first = seed_fact_sheet(db_path)
    response = fact_client.patch(f"/profile/facts/{first}", json={"date": "someday"})
    assert response.status_code == 400
    assert "YYYY" in response.json()["detail"]


def test_patching_an_unknown_fact_returns_404(fact_client: TestClient) -> None:
    assert fact_client.patch("/profile/facts/999", json={"status": "verified"}).status_code == 404
