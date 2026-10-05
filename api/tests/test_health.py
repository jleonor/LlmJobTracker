from fastapi.testclient import TestClient

from localjobtracker.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


def client() -> TestClient:
    return TestClient(create_app(TOKEN))


def test_health_with_token_returns_ok() -> None:
    response = client().get("/health", headers={TOKEN_HEADER: TOKEN})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_without_token_is_rejected() -> None:
    assert client().get("/health").status_code == 401


def test_health_with_wrong_token_is_rejected() -> None:
    response = client().get("/health", headers={TOKEN_HEADER: "wrong"})
    assert response.status_code == 401
