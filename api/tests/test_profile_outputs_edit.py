from pathlib import Path

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
    cv = store(db_path, "master_cv", "cv_en.pdf", (FIXTURES / "cv_en.pdf").read_bytes())
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


def latest_document(db_path: Path, kind: str) -> str:
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT document FROM profile_outputs WHERE kind = ? ORDER BY version DESC LIMIT 1",
            (kind,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0])


def test_an_edited_history_is_stored_as_a_new_version_and_the_first_is_kept(
    db_path: Path, analysed: int
) -> None:
    conn = connect(db_path)
    try:
        edited = latest_document(db_path, "full_cv_history") + "\n\nSenior analyst, Example Corp."
        saved = save_user_version(conn, db_path.parent, "full_cv_history", edited)
    finally:
        conn.close()

    assert saved.version == 2
    assert saved.claude_job_id is None
    assert versions(db_path, "full_cv_history") == [1, 2]
    assert latest_document(db_path, "full_cv_history").endswith("Senior analyst, Example Corp.")


def test_an_empty_edit_is_refused(db_path: Path, analysed: int) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="needs some text"):
            save_user_version(conn, db_path.parent, "full_cv_history", "   ")
    finally:
        conn.close()
    assert versions(db_path, "full_cv_history") == [1]


def test_an_unknown_kind_cannot_be_edited(db_path: Path, analysed: int) -> None:
    conn = connect(db_path)
    try:
        with pytest.raises(PromptRejected, match="cannot be edited"):
            save_user_version(conn, db_path.parent, "nonexistent", "Some text.")
    finally:
        conn.close()


def test_an_edit_updates_the_readable_generated_file_copy(db_path: Path, analysed: int) -> None:
    conn = connect(db_path)
    try:
        before = conn.execute(
            "SELECT sha256 FROM profile_files WHERE kind = 'own_strategy'"
        ).fetchone()[0]
        edited = latest_document(db_path, "strategy") + "\n\nA clearer differentiator."
        save_user_version(conn, db_path.parent, "strategy", edited)
        after = conn.execute(
            "SELECT sha256, generated FROM profile_files WHERE kind = 'own_strategy'"
        ).fetchone()
    finally:
        conn.close()

    assert after["sha256"] != before
    assert after["generated"] == 1


def test_the_put_route_saves_an_edit(db_path: Path, analysed: int) -> None:
    with TestClient(create_app(TOKEN, db_path, CannedRunner({}))) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        edited = latest_document(db_path, "strategy") + "\n\nA clearer differentiator."

        saved = client.put("/profile/outputs/strategy", json={"text": edited})
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        assert saved.json()["document"] == edited

        refused = client.put("/profile/outputs/strategy", json={"text": "   "})
        assert refused.status_code == 400
        assert "needs some text" in refused.json()["detail"]
