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

## Answer

One Markdown document, in the same voice and structure as the document it replaces — same rule as
`profile-steps.md`'s "Answer." No surrounding JSON, no code fence, no commentary about what
changed outside the document itself (the chat reply shown to the user is built from the job's own
metadata — started, streamed, done — not a separate "here's what I did" message the model writes;
see Trace below).

Code checks: the answer is not empty. Same size cap as `profile-steps.md` (150,000 characters
built) applies to the whole prompt, context files included.

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
