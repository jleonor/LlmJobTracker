# Pricing: the price table and its scrape prompt

Phase 7 (D-197, D-198). Cost is only free when a backend hands it back directly (Claude Code's
CLI does; Codex and any future direct provider API don't — `runner-backends.md`). For every other
case, cost is computed in-app: `cost_usd = input_tokens * input_price_per_token + output_tokens *
output_price_per_token`, looked up from `model_prices` (migration 23) by `(provider, model)`. A
missing row means cost simply isn't shown for that run — never a guessed number.

## `model_prices` table

`provider` (`claude_code` or `codex`), `model`, `input_price_per_token`, `output_price_per_token`
(both default `0`, meaning "no price set yet, don't compute a cost"), an optional `pricing_url`,
and `updated_at`. One row per `(provider, model)` (`UNIQUE` constraint).

## Editing by hand

Settings' price table editor (step 9) reads and writes this table directly — add a `(provider,
model)` row, set its two per-token prices. No model step involved; this is config, not generation.

## The "fetch and update" scrape

Settings can also hold a `pricing_url` per provider and trigger a refresh that proposes a parsed
price table. **Corrected from this spec's first draft**, which said the Claude Job would get "a
fetch tool" — that would have been the only tool-bearing step in the whole app, when the existing,
already-built pattern for every other URL in this app (`listing_intake.py`'s `extract_from_url`) is
exactly the one CLAUDE.md already states: fetch and reduce to text in plain code, never give Claude
a tool at all, and only then run a tool-less model step over the already-extracted text. The pricing
scrape follows that same pattern, reusing `extract_from_url` directly rather than inventing a second
fetcher: code fetches `pricing_url` server-side (timeout, size cap, HTML reduced to readable text,
same as a job listing's URL intake), and the Claude Job that parses it is exactly as toolless as
every other Claude Job in this app (D-32 extended, not an exception to it).

- **Input:** the page text already fetched and extracted by code (never the raw HTML, never a live
  URL the model could itself re-fetch), plus the provider's current `model_prices` rows (so the
  model can say "unchanged" for a model whose price didn't move, rather than re-stating every row).
- **Output:** one row per model found on the page — `model`, `input_price_per_token`,
  `output_price_per_token` (converted from whatever unit the page quotes — most pricing pages quote
  per-million-token prices, so the model converts to per-token before answering, and the parser
  re-checks the arithmetic rather than trusting the model's division).
- **Review, not apply (D-198):** the parsed table is returned to the user for review and only
  written to `model_prices` when they confirm — the same review-before-save pattern this app already
  uses for every other piece of generated content (CLAUDE.md, D-85). A rejected or edited-then-
  confirmed table is what gets saved, never the model's raw answer directly.
- **Failure:** a page that doesn't parse (no recognizable price table, a paywall, a fetch error)
  fails the job with a message saying so — the existing `model_prices` rows are untouched either
  way until the user explicitly confirms a replacement.
