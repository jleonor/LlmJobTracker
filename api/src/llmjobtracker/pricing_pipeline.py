"""Fetch-and-propose a provider's price table from its stored pricing page (D-198,
Agent/specs/pricing.md).

Code fetches the page (`listing_intake.extract_from_url`, the same server-side fetch every other
URL in this app already uses - never a Claude tool, correcting this spec's first draft). A
tool-less Claude Job then parses the already-extracted text into one row per model. Nothing here
writes to `model_prices`: like Add Job's identity step (`JOB_KIND_IDENTITY`), this job kind has
nothing to store in `on_result` - its answer is read back and parsed on demand, and only
`pricing.upsert_model_price` (called once the user reviews and confirms) ever changes the stored
table.
"""

import re
import sqlite3
from typing import Final

from pydantic import BaseModel

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.listing_intake import ListingFetchError, extract_from_url
from llmjobtracker.pricing import list_model_prices

FETCH_PRICES_KIND: Final = "fetch_model_prices"

_FETCH_PRICES_PROMPT = """You are given the text of a pricing page for an AI model provider.
List the per-token prices for every model you can find on the page, one line per model, each in
exactly this format:

MODEL: <model id, as written on the page> | INPUT_PER_MILLION: <usd> | OUTPUT_PER_MILLION: <usd>

Prices are per 1,000,000 tokens, in US dollars, written as a plain number with no currency symbol
and no thousands separator (for example 3.00, not $3.00 or 3,00).

If a model's price on the page is identical to a price already stored below, you may write this
instead of repeating the numbers:

MODEL: <model id> | UNCHANGED

Do not invent a model that is not actually on the page. Do not guess a price you cannot read.

=== PRICES ALREADY STORED ===
{current_prices}
=== END PRICES ALREADY STORED ===

=== PAGE TEXT ===
{page_text}
=== END PAGE TEXT ==="""

_UNCHANGED_RE = re.compile(r"^MODEL:\s*(.+?)\s*\|\s*UNCHANGED\s*$", re.IGNORECASE)
_PRICED_RE = re.compile(
    r"^MODEL:\s*(.+?)\s*\|\s*INPUT_PER_MILLION:\s*([\d.]+)\s*\|\s*OUTPUT_PER_MILLION:\s*([\d.]+)\s*$",
    re.IGNORECASE,
)


class ParsedModelPrice(BaseModel):
    model: str
    input_price_per_token: float
    output_price_per_token: float


def _current_prices_block(conn: sqlite3.Connection, provider: str) -> str:
    rows = list_model_prices(conn, provider)
    if not rows:
        return "(none stored yet)"
    lines = []
    for row in rows:
        lines.append(
            f"MODEL: {row.model} | INPUT_PER_MILLION: {row.input_price_per_token * 1_000_000:g} "
            f"| OUTPUT_PER_MILLION: {row.output_price_per_token * 1_000_000:g}"
        )
    return "\n".join(lines)


def build_fetch_prices_prompt(conn: sqlite3.Connection, provider: str, page_text: str) -> str:
    return _FETCH_PRICES_PROMPT.format(
        current_prices=_current_prices_block(conn, provider), page_text=page_text
    )


def parse_fetch_prices_answer(
    conn: sqlite3.Connection, provider: str, text: str
) -> list[ParsedModelPrice]:
    """Reads the model's line-per-model answer. Raises PromptRejected if not one well-formed
    line was found - a page that doesn't parse fails the job with a message, per pricing.md,
    rather than silently proposing an empty table."""
    current = {row.model: row for row in list_model_prices(conn, provider)}
    parsed: list[ParsedModelPrice] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        unchanged = _UNCHANGED_RE.match(stripped)
        if unchanged:
            model = unchanged.group(1)
            existing = current.get(model)
            if existing is None:
                raise PromptRejected(
                    f"The answer says {model!r} is unchanged, but no price is stored for it yet."
                )
            parsed.append(
                ParsedModelPrice(
                    model=model,
                    input_price_per_token=existing.input_price_per_token,
                    output_price_per_token=existing.output_price_per_token,
                )
            )
            continue
        priced = _PRICED_RE.match(stripped)
        if priced:
            model, input_per_million, output_per_million = priced.groups()
            parsed.append(
                ParsedModelPrice(
                    model=model,
                    input_price_per_token=float(input_per_million) / 1_000_000,
                    output_price_per_token=float(output_per_million) / 1_000_000,
                )
            )
    if not parsed:
        raise PromptRejected("Could not find any model prices in the answer.")
    return parsed


def submit_fetch_model_prices(
    conn: sqlite3.Connection, queue: ClaudeJobQueue, provider: str
) -> int:
    """Queue the price-fetch job for one provider. Raises ValueError if there's no pricing URL
    stored yet, or the page couldn't be read - the same fallback-not-raise-to-the-model shape
    `listing_intake` already uses, surfaced here as a plain error before any Claude Job exists."""
    row = conn.execute(
        "SELECT pricing_url FROM provider_pricing WHERE provider = ?", (provider,)
    ).fetchone()
    url = row["pricing_url"] if row is not None else None
    if not url:
        raise ValueError("No pricing page URL is set for this provider yet.")
    try:
        extraction = extract_from_url(url)
    except ListingFetchError as error:
        raise ValueError(error.message) from error
    if extraction.status != "ok" or not extraction.text:
        raise ValueError(extraction.message or "Could not read the pricing page.")
    prompt = build_fetch_prices_prompt(conn, provider, extraction.text)
    return queue.submit(
        conn, f"Fetch prices: {provider}", FETCH_PRICES_KIND, [(FETCH_PRICES_KIND, prompt)]
    )
