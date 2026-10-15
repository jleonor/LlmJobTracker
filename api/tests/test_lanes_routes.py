"""Tests for the /lanes routes (Agent/specs/lane-steps.md, D-214): CRUD on the approved lane
catalog, plus the "Sync from strategy" action.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import insert_job_file
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

TOKEN = "test-token"


def write_strategy(db_path: Path, text: str = "Lead with data work.") -> None:
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_outputs (kind, version, document, input_sha256s) "
            "VALUES ('strategy', 1, ?, '[]')",
            (text,),
        )
        conn.commit()
    finally:
        conn.close()


def add_application(db_path: Path, *, with_listing: bool) -> int:
    conn = connect(db_path)
    try:
        app_id = insert_job_application(conn, {"company": "Acme Inc", "role_title": "Analyst"})
        if with_listing:
            insert_job_file(
                conn,
                app_id,
                kind="listing",
                name="Job Listing.md",
                stored_path=f"Acme Inc/Analyst {app_id}/Job Listing.md",
                extracted_text="Senior Data Analyst, must know SQL.",
            )
        conn.commit()
    finally:
        conn.close()
    return app_id


def test_lanes_start_empty(client: TestClient) -> None:
    assert client.get("/lanes").json() == []


def test_adding_a_lane_appends_it_with_the_next_position(client: TestClient) -> None:
    first = client.post("/lanes", json={"name": "Data Analytics", "description": "BI roles"})
    assert first.status_code == 201
    assert first.json()["position"] == 0

    second = client.post("/lanes", json={"name": "Product Analytics"})
    assert second.status_code == 201
    assert second.json()["position"] == 1

    assert [lane["name"] for lane in client.get("/lanes").json()] == [
        "Data Analytics",
        "Product Analytics",
    ]


def test_adding_a_lane_with_a_blank_name_is_rejected(client: TestClient) -> None:
    response = client.post("/lanes", json={"name": "   "})
    assert response.status_code == 422


def test_editing_a_lane_updates_only_the_sent_fields(client: TestClient) -> None:
    created = client.post("/lanes", json={"name": "Data Analytics", "description": "old"})
    lane_id = created.json()["id"]

    edited = client.patch(f"/lanes/{lane_id}", json={"description": "new description"})
    assert edited.status_code == 200
    assert edited.json()["name"] == "Data Analytics"
    assert edited.json()["description"] == "new description"


def test_editing_an_unknown_lane_is_not_found(client: TestClient) -> None:
    assert client.patch("/lanes/999", json={"name": "x"}).status_code == 404


def test_removing_a_lane_leaves_the_others_positions_unchanged(client: TestClient) -> None:
    first = client.post("/lanes", json={"name": "Data Analytics"}).json()
    client.post("/lanes", json={"name": "Product Analytics"})
    third = client.post("/lanes", json={"name": "Platform Engineering"}).json()

    removed = client.delete(f"/lanes/{first['id']}")
    assert removed.status_code == 204

    remaining = client.get("/lanes").json()
    assert [lane["name"] for lane in remaining] == ["Product Analytics", "Platform Engineering"]
    assert [lane["position"] for lane in remaining] == [1, third["position"]]


def test_sync_route_requires_a_strategy_document(client: TestClient) -> None:
    assert client.post("/lanes/sync").status_code == 400


def test_sync_route_replaces_the_stored_lanes(db_path: Path) -> None:
    write_strategy(db_path)
    answer = (
        "=== LANE ===\n"
        "NAME: Data Analytics\n"
        "DESCRIPTION: Reporting and dashboards.\n"
        "REASONING: Matches past BI work.\n"
        "=== END LANE ==="
    )
    with TestClient(create_app(TOKEN, db_path, FakeRunner(text=answer))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        client.post("/lanes", json={"name": "Old Lane"})

        response = client.post("/lanes/sync")
        assert response.status_code == 201
        assert response.json()["kind"] == "extract_lanes"


def test_reassign_all_route_skips_applications_with_no_listing(client: TestClient) -> None:
    assert client.post("/lanes/reassign-all").json() == {"queued": 0, "skipped": 0}


def test_reassign_all_route_counts_queued_and_skipped(db_path: Path) -> None:
    add_application(db_path, with_listing=True)
    add_application(db_path, with_listing=True)
    add_application(db_path, with_listing=False)

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post("/lanes/reassign-all")
        assert response.status_code == 200
        assert response.json() == {"queued": 2, "skipped": 1}
