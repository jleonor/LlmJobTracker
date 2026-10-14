"""Price lookup for a completed run (D-197, D-198, Agent/specs/pricing.md).

cost_usd = input_tokens * input_price_per_token + output_tokens * output_price_per_token,
looked up from model_prices by (provider, model) - the provider is whichever backend is
currently selected in Settings (D-195: one global backend for the whole app, so a run's
provider is never ambiguous). A missing price row means cost simply isn't shown, never a
guessed number.
"""

import sqlite3

from pydantic import BaseModel

from llmjobtracker.migrations import RUNNER_BACKENDS
from llmjobtracker.runner import RunResult
from llmjobtracker.settings import get_settings


class ModelPrice(BaseModel):
    provider: str
    model: str
    input_price_per_token: float
    output_price_per_token: float
    updated_at: str


def _require_known_provider(provider: str) -> None:
    if provider not in RUNNER_BACKENDS:
        raise ValueError(f"Unknown provider: {provider!r}")


def list_model_prices(conn: sqlite3.Connection, provider: str | None = None) -> list[ModelPrice]:
    """Every stored price row, or just one provider's (Agent/specs/pricing.md's "editing by
    hand" and the pricing-scrape prompt's own "already stored" block both use this)."""
    if provider is None:
        rows = conn.execute("SELECT * FROM model_prices ORDER BY provider, model").fetchall()
    else:
        _require_known_provider(provider)
        rows = conn.execute(
            "SELECT * FROM model_prices WHERE provider = ? ORDER BY model", (provider,)
        ).fetchall()
    return [ModelPrice(**dict(row)) for row in rows]


def upsert_model_price(
    conn: sqlite3.Connection,
    provider: str,
    model: str,
    input_price_per_token: float,
    output_price_per_token: float,
) -> ModelPrice:
    """Add a (provider, model) row, or replace its prices if one already exists - the same
    operation whether it came from hand-editing or from confirming a scraped table (D-198)."""
    _require_known_provider(provider)
    if not model.strip():
        raise ValueError("A model id is required.")
    if input_price_per_token < 0 or output_price_per_token < 0:
        raise ValueError("A price cannot be negative.")
    with conn:
        conn.execute(
            """
            INSERT INTO model_prices (provider, model, input_price_per_token,
                output_price_per_token, updated_at)
            VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            ON CONFLICT (provider, model) DO UPDATE SET
                input_price_per_token = excluded.input_price_per_token,
                output_price_per_token = excluded.output_price_per_token,
                updated_at = excluded.updated_at
            """,
            (provider, model, input_price_per_token, output_price_per_token),
        )
    row = conn.execute(
        "SELECT * FROM model_prices WHERE provider = ? AND model = ?", (provider, model)
    ).fetchone()
    return ModelPrice(**dict(row))


def delete_model_price(conn: sqlite3.Connection, provider: str, model: str) -> bool:
    with conn:
        cursor = conn.execute(
            "DELETE FROM model_prices WHERE provider = ? AND model = ?", (provider, model)
        )
    return cursor.rowcount == 1


def get_pricing_url(conn: sqlite3.Connection, provider: str) -> str | None:
    _require_known_provider(provider)
    row = conn.execute(
        "SELECT pricing_url FROM provider_pricing WHERE provider = ?", (provider,)
    ).fetchone()
    return row["pricing_url"] if row is not None else None


def set_pricing_url(conn: sqlite3.Connection, provider: str, pricing_url: str | None) -> None:
    _require_known_provider(provider)
    cleaned = (pricing_url or "").strip() or None
    with conn:
        conn.execute(
            "UPDATE provider_pricing SET pricing_url = ? WHERE provider = ?",
            (cleaned, provider),
        )


def compute_cost_usd(conn: sqlite3.Connection, result: RunResult) -> float | None:
    """The run's cost: the runner's own figure if it gave one, else computed from its tokens
    and the stored price table. None if neither is available."""
    if result.cost_usd is not None:
        return result.cost_usd
    if result.model is None or result.input_tokens is None or result.output_tokens is None:
        return None
    provider = get_settings(conn).backend
    row = conn.execute(
        "SELECT input_price_per_token, output_price_per_token FROM model_prices "
        "WHERE provider = ? AND model = ?",
        (provider, result.model),
    ).fetchone()
    if row is None:
        return None
    return float(
        result.input_tokens * row["input_price_per_token"]
        + result.output_tokens * row["output_price_per_token"]
    )
