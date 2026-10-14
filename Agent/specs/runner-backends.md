# Runner backends: the contract a second implementation must meet

Phase 7 (D-195 to D-204). `Runner` (`api/src/llmjobtracker/runner.py`) is the only seam the rest of
the app talks to (D-19/D-20, CLAUDE.md rule 6) — this spec restates what `RunResult`,
`RateLimitError` and the token fields must mean for *any* runner, not just `ClaudeCodeRunner`'s,
so a second implementation (`CodexRunner`) and later ones stay interchangeable from the queue's
point of view. Live findings behind the choices below are in `planning/runner-notes.md`'s "Phase 7
additions" section — this file states the contract, that one records the evidence.

## `RunResult`

- `ok` / `text` / `error` / `duration_ms`: unchanged, every runner already fills these the same way.
- `model`: the model id the runner actually used. When a backend's own output doesn't say which
  model served the request (confirmed true of Codex, `codex exec --json` never reports one — see
  runner-notes.md), the runner records the model it explicitly requested, not a guess parsed from
  nothing.
- `cost_usd`: a dollar figure **only when the backend hands one back directly** (true of Claude
  Code's CLI, `total_cost_usd`). A runner that cannot report cost itself (Codex; any future direct
  provider API) leaves this `None` — cost is then computed by the queue from `input_tokens` /
  `output_tokens` and the stored price table (`pricing.md`), never guessed by the runner itself.
- `input_tokens` / `output_tokens` (new, migration 23): token counts, when the backend reports them.
  This is the one figure every backend is expected to supply (D-197) — unlike cost, a runner should
  not leave these `None` unless the backend genuinely gives nothing usable. `input_tokens` is a
  **total**, cache included: confirmed live, Claude Code's own `usage.input_tokens` excludes cache
  tokens (reported separately as `cache_creation_input_tokens`/`cache_read_input_tokens`), while
  Codex's `usage.input_tokens` is already a total — `ClaudeCodeRunner` sums all three of its own
  fields so the column means the same thing for both backends, rather than making Claude look
  implausibly cheap next to Codex for a similarly-sized prompt (runner-notes.md has the live
  numbers that surfaced this).

## `RateLimitError`

- `resets_at`: an absolute UTC time, as today. A backend that reports a *relative* delay instead of
  an absolute reset time (Codex's rate-limit signal is reported this way in third-party research,
  not yet confirmed live — runner-notes.md) computes `resets_at = now + delay` itself before raising
  the error; the queue (`claude_job_queue.py`) never needs to know which shape the backend reported
  natively.
- A runner that cannot determine a reset time at all raises `RateLimitError` with `resets_at=None` —
  already-supported today (`_paused_message` falls back to a generic pause message).

## What a runner must never do

- Must never retry on its own. Retrying (per D-201's new policy modes) is the queue's job, layered
  above whatever the runner reports — a runner that silently retries internally would hide a paused
  state the queue is supposed to see and act on.
- Must never read `app_settings`/the `settings` table itself. Which backend is active, and which
  retry policy is selected, are decisions the queue and the API layer make before calling a runner;
  a runner is handed a prompt and returns a result, nothing more (same boundary `ClaudeCodeRunner`
  already respects).
- Must never depend on another runner's binary, flags or event shape. `CodexRunner` knows nothing
  about `claude`, the same way `ClaudeCodeRunner` knows nothing about `codex` (D-20, extended).

## CodexRunner-specific notes (see runner-notes.md for the live evidence)

- Always passes `--skip-git-repo-check` (Codex refuses to run at all otherwise, confirmed live) and
  `--sandbox read-only` (no filesystem/network side effects — this app's jobs want an answer, not an
  agent that edits files, matching `ClaudeCodeRunner`'s `--restricted`/no-tools stance).
  `--dangerously-bypass-approvals-and-sandbox` is never used.
- The prompt is written to stdin (`codex exec -`), not passed as an argument, for the same reason
  `ClaudeCodeRunner` avoids argv: Windows' command-line length limit, and a profile prompt that can
  hold every CV.
- The answer is the last `item.completed` event whose `item.type == "agent_message"` — a turn can
  emit more than one `item.completed` event for intermediate reasoning.
- A failed turn is `turn.failed` (or a top-level `type: "error"` with no following
  `turn.completed`), whose `.message` (or `.error.message`) is itself a JSON string to try to parse,
  not already-structured data.
- `--output-schema` (Codex's `--json-schema` equivalent) takes a **file path**, not inline JSON —
  `CodexRunner` writes the schema to a temp file in its workdir before the run and cleans it up
  after, unlike `ClaudeCodeRunner`'s inline flag.
