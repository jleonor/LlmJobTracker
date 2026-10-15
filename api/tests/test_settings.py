from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from llmjobtracker import app as app_module
from llmjobtracker.app import TOKEN_HEADER, create_app
from llmjobtracker.claude_job_queue import ClaudeJobQueue
from llmjobtracker.runner import AuthStatus, FakeRunner

TOKEN = "test-token"

DEFAULTS = {
    "backend": "claude_code",
    "retry_policy": "reset_time",
    "retry_interval_minutes": 60,
    "retry_max_attempts": 24,
    "claude_code_model": "claude-sonnet-5",
    "codex_model": "gpt-6.1-sol",
    "llm_export_path": None,
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
        "claude_code_model": "claude-sonnet-5",
        "codex_model": "gpt-6.1-sol",
        "llm_export_path": None,
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
        "claude_code_model": "claude-sonnet-5",
        "codex_model": "gpt-6.1-sol",
        "llm_export_path": None,
    }


def test_saving_an_llm_export_path_is_read_back(client: TestClient) -> None:
    saved = client.put(
        "/settings",
        json={"user_name": "YourName", "llm_export_path": "D:\\Exports\\MyTracker"},
    )
    assert saved.status_code == 200
    assert saved.json()["llm_export_path"] == "D:\\Exports\\MyTracker"

    read_again = client.get("/settings")
    assert read_again.json()["llm_export_path"] == "D:\\Exports\\MyTracker"


def test_saving_only_the_name_keeps_the_llm_export_path(client: TestClient) -> None:
    client.put("/settings", json={"user_name": "Alex", "llm_export_path": "D:\\Exports\\MyTracker"})

    saved = client.put("/settings", json={"user_name": "Alex Again"})

    assert saved.json()["llm_export_path"] == "D:\\Exports\\MyTracker"


def test_saving_a_blank_llm_export_path_clears_it(client: TestClient) -> None:
    client.put(
        "/settings", json={"user_name": "YourName", "llm_export_path": "D:\\Exports\\MyTracker"}
    )

    saved = client.put("/settings", json={"user_name": "YourName", "llm_export_path": "   "})

    assert saved.json()["llm_export_path"] is None


def test_an_unknown_backend_is_rejected(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "YourName", "backend": "chatgpt"})
    assert saved.status_code == 422


def test_a_non_positive_retry_interval_is_rejected(client: TestClient) -> None:
    saved = client.put("/settings", json={"user_name": "YourName", "retry_interval_minutes": 0})
    assert saved.status_code == 422


# --- Price table (D-198) ---------------------------------------------------------------------


def test_prices_start_empty(client: TestClient) -> None:
    assert client.get("/settings/prices").json() == []


def test_saving_one_price_by_hand_is_read_back(client: TestClient) -> None:
    saved = client.put(
        "/settings/prices/codex/gpt-6.1-sol",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["provider"] == "codex"
    assert body["model"] == "gpt-6.1-sol"

    listed = client.get("/settings/prices").json()
    assert [row["model"] for row in listed] == ["gpt-6.1-sol"]


def test_saving_a_price_for_an_unknown_provider_is_rejected(client: TestClient) -> None:
    saved = client.put(
        "/settings/prices/chatgpt/gpt-5",
        json={"input_price_per_token": 1, "output_price_per_token": 1},
    )
    assert saved.status_code == 422


def test_deleting_a_price_removes_it(client: TestClient) -> None:
    client.put(
        "/settings/prices/codex/gpt-6.1-sol",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )

    deleted = client.delete("/settings/prices/codex/gpt-6.1-sol")

    assert deleted.status_code == 204
    assert client.get("/settings/prices").json() == []


def test_renaming_a_price_keeps_its_values_under_the_new_name(client: TestClient) -> None:
    client.put(
        "/settings/prices/codex/gtp-6.1-sol",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )

    renamed = client.put(
        "/settings/prices/codex/gtp-6.1-sol/rename", json={"new_model": "gpt-6.1-sol"}
    )

    assert renamed.status_code == 200
    body = renamed.json()
    assert body["model"] == "gpt-6.1-sol"
    assert body["input_price_per_token"] == pytest.approx(0.000003)
    listed = client.get("/settings/prices").json()
    assert [row["model"] for row in listed] == ["gpt-6.1-sol"]


def test_renaming_the_active_model_updates_settings_too(client: TestClient) -> None:
    client.put("/settings", json={"user_name": "YourName", "backend": "codex"})
    client.put(
        "/settings/prices/codex/gpt-6.1-sol",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )

    renamed = client.put(
        "/settings/prices/codex/gpt-6.1-sol/rename", json={"new_model": "gpt-6.1-sol-v2"}
    )

    assert renamed.status_code == 200
    assert client.get("/settings").json()["codex_model"] == "gpt-6.1-sol-v2"


def test_renaming_a_non_active_model_leaves_settings_alone(client: TestClient) -> None:
    client.put(
        "/settings/prices/claude_code/claude-sonnet-5-old",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )

    renamed = client.put(
        "/settings/prices/claude_code/claude-sonnet-5-old/rename",
        json={"new_model": "claude-sonnet-5-new"},
    )

    assert renamed.status_code == 200
    assert client.get("/settings").json()["claude_code_model"] == "claude-sonnet-5"


def test_renaming_to_a_name_that_already_has_a_price_is_rejected(client: TestClient) -> None:
    client.put(
        "/settings/prices/codex/gpt-6.1-sol",
        json={"input_price_per_token": 0.000003, "output_price_per_token": 0.000015},
    )
    client.put(
        "/settings/prices/codex/gpt-5",
        json={"input_price_per_token": 0.00000125, "output_price_per_token": 0.00001},
    )

    renamed = client.put("/settings/prices/codex/gpt-6.1-sol/rename", json={"new_model": "gpt-5"})

    assert renamed.status_code == 422


def test_renaming_a_missing_price_is_rejected(client: TestClient) -> None:
    renamed = client.put(
        "/settings/prices/codex/no-such-model/rename", json={"new_model": "gpt-6.1-sol"}
    )
    assert renamed.status_code == 422


def test_bulk_saving_prices_confirms_several_rows_at_once(client: TestClient) -> None:
    saved = client.put(
        "/settings/prices",
        json=[
            {
                "provider": "codex",
                "model": "gpt-6.1-sol",
                "input_price_per_token": 0.000003,
                "output_price_per_token": 0.000015,
            },
            {
                "provider": "codex",
                "model": "gpt-5",
                "input_price_per_token": 0.00000125,
                "output_price_per_token": 0.00001,
            },
        ],
    )
    assert saved.status_code == 200
    assert {row["model"] for row in saved.json()} == {"gpt-6.1-sol", "gpt-5"}


# --- Pricing URLs ------------------------------------------------------------------------------


def test_pricing_urls_default_to_none(client: TestClient) -> None:
    assert client.get("/settings/pricing-urls").json() == {"claude_code": None, "codex": None}


def test_saving_a_pricing_url(client: TestClient) -> None:
    saved = client.put(
        "/settings/pricing-urls/codex", json={"pricing_url": "https://openai.com/api/pricing"}
    )
    assert saved.status_code == 200
    assert saved.json() == {"codex": "https://openai.com/api/pricing"}
    assert client.get("/settings/pricing-urls").json() == {
        "claude_code": None,
        "codex": "https://openai.com/api/pricing",
    }


def test_saving_a_pricing_url_for_an_unknown_provider_is_rejected(client: TestClient) -> None:
    saved = client.put("/settings/pricing-urls/chatgpt", json={"pricing_url": "https://x.com"})
    assert saved.status_code == 422


# --- Fetch and propose (D-198) --------------------------------------------------------------

_PRICING_PAGE_HTML = """<!doctype html>
<html><head><title>API Pricing</title></head>
<body><main>
<h1>API Pricing</h1>
<p>Prices are per 1,000,000 tokens, billed monthly, in US dollars.</p>
<h2>gpt-6.1-sol</h2>
<p>Input: $3.00 per 1,000,000 tokens. Output: $15.00 per 1,000,000 tokens.</p>
</main></body></html>"""


def test_fetch_without_a_pricing_url_is_rejected(client: TestClient) -> None:
    response = client.post("/settings/prices/codex/fetch")
    assert response.status_code == 400


@respx.mock
def test_fetch_queues_a_job_and_its_result_can_be_read_and_confirmed(db_path: Path) -> None:
    # A FakeRunner answering with a real price line, not "OK" - the client fixture's default
    # FakeRunner wouldn't produce anything parse_fetch_prices_answer can read.
    runner = FakeRunner(
        text="MODEL: gpt-6.1-sol | INPUT_PER_MILLION: 3.00 | OUTPUT_PER_MILLION: 15.00"
    )
    app = create_app(TOKEN, db_path, runner)
    with TestClient(app) as client:
        client.headers[TOKEN_HEADER] = TOKEN
        client.put(
            "/settings/pricing-urls/codex", json={"pricing_url": "https://example.com/pricing"}
        )
        respx.get("https://example.com/pricing").mock(
            return_value=httpx.Response(
                200, text=_PRICING_PAGE_HTML, headers={"content-type": "text/html"}
            )
        )

        submitted = client.post("/settings/prices/codex/fetch")
        assert submitted.status_code == 201
        job_id = submitted.json()["id"]

        queue: ClaudeJobQueue = app.state.queue
        queue.process_next()

        result = client.get(f"/settings/prices/codex/fetch/{job_id}")
        assert result.status_code == 200
        rows = result.json()
        assert rows == [
            {
                "model": "gpt-6.1-sol",
                "input_price_per_token": pytest.approx(0.000003),
                "output_price_per_token": pytest.approx(0.000015),
            }
        ]

        confirmed = client.put("/settings/prices", json=[{"provider": "codex", **rows[0]}])
        assert confirmed.status_code == 200
        assert confirmed.json()[0]["model"] == "gpt-6.1-sol"


# --- Auth status / logout (D-203) ------------------------------------------------------------


def test_auth_status_reports_both_backends(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        app_module,
        "claude_code_auth_status",
        lambda: AuthStatus(logged_in=True, detail="Logged in as someone@example.com"),
    )
    monkeypatch.setattr(
        app_module, "codex_auth_status", lambda: AuthStatus(logged_in=False, detail="Not logged in")
    )

    response = client.get("/settings/auth-status")

    assert response.status_code == 200
    assert response.json() == {
        "claude_code": {"logged_in": True, "detail": "Logged in as someone@example.com"},
        "codex": {"logged_in": False, "detail": "Not logged in"},
    }


def test_logout_calls_the_right_backends_logout_and_returns_fresh_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(app_module, "claude_code_logout", lambda: called.append("claude_code"))
    monkeypatch.setattr(
        app_module,
        "claude_code_auth_status",
        lambda: AuthStatus(logged_in=False, detail="Not logged in"),
    )

    response = client.post("/settings/claude_code/logout")

    assert response.status_code == 200
    assert response.json() == {"logged_in": False, "detail": "Not logged in"}
    assert called == ["claude_code"]


def test_logout_rejects_an_unknown_backend(client: TestClient) -> None:
    response = client.post("/settings/chatgpt/logout")
    assert response.status_code == 404


def test_login_launches_the_right_backends_login(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(app_module, "codex_login", lambda: called.append("codex"))

    response = client.post("/settings/codex/login")

    assert response.status_code == 204
    assert called == ["codex"]


def test_login_rejects_an_unknown_backend(client: TestClient) -> None:
    response = client.post("/settings/chatgpt/login")
    assert response.status_code == 404
