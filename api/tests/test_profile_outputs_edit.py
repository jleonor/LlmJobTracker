import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_profile_pipeline import (
    FIXTURES,
    CannedRunner,
    good_answers,
    make_queue,
    run_all,
    start,
    store,
)

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.claude_job_queue import PromptRejected
from localjobtracker.profile_pipeline import save_user_version
from localjobtracker.storage import connect

TOKEN = "test-token"


@pytest.fixture
def analysed(db_path: Path) -> int:
    """A finished analysis. Returns the id of the CV the answers cite."""
    cv = store(db_path, "master_cv_en", "cv_en.pdf", (FIXTURES / "cv_en.pdf").read_bytes())
    store(db_path, "questionnaire", "q.txt", (FIXTURES / "questionnaire.txt").read_bytes())
    queue = make_queue(db_path, CannedRunner(good_answers(cv)))
    start(db_path, queue)
    run_all(queue)
    return cv


def versions(db_path: Path, kind: str) -> list[int]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT version FROM profile_outputs WHERE kind = ? ORDER BY version", (kind,)
        ).fetchall()
    finally:
        conn.close()
    return [int(row[0]) for row in rows]


def latest_body(db_path: Path, kind: str) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT body_json FROM profile_outputs WHERE kind = ? ORDER BY version DESC LIMIT 1",
            (kind,),
        ).fetchone()
    finally:
        conn.close()
    body: dict[str, Any] = json.loads(row[0])
    return body


def test_an_edited_history_is_stored_as_a_new_version_and_the_first_is_kept(
    db_path: Path, analysed: int
) -> None:
    conn = connect(db_path)
    try:
        body = latest_body(db_path, "full_cv_history")
        body["items"][0]["text"] = "Senior analyst, Example Corp"
        saved = save_user_version(conn, "full_cv_history", body)
    finally:
        conn.close()

    assert saved.version == 2
    assert saved.claude_job_id is None
    assert versions(db_path, "full_cv_history") == [1, 2]
    assert latest_body(db_path, "full_cv_history")["items"][0]["text"].startswith("Senior")


def test_a_history_edit_must_pass_the_same_checks(db_path: Path, analysed: int) -> None:
    body = latest_body(db_path, "full_cv_history")
    body["items"][0]["date"] = "sometime"
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="date must be"):
            save_user_version(conn, "full_cv_history", body)
    finally:
        conn.close()
    assert versions(db_path, "full_cv_history") == [1]


def test_a_renamed_lane_is_stored_and_keeps_its_facts(db_path: Path, analysed: int) -> None:
    body = copy.deepcopy(latest_body(db_path, "strategy"))
    body["lanes"][0]["name"] = "Analytics and reporting"
    conn = connect(db_path)
    try:
        saved = save_user_version(conn, "strategy", body)
    finally:
        conn.close()

    assert saved.version == 2
    assert saved.body["lanes"][0]["name"] == "Analytics and reporting"
    assert saved.body["lanes"][0]["fact_ids"] == ["F-001"]


def test_a_lane_cannot_cite_a_fact_that_does_not_exist(db_path: Path, analysed: int) -> None:
    body = copy.deepcopy(latest_body(db_path, "strategy"))
    body["lanes"][0]["fact_ids"] = ["F-999"]
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="unknown id F-999"):
            save_user_version(conn, "strategy", body)
    finally:
        conn.close()


def test_other_outputs_cannot_be_edited(db_path: Path, analysed: int) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="cannot be edited"):
            save_user_version(conn, "fact_sheet", {"facts": [], "conflicts": []})
    finally:
        conn.close()


def test_the_put_route_saves_an_edit_and_refuses_a_bad_one(db_path: Path, analysed: int) -> None:
    with TestClient(create_app(TOKEN, db_path, CannedRunner({}))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        body = latest_body(db_path, "strategy")
        body["overview"] = "A clearer overview."

        saved = client.put("/profile/outputs/strategy", json=body)
        assert saved.status_code == 200
        assert saved.json()["version"] == 2

        body["lanes"][0]["fact_ids"] = []
        refused = client.put("/profile/outputs/strategy", json=body)
        assert refused.status_code == 400
        assert "lane needs at least one fact" in refused.json()["detail"]
