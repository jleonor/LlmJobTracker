"""Price lookup for a completed run (D-197, D-198, Agent/specs/pricing.md).

cost_usd = input_tokens * input_price_per_token + output_tokens * output_price_per_token,
looked up from model_prices by (provider, model) - the provider is whichever backend is
currently selected in Settings (D-195: one global backend for the whole app, so a run's
provider is never ambiguous). A missing price row means cost simply isn't shown, never a
guessed number.
"""

import sqlite3

from llmjobtracker.runner import RunResult
from llmjobtracker.settings import get_settings


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
