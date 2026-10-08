# Revise steps: the contract for a Revise (LLM) chat turn

Extends Phase 3 (D-106). A revise conversation is scoped to one generated document — today, one of
the three `own_*` kinds in `profile-steps.md` (the career history, the questionnaire analysis, the
strategy). Each turn the user sends is one new Claude Job, with one prompt, run through the
`Runner` with no JSON schema and no tools (`--tools ""`, same as the prompts that generate these
documents). The answer replaces the document as a new version, the same way a generated run does
(D-84): nothing is overwritten, and the prior version stays reachable through its own file history.

## Job kind and prompt shape

- **Kind:** `revise_<own file kind>` — `revise_own_full_cv_history`, `revise_own_questionnaire_analysis`,
  `revise_own_strategy`. Each links to no `job_application_id`, the same as `profile_analysis`.
- **One prompt per turn.** The runner has no session persistence, so nothing is carried between
  turns except what the prompt text itself contains.
- **Built when the job runs**, not when queued — same rule as `profile-steps.md`, so it always
  reflects the latest document version, even if an earlier turn in the same conversation failed.

## What goes into the prompt

In this order:

1. **Writing rules** in force (the user's own, or `Agent/rules/honesty.md`) — same as every
   profile prompt.
2. **Context files**, fixed per kind, the same inputs that kind's generating prompt uses:
   - `revise_own_full_cv_history`: every master CV, older CV, older cover letter (extracted text).
   - `revise_own_questionnaire_analysis`: the questionnaire, and the current career history.
   - `revise_own_strategy`: the current questionnaire analysis, and the current career history.
   These are the files the chat UI lists as "in context" for that conversation (the brainstorm's
   #4). They are read fresh each turn, the same as a generating run — a revise answers from the
   current state of its sources, not a snapshot taken when the conversation started.
3. **The current document** (the latest version in `profile_outputs` for that kind), in full.
4. **The conversation transcript so far**: each prior user message, in order. The model's own
   prior replies are not replayed as separate turns — each prior reply's effect is already visible
   in "the current document" above, so repeating it would duplicate content the model would then
   have to reconcile with itself. Only the user's asks are replayed, so the model sees what was
   requested and can confirm each was addressed.
5. **The user's new message** for this turn.

## Answer (D-110)

The answer chooses one of two modes, declared on its first line:

- **`MODE: edit`** — for most requests. A list of one or more exact text replacements, each one
  block:

  ```
  === EDIT ===
  OLD:
  <text copied character for character from the current document, unique within it>
  NEW:
  <replacement text>
  === END EDIT ===
  ```

  Code applies each edit in order: `OLD` must appear in the current document exactly once, the
  same invariant Claude Code's own edit tool enforces. If it does not — not found, or found more
  than once — the prompt fails with that reason, and the document is left unchanged; there is no
  automatic retry and no silent fallback to a rewrite. The user sends another turn to try again.

- **`MODE: rewrite`** — only when the request cannot be expressed as a small number of edits, for
  example reorganising the whole document. The full document follows, as Markdown, the same shape
  `profile-steps.md`'s "Answer" describes: no surrounding JSON, no code fence, no commentary.

A full rewrite was the only option before D-110, and it reworded parts of the document the user
never asked to change, even when told to keep its structure. An edit, verbatim-matched by code
before it is applied, cannot touch anything it was not given — closer to how a person edits a
document, and closer to what the brainstorm asked for ("how Claude Code does it") without giving
Claude a file-editing tool (D-85/86's no-tools design stays as it is; the `=== EDIT ===` block
reuses the same delimiter convention the prompt's own file and document blocks already use,
rather than the runner's `--json-schema` path, which stays unverified live — runner-notes.md).

No separate "here's what I did" message outside the edits or the document: the chat reply shown
to the user is built from the job's own metadata — started, streamed, done — same as before (see
Trace below).

Code checks: the mode line is present and recognised, and the edit or document body is not
empty. Same size cap as `profile-steps.md` (150,000 characters built) applies to the whole
prompt, context files included.

## Trace (D-105)

The runner passes `--include-partial-messages`, so the chat can show the answer streaming in as it
is generated. There is no tool-call trace to show, since the prompt gets no tools: a turn's visible
states are queued, started, streaming text, then done (with cost and duration) or failed — the same
states `RunTrace` shows for a generating run, not an action/reasoning trace.

## Honesty

Same rule as every profile document (D-85): the answer uses only what the context files and the
current document say, and does not invent or embellish a claim. The user reviews the updated
document before anything later run treats it as current, the same as any other revision.

## Out of scope here

- The Job Application page's Revise (LLM) buttons (positioning, job details, application history,
  files) stay disabled. None of their target documents exist yet (positioning is Phase 5), so there
  is nothing for a revise prompt to revise. The components built for this spec should work for them
  once they do, per the brainstorm, but wiring them is not part of this step.
- Conversation storage (the table holding each turn and its Claude Job) is a migration decision,
  not a prompt contract — see Phase 3's step list, step 4.
