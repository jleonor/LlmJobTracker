import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from llmjobtracker.migrations import migrate
from llmjobtracker.pricing import compute_cost_usd
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
