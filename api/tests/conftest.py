from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.migrations import migrate
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect, database_path

TEST_TOKEN = "test-token"


@pytest.fixture
def token() -> str:
    return TEST_TOKEN


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = database_path(tmp_path)
    conn = connect(path)
    migrate(conn)
    conn.close()
    return path


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner(text="OK")


@pytest.fixture
def client(db_path: Path, token: str, runner: FakeRunner) -> Iterator[TestClient]:
    with TestClient(create_app(token, db_path, runner)) as test_client:
        test_client.headers[TOKEN_HEADER] = token
        yield test_client
