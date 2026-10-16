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


def test_lanes_start_with_only_the_default_other_lane(client: TestClient) -> None:
    """Migration 29 seeds Other (D-219) - a fresh install is never truly empty."""
    lanes = client.get("/lanes").json()
    assert [lane["name"] for lane in lanes] == ["Other"]
    assert lanes[0]["description"] == "Roles that don't clearly fit any of the lanes above."


def test_adding_a_lane_appends_it_with_the_next_position(client: TestClient) -> None:
    first = client.post("/lanes", json={"name": "Data Analytics", "description": "BI roles"})
    assert first.status_code == 201
    assert first.json()["position"] == 1  # position 0 is the seeded Other lane

    second = client.post("/lanes", json={"name": "Product Analytics"})
    assert second.status_code == 201
    assert second.json()["position"] == 2

    assert [lane["name"] for lane in client.get("/lanes").json()] == [
        "Other",
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
    assert [lane["name"] for lane in remaining] == [
        "Other",
        "Product Analytics",
        "Platform Engineering",
    ]
    assert [lane["position"] for lane in remaining][1:] == [2, third["position"]]


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


def set_lane(db_path: Path, application_id: int, lane: str | None) -> None:
    conn = connect(db_path)
    try:
        conn.execute("UPDATE job_applications SET lane = ? WHERE id = ?", (lane, application_id))
        conn.commit()
    finally:
        conn.close()


# --- Reassign missing lanes (D-222) -------------------------------------------------------------


def test_reassign_missing_preview_and_post_agree_and_skip_apps_that_already_have_a_lane(
    db_path: Path,
) -> None:
    ready_id = add_application(db_path, with_listing=True)
    no_listing_id = add_application(db_path, with_listing=False)
    already_set_id = add_application(db_path, with_listing=True)
    set_lane(db_path, already_set_id, "Data Analytics")

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        preview = client.get("/lanes/reassign-missing")
        assert preview.status_code == 200
        assert preview.json() == {"queued": 1, "skipped": 1}

        response = client.post("/lanes/reassign-missing")
        assert response.status_code == 200
        assert response.json() == {"queued": 1, "skipped": 1}

        jobs = client.get("/claude-jobs").json()
        assign_jobs = [job for job in jobs if job["kind"] == "assign_job_lane"]
        assert [job["job_application_id"] for job in assign_jobs] == [ready_id]
        # Confirms the preview changed nothing - still exactly one queued job afterward.
        assert no_listing_id not in [job["job_application_id"] for job in assign_jobs]
        assert already_set_id not in [job["job_application_id"] for job in assign_jobs]


# --- Clear all lanes (D-222) ---------------------------------------------------------------------


def test_clear_all_preview_changes_nothing(db_path: Path) -> None:
    app_id = add_application(db_path, with_listing=False)
    set_lane(db_path, app_id, "Data Analytics")

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        assert client.get("/lanes/clear-all").json() == {"cleared": 1}
        assert client.get(f"/job-applications/{app_id}").json()["lane"] == "Data Analytics"


def test_clear_all_route_clears_every_application_including_other(db_path: Path) -> None:
    other_id = add_application(db_path, with_listing=False)
    set_lane(db_path, other_id, "Other")
    real_id = add_application(db_path, with_listing=False)
    set_lane(db_path, real_id, "Data Analytics")
    unset_id = add_application(db_path, with_listing=False)

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post("/lanes/clear-all")
        assert response.status_code == 200
        assert response.json() == {"cleared": 2}
        assert client.get(f"/job-applications/{other_id}").json()["lane"] is None
        assert client.get(f"/job-applications/{real_id}").json()["lane"] is None
        assert client.get(f"/job-applications/{unset_id}").json()["lane"] is None


# --- Clear lanes not in the approved list (D-222) ------------------------------------------------


def test_clear_not_in_list_preview_and_post_agree(db_path: Path) -> None:
    stale_id = add_application(db_path, with_listing=False)
    set_lane(db_path, stale_id, "Deleted Lane")
    approved_id = add_application(db_path, with_listing=False)
    set_lane(db_path, approved_id, "Other")

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        preview = client.get("/lanes/clear-not-in-list")
        assert preview.status_code == 200
        assert preview.json() == {"cleared": 1}

        response = client.post("/lanes/clear-not-in-list")
        assert response.status_code == 200
        assert response.json() == {"cleared": 1}

        assert client.get(f"/job-applications/{stale_id}").json()["lane"] is None
        assert client.get(f"/job-applications/{approved_id}").json()["lane"] == "Other"


def test_clear_not_in_list_matches_case_insensitively(db_path: Path) -> None:
    app_id = add_application(db_path, with_listing=False)
    set_lane(db_path, app_id, "other")  # lowercase - still matches the approved "Other"

    with TestClient(create_app(TOKEN, db_path, FakeRunner(text="OK"))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        response = client.post("/lanes/clear-not-in-list")
        assert response.json() == {"cleared": 0}
        assert client.get(f"/job-applications/{app_id}").json()["lane"] == "other"
