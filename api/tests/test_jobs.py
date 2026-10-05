import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker import seed
from localjobtracker.app import create_app
from localjobtracker.jobs import count_jobs
from localjobtracker.runner import FakeRunner
from localjobtracker.storage import connect

FIXTURE = seed.DEFAULT_FIXTURE


def test_jobs_empty_database_returns_empty_list(client: TestClient) -> None:
    response = client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_jobs_without_token_is_rejected(db_path: Path, token: str) -> None:
    with TestClient(create_app(token, db_path, FakeRunner())) as bare:
        assert bare.get("/jobs").status_code == 401


def test_seed_then_jobs_lists_fixture_rows(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    monkeypatch.setattr("sys.argv", ["seed", "--db", str(db_path)])
    seed.main()

    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs = client.get("/jobs").json()
    assert len(jobs) == len(expected)
    assert {j["company"] for j in jobs} == {row["company"] for row in expected}
    assert all({"id", "company", "role_title", "status"} <= set(j) for j in jobs)


def test_jobs_are_ordered_with_undated_last(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, client: TestClient
) -> None:
    monkeypatch.setattr("sys.argv", ["seed", "--db", str(db_path)])
    seed.main()

    jobs = client.get("/jobs").json()
    dates = [j["due_date"] for j in jobs]
    dated = [d for d in dates if d is not None]
    assert dated == sorted(dated)
    assert dates[len(dated) :] == [None] * (len(dates) - len(dated))


def test_seed_twice_adds_no_duplicates(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["seed", "--db", str(db_path)])
    seed.main()
    seed.main()

    conn = connect(db_path)
    try:
        assert count_jobs(conn) == len(json.loads(FIXTURE.read_text(encoding="utf-8")))
    finally:
        conn.close()
    assert "skipped" in capsys.readouterr().out
