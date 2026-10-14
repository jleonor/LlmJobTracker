from pathlib import Path

import httpx
import pytest
import respx

from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.pricing import set_pricing_url, upsert_model_price
from llmjobtracker.pricing_pipeline import (
    build_fetch_prices_prompt,
    parse_fetch_prices_answer,
    submit_fetch_model_prices,
)
from llmjobtracker.runner import FakeRunner
from llmjobtracker.storage import connect

_PRICING_PAGE_HTML = """<!doctype html>
<html><head><title>API Pricing</title></head>
<body>
<nav><a href="/">Home</a> <a href="/docs">Docs</a></nav>
<div class="cookie-banner">We use cookies. <button>Accept</button></div>
<main>
<h1>API Pricing</h1>
<p>Prices are per 1,000,000 tokens, billed monthly, in US dollars.</p>
<h2>gpt-5-codex</h2>
<p>Input: $3.00 per 1,000,000 tokens. Output: $15.00 per 1,000,000 tokens.</p>
<h2>Usage limits</h2>
<p>See your account dashboard for current usage against your plan's limits.</p>
</main>
<footer><p>&copy; 2026 Example Corp.</p></footer>
</body></html>"""


def test_build_prompt_lists_stored_prices_and_includes_the_page_text(db_path: Path) -> None:
    conn = connect(db_path)
    upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)

    prompt = build_fetch_prices_prompt(conn, "codex", "Pricing: gpt-5-codex costs $3 / $15")
    conn.close()

    assert "MODEL: gpt-5-codex | INPUT_PER_MILLION: 3" in prompt
    assert "OUTPUT_PER_MILLION: 15" in prompt
    assert "Pricing: gpt-5-codex costs $3 / $15" in prompt


def test_build_prompt_with_no_stored_prices_says_so(db_path: Path) -> None:
    conn = connect(db_path)
    prompt = build_fetch_prices_prompt(conn, "codex", "page text")
    conn.close()
    assert "(none stored yet)" in prompt


def test_parse_reads_a_priced_line(db_path: Path) -> None:
    conn = connect(db_path)
    answer = "MODEL: gpt-5-codex | INPUT_PER_MILLION: 3.00 | OUTPUT_PER_MILLION: 15.00"

    rows = parse_fetch_prices_answer(conn, "codex", answer)
    conn.close()

    assert len(rows) == 1
    assert rows[0].model == "gpt-5-codex"
    assert rows[0].input_price_per_token == pytest.approx(0.000003)
    assert rows[0].output_price_per_token == pytest.approx(0.000015)


def test_parse_reads_multiple_lines_ignoring_stray_prose(db_path: Path) -> None:
    conn = connect(db_path)
    answer = """Here is what I found on the page:

MODEL: gpt-5 | INPUT_PER_MILLION: 1.25 | OUTPUT_PER_MILLION: 10.00
MODEL: gpt-5-codex | INPUT_PER_MILLION: 3.00 | OUTPUT_PER_MILLION: 15.00

That's everything on the page."""

    rows = parse_fetch_prices_answer(conn, "codex", answer)
    conn.close()

    assert [row.model for row in rows] == ["gpt-5", "gpt-5-codex"]


def test_parse_resolves_unchanged_against_the_stored_price(db_path: Path) -> None:
    conn = connect(db_path)
    upsert_model_price(conn, "codex", "gpt-5-codex", 0.000003, 0.000015)
    answer = "MODEL: gpt-5-codex | UNCHANGED"

    rows = parse_fetch_prices_answer(conn, "codex", answer)
    conn.close()

    assert rows[0].input_price_per_token == pytest.approx(0.000003)
    assert rows[0].output_price_per_token == pytest.approx(0.000015)


def test_parse_rejects_unchanged_for_an_unknown_model(db_path: Path) -> None:
    conn = connect(db_path)
    with pytest.raises(PromptRejected):
        parse_fetch_prices_answer(conn, "codex", "MODEL: never-stored | UNCHANGED")
    conn.close()


def test_parse_rejects_an_answer_with_no_recognizable_line(db_path: Path) -> None:
    conn = connect(db_path)
    with pytest.raises(PromptRejected):
        parse_fetch_prices_answer(conn, "codex", "Sorry, I could not read this page.")
    conn.close()


def test_submit_fails_without_a_stored_pricing_url(db_path: Path) -> None:
    conn = connect(db_path)
    queue = ClaudeJobQueue(db_path, FakeRunner())
    with pytest.raises(ValueError, match="No pricing page URL"):
        submit_fetch_model_prices(conn, queue, "codex")
    conn.close()


@respx.mock
def test_submit_queues_a_job_with_the_fetched_page_text(db_path: Path) -> None:
    conn = connect(db_path)
    set_pricing_url(conn, "codex", "https://example.com/pricing")
    queue = ClaudeJobQueue(db_path, FakeRunner())
    respx.get("https://example.com/pricing").mock(
        return_value=httpx.Response(
            200, text=_PRICING_PAGE_HTML, headers={"content-type": "text/html"}
        )
    )

    job_id = submit_fetch_model_prices(conn, queue, "codex")
    conn.close()

    assert job_id > 0


@respx.mock
def test_submit_fails_when_the_page_cannot_be_read(db_path: Path) -> None:
    conn = connect(db_path)
    set_pricing_url(conn, "codex", "https://example.com/pricing")
    queue = ClaudeJobQueue(db_path, FakeRunner())
    respx.get("https://example.com/pricing").mock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(ValueError, match="Could not reach"):
        submit_fetch_model_prices(conn, queue, "codex")
    conn.close()
