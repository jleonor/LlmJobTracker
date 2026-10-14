from fastapi.testclient import TestClient

DEFAULTS = {
    "backend": "claude_code",
    "retry_policy": "reset_time",
    "retry_interval_minutes": 60,
    "retry_max_attempts": 24,
}


def test_settings_default_to_your_name(client: TestClient) -> None:
    response = client.get("/settings")
    assert response.status_code == 200
    assert response.json() == {"user_name": "YourName", **DEFAULTS}


def test_saving_a_name_is_read_back(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "Alex"})
    assert saved.status_code == 200
    assert saved.json() == {"user_name": "Alex", **DEFAULTS}

    read_again = client.get("/settings")
    assert read_again.json() == {"user_name": "Alex", **DEFAULTS}


def test_saving_a_blank_name_falls_back_to_your_name(client: TestClient) -> None:
    client.put("/settings", json={"user_name": "Alex"})

    saved = client.put("/settings", json={"user_name": "   "})

    assert saved.json() == {"user_name": "YourName", **DEFAULTS}


def test_saving_trims_whitespace(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "  Alex  "})
    assert saved.json() == {"user_name": "Alex", **DEFAULTS}


def test_saving_only_the_name_keeps_the_backend_and_retry_policy(client: TestClient) -> None:
    client.put(
        "/settings",
        json={"user_name": "Alex", "backend": "codex", "retry_policy": "fixed_interval"},
    )

    saved = client.put("/settings", json={"user_name": "Alex Again"})

    assert saved.json() == {
        "user_name": "Alex Again",
        "backend": "codex",
        "retry_policy": "fixed_interval",
        "retry_interval_minutes": 60,
        "retry_max_attempts": 24,
    }


def test_saving_the_backend_and_retry_policy(client: TestClient) -> None:
    saved = client.put(
        "/settings",
        json={
            "user_name": "YourName",
            "backend": "codex",
            "retry_policy": "fixed_interval",
            "retry_interval_minutes": 30,
            "retry_max_attempts": 10,
        },
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "user_name": "YourName",
        "backend": "codex",
        "retry_policy": "fixed_interval",
        "retry_interval_minutes": 30,
        "retry_max_attempts": 10,
    }


def test_an_unknown_backend_is_rejected(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "YourName", "backend": "chatgpt"})
    assert saved.status_code == 422


def test_a_non_positive_retry_interval_is_rejected(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "YourName", "retry_interval_minutes": 0})
    assert saved.status_code == 422
