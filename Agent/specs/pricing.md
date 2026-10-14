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

Settings can also hold a `pricing_url` per provider and trigger a Claude Job that reads that one
page and proposes a parsed price table. This is the one new, deliberately narrow exception to this
app's usual "a step that reads untrusted text gets no tools" rule (CLAUDE.md): the job gets exactly
one fetch tool, scoped to the single URL the user themselves put in Settings — not the open web, and
not a URL that arrived from anywhere else (a job listing, an email, generated text).

- **Input:** the `pricing_url` stored for the provider being refreshed, plus the provider's current
  `model_prices` rows (so the model can say "unchanged" for a model whose price didn't move, rather
  than re-stating every row).
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
