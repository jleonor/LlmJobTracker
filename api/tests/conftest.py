from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app
from localjobtracker.migrations import migrate
from localjobtracker.storage import connect, database_path

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
def client(db_path: Path, token: str) -> Iterator[TestClient]:
    with TestClient(create_app(token, db_path)) as test_client:
        test_client.headers[TOKEN_HEADER] = token
        yield test_client
