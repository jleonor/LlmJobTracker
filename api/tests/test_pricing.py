import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from llmjobtracker.migrations import migrate
from llmjobtracker.pricing import (
    compute_cost_usd,
    delete_model_price,
    get_pricing_url,
    list_model_prices,
    set_pricing_url,
    upsert_model_price,
)
from llmjobtracker.runner import RunResult
from llmjobtracker.storage import connect, database_path


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path(tmp_path))
    migrate(connection)
    yield connection
    connection.close()


def test_the_runners_own_cost_is_kept_as_is(conn: sqlite3.Connection) -> None:
    result = RunResult(ok=True, cost_usd=0.0106, model="claude-sonnet-5")
    assert compute_cost_usd(conn, result) == pytest.approx(0.0106)


def test_a_missing_price_row_leaves_cost_unset(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE settings SET backend = 'codex' WHERE id = 1")
    conn.commit()
    result = RunResult(ok=True, model="gpt-5-codex", input_tokens=1000, output_tokens=100)
    assert compute_cost_usd(conn, result) is None


def test_cost_is_computed_from_tokens_and_the_stored_price(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO model_prices (provider, model, input_price_per_token, "
        "output_price_per_token) VALUES ('codex', 'gpt-5-codex', 0.000003, 0.000015)"
    )
    conn.execute("UPDATE settings SET backend = 'codex' WHERE id = 1")
    conn.commit()
    result = RunResult(ok=True, model="gpt-5-codex", input_tokens=1000, output_tokens=100)

    cost = compute_cost_usd(conn, result)

    assert cost == pytest.approx(1000 * 0.000003 + 100 * 0.000015)


def test_the_price_lookup_uses_the_currently_selected_backend(conn: sqlite3.Connection) -> None:
    # Same model name under two providers, different prices - the active backend disambiguates.
    conn.execute(
        "INSERT INTO model_prices (provider, model, input_price_per_token, "
        "output_price_per_token) VALUES ('claude_code', 'shared-name', 1.0, 1.0)"
    )
    conn.execute(
        "INSERT INTO model_prices (provider, model, input_price_per_token, "
        "output_price_per_token) VALUES ('codex', 'shared-name', 2.0, 2.0)"
    )
    conn.execute("UPDATE settings SET backend = 'codex' WHERE id = 1")
    conn.commit()
    result = RunResult(ok=True, model="shared-name", input_tokens=10, output_tokens=10)

    assert compute_cost_usd(conn, result) == pytest.approx(10 * 2.0 + 10 * 2.0)


def test_missing_tokens_leave_cost_unset(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO model_prices (provider, model, input_price_per_token, "
        "output_price_per_token) VALUES ('codex', 'gpt-5-codex', 0.000003, 0.000015)"
    )
    conn.execute("UPDATE settings SET backend = 'codex' WHERE id = 1")
    conn.commit()
    result = RunResult(ok=True, model="gpt-5-codex", input_tokens=None, output_tokens=100)
    assert compute_cost_usd(conn, result) is None


def test_missing_model_leaves_cost_unset(conn: sqlite3.Connection) -> None:
    result = RunResult(ok=True, model=None, input_tokens=100, output_tokens=100)
    assert compute_cost_usd(conn, result) is None


def test_upsert_adds_a_row_and_list_returns_it(conn: sqlite3.Connection) -> None:
    added = upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)

    assert added.provider == "codex"
    assert added.model == "gpt-5-codex"
    assert list_model_prices(conn, "codex") == [added]
    assert list_model_prices(conn) == [added]


def test_upsert_again_replaces_the_prices_not_adds_a_row(conn: sqlite3.Connection) -> None:
    upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)

    replaced = upsert_model_price(conn, "codex", "gpt-5-codex", 0.000004, 0.00002)

    rows = list_model_prices(conn, "codex")
    assert len(rows) == 1
    assert rows[0].input_price_per_token == pytest.approx(0.000004)
    assert replaced.output_price_per_token == pytest.approx(0.00002)


def test_list_model_prices_filters_by_provider(conn: sqlite3.Connection) -> None:
    upsert_model_price(conn, "claude_code", "claude-sonnet-5", 0.000003, 0.000015)
    upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)

    assert [row.model for row in list_model_prices(conn, "claude_code")] == ["claude-sonnet-5"]
    assert [row.model for row in list_model_prices(conn, "codex")] == ["gpt-5-codex"]
    assert len(list_model_prices(conn)) == 2


def test_upsert_rejects_an_unknown_provider(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        upsert_model_price(conn, "chatgpt", "gpt-5", 0.000003, 0.000015)


def test_upsert_rejects_a_negative_price(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        upsert_model_price(conn, "codex", "gpt-5-codex", -1, 0.000015)


def test_delete_removes_a_row(conn: sqlite3.Connection) -> None:
    upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)

    assert delete_model_price(conn, "codex", "gpt-5-codex") is True
    assert list_model_prices(conn, "codex") == []
    assert delete_model_price(conn, "codex", "gpt-5-codex") is False


def test_pricing_url_defaults_to_none_and_can_be_set(conn: sqlite3.Connection) -> None:
    assert get_pricing_url(conn, "codex") is None

    set_pricing_url(conn, "codex", "https://openai.com/api/pricing")

    assert get_pricing_url(conn, "codex") == "https://openai.com/api/pricing"


def test_pricing_url_trims_whitespace_and_blank_becomes_none(conn: sqlite3.Connection) -> None:
    set_pricing_url(conn, "codex", "  https://openai.com/api/pricing  ")
    assert get_pricing_url(conn, "codex") == "https://openai.com/api/pricing"

    set_pricing_url(conn, "codex", "   ")
    assert get_pricing_url(conn, "codex") is None


def test_pricing_url_rejects_an_unknown_provider(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        get_pricing_url(conn, "chatgpt")
    with pytest.raises(ValueError):
        set_pricing_url(conn, "chatgpt", "https://example.com")
