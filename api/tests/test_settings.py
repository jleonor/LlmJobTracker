from fastapi.testclient import TestClient


def test_settings_default_to_your_name(client: TestClient) -> None:
    response = client.get("/settings")
    assert response.status_code == 200
    assert response.json() == {"user_name": "YourName"}


def test_saving_a_name_is_read_back(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "Alex"})
    assert saved.status_code == 200
    assert saved.json() == {"user_name": "Alex"}

    read_again = client.get("/settings")
    assert read_again.json() == {"user_name": "Alex"}


def test_saving_a_blank_name_falls_back_to_your_name(client: TestClient) -> None:
    client.put("/settings", json={"user_name": "Alex"})

    saved = client.put("/settings", json={"user_name": "   "})

    assert saved.json() == {"user_name": "YourName"}


def test_saving_trims_whitespace(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "  Alex  "})
    assert saved.json() == {"user_name": "Alex"}
