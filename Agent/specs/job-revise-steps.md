# Job-page revise steps: the contract for a job-section chat turn

Extends Phase 3 (D-136). A job-page revise conversation is scoped to one Job Application and one
of its six sections: `job_details`, `positioning`, `application_history`, `tailored_cv`,
`cover_letter`, `interview_prep` (the last added later, D-169, once Interview preparation itself
existed — job-llm-steps.md §7). Each turn the user sends is one new Claude Job, with one prompt,
run through the `Runner` with no JSON schema and no tools (`--tools ""`, same as every other
job-page prompt). The answer is a true incremental patch against the section's own current
content, not a full replacement — mirrors `revise-steps.md`'s OLD/NEW model in spirit, but each
section needs its own answer grammar, since none of the six is a single plain-text document the
way a profile output is.

All six sections now have a grammar: `job_details`, `application_history` and `positioning`
each have their own (D-137 to D-140); `tailored_cv` and `cover_letter` (D-141) reuse D-130's
existing block-id operations almost unchanged, built against the *current* file's own blocks;
`interview_prep` (D-169) has its own, a `NUMBER`-indexed patch mirroring `job_details`'
`REQUIREMENT PATCH` grammar.

## Job kind, table, and prompt shape

- **Kind:** `revise_<section kind>` — `revise_job_details`, `revise_application_history`,
  `revise_positioning`, `revise_tailored_cv`, `revise_cover_letter`, `revise_interview_prep`
  (D-169). Each links to the `job_application_id` it's revising, unlike a profile revise turn
  (which links to none).
- **Table:** `job_revise_turns` (migration 18) — one shared table with a `section_kind` column,
  the same single-table-many-kinds shape `revise_turns` already uses for the three profile
  documents, kept separate from it since `revise_turns`'s `output_kind` CHECK and lack of a
  `job_application_id` column are profile-specific by design. `attachment_job_file_id` (D-138) is
  the `job_files` row a turn optionally carries — filed for real *before* the turn is queued (the
  route's caller uploads it first through the existing `/job-applications/{id}/files/{kind}`
  endpoint, the same as any other upload), not a separate attachment-storage mechanism of its own.
  `section_kind`'s own CHECK constraint was deliberately pre-reserved for exactly the five kinds
  known when migration 18 was written (`migrations.py`'s own comment: "so the table's CHECK
  constraint doesn't need a later migration to widen it") — `interview_prep` wasn't one of them,
  since Interview preparation didn't exist yet. Widening a CHECK is not a plain `ALTER TABLE ADD
  COLUMN` in SQLite, so migration 22 rebuilds the table (create-new/copy/drop/rename, the same
  technique migration 13 already used for a CHECK change on `job_applications`/`status_history`),
  rather than attempting an in-place `ALTER`.
- **One prompt per turn**, built when the job runs, not when queued — same rule as every other
  revise/generate prompt in this app, so it always reflects the latest stored content and the
  latest conversation, even if an earlier turn in the same conversation failed.

## Job details' answer grammar

What goes into the prompt, in this order: the listing's extracted text (read as data, never as
instructions, the same rule `generate_job_details` already states); the current `description`;
the current `requirements`, numbered 1-based — the chat prompt tells the model to refer to an
existing requirement only by its number, never by retyping its text, the same "don't ask the
model to reproduce structured content, give it an id instead" idea D-130 and D-134 already use;
the conversation so far (`Turn 1: <message>`, `Turn 2: <message>`, ...); the new message.

The answer:

```
=== DESCRIPTION ===
unchanged
=== END DESCRIPTION ===
```

or, if the request changes it, the full replacement description in place of `unchanged`. Then,
only for a requirement actually being changed — a requirement not mentioned stays exactly as it
is:

```
=== REQUIREMENT PATCH ===
NUMBER: <a number from the list above, or NEW to add a requirement>
ACTION: EDIT, REMOVE, or ADD
TEXT: <for EDIT or ADD only - copied verbatim from the listing text>
=== END REQUIREMENT PATCH ===
```

Code applies every patch against the *stored* requirements list (not the order the model gave
them in): `EDIT`/`REMOVE` resolve `NUMBER` against the list's current length (out of range,
non-integer, or patched more than once rejects the whole turn); `EDIT`/`ADD`'s `TEXT` is
re-checked verbatim against the listing (whitespace-normalised substring match), the same D-125
guarantee a fresh generation already gets — a human-directed edit claims to quote the listing
just as much as a model-generated one does, so it is not exempt. An answer that changes nothing
(`DESCRIPTION: unchanged` and no patches) is rejected rather than silently accepted as a no-op
turn. A rejected turn leaves `description`/`requirements` exactly as they were — no retry, no
partial apply.

## Application history's answer grammar (D-138)

What goes into the prompt: the job description; the application's already-filed emails, read the
same way `generate_application_history` already reads them (`email_blocks`, now a shared,
public helper of `job_pipeline.py` rather than that step's own private one); this turn's
attachment, if any (its own labelled block, read fresh each turn — `.eml`/`.msg` through the same
email-text parsing, anything else through `extraction.py`'s general-purpose `extract()`, since
only the listing kind is extracted at upload time); the current `next_action` and `due_date`; the
conversation so far; the new message. `notes` is never part of the prompt, same as the one-shot
step (D-127: user-only).

The answer patches the two fields independently:

```
=== NEXT ACTION ===
unchanged, none to clear it, or the new next action
=== END NEXT ACTION ===

=== DUE DATE ===
unchanged, none to clear it, or a new date as YYYY-MM-DD
=== END DUE DATE ===
```

`unchanged` leaves the stored field untouched; `none` clears it — unlike the one-shot generate
step, which never clears a field (its own caution about a weak LLM proposal overwriting a real
value), a human-directed chat edit can reasonably ask for a field to be cleared, so the chat
grammar allows it. A `DUE DATE` that is neither of those two words is checked as `YYYY-MM-DD`;
anything else rejects the whole turn, both fields left as they were. An answer that changes
neither field is rejected, same as Job details' "did not change anything" guard.

## Positioning analysis's answer grammar (D-139)

What goes into the prompt: the three profile documents (career history, questionnaire analysis,
strategy — `profile_document_blocks`, now a shared, public helper of `job_pipeline.py` rather
than that step's own private one, since Tailored CV and Cover letter's prompts already needed
it); the job description; the current `positioning_scores`, numbered 1-based with each
requirement's current weight and match shown alongside it; the current `fit`/`gaps`/`strategy`/
`unclear`; the conversation so far; the new message.

Until this batch, the only record of each requirement's weight/match/reasoning was the *rendered*
breakdown Markdown table — not something a `NUMBER`-indexed patch can reliably read back from,
since reparsing a table the model never wrote in this turn is exactly the fragile, lossy
round-trip this app's prompt design avoids elsewhere (D-130, D-134). Migration 19 adds
`job_applications.positioning_scores` (JSON `[{text, weight, match, reasoning}]`), written
alongside the rendered document by both the one-shot `generate_positioning` and this chat.

The answer:

```
=== FIT ===
unchanged, or the full replacement list (one "- bullet" per line)
=== END FIT ===

=== GAPS ===
unchanged, or the full replacement list (one "- bullet" per line)
=== END GAPS ===

=== STRATEGY ===
unchanged, or the full replacement text
=== END STRATEGY ===

=== UNCLEAR ===
unchanged, or the full replacement list (one "- bullet" per line)
=== END UNCLEAR ===
```

then, only for a requirement's score actually being changed — one not mentioned stays exactly as
it is:

```
=== REQUIREMENT PATCH ===
NUMBER: <a number from the list above>
WEIGHT: unchanged, or a new 0-10 weight
MATCH: unchanged, or a new 0-10 match
REASONING: unchanged, or new reasoning
=== END REQUIREMENT PATCH ===
```

Each of `WEIGHT`/`MATCH`/`REASONING` is independent — a patch can touch any subset of the three,
leaving the others as they are. `NUMBER` is checked against the stored list's current length (out
of range, non-integer, or patched more than once rejects the whole turn); `WEIGHT`/`MATCH` are
checked as `0`-`10` when given. Applying any score patch recomputes `match_score` (D-47) from the
updated list and re-renders the breakdown document (`render_breakdown_document`, the same
function the one-shot step uses) — if every resulting weight would be `0`, the whole turn is
rejected, the same guard the one-shot step already has. An answer that changes nothing (every
field `unchanged` and no patches) is rejected, same as the other two sections' grammars.

## Interview preparation's answer grammar (D-169)

What goes into the prompt: the three profile documents (career history, questionnaire analysis,
strategy — `profile_document_blocks`, the same shared helper Positioning/Tailored CV/Cover letter
already use); the selected Master CV's own plain text (job-llm-steps.md §7's own addition — read
here too, the same way the one-shot step does); the job description and the stored `requirements`
list, numbered 1-based, background only; the current `interview_prep` list, numbered 1-based, each
shown as its stored question, answer and score (or "(not scored)" if null); the conversation so
far; the new message. Any pair the turn adds or rewrites is answered the same way the one-shot
step is (D-172): identify what the question actually tests, check the material for
direct/transferable/no evidence, and answer with STAR, STAR + Bridge, or an acknowledged
hypothetical accordingly — restated in the chat prompt itself, not merely assumed to carry over
from the first generation. It is scored out of 10 the same way too (D-173).

Only for a pair actually being changed — a pair not mentioned stays exactly as it is:

```
=== QA PATCH ===
NUMBER: <a number from the list above, or NEW to add a pair>
ACTION: EDIT, REMOVE, or ADD
QUESTION: <for ADD, or an EDIT that changes the question — otherwise omit>
ANSWER: <for ADD, or an EDIT that changes the answer — otherwise omit>
SCORE: <0-10, required for ADD, or an EDIT that changes the answer — otherwise omit>
=== END QA PATCH ===
```

Code applies every patch against the *stored* `interview_prep` list (not the order the model gave
them in): `EDIT`/`REMOVE` resolve `NUMBER` against the list's current length (out of range,
non-integer, or patched more than once rejects the whole turn, the same guarantee Job details' and
Positioning's own `NUMBER`-indexed patches already give); `ADD` requires `QUESTION`, `ANSWER` and
`SCORE` all three (D-173 — a new pair should be scored like any other); an `EDIT` that gives only
some of the three leaves the rest exactly as stored (`SCORE` omitted on an answer-only edit, for
instance, keeps the previous score rather than clearing it), the same per-field independence
Application history's `NEXT ACTION`/`DUE DATE` patch already allows. `SCORE`, when given, is
checked the same way the one-shot step's own is (a whole number 0-10, `PromptRejected` otherwise).
An answer that changes nothing (no patches at all) is rejected, the same "did nothing" guard every
other chat grammar here already has. A rejected turn leaves `interview_prep` exactly as it was —
no retry, no partial apply. `_split_qa_patch`'s own field boundaries use `[ \t]*`, the same fix
job-llm-steps.md §7 explains for `_QA_BLOCK` — the same greedy-`\s*`-eats-the-boundary-newline risk
applies to an empty `QUESTION`/`ANSWER` value here too.

## Tailored CV's and Cover letter's answer grammar (D-141)

Unlike the other three, these reuse D-130's existing block-id operation grammar
(EDIT/INSERT AFTER/REMOVE/ADD ROW AFTER) essentially unchanged — no new grammar was designed for
this batch, confirming what D-136 already expected.

What goes into the prompt: the *current* tailored CV's/cover letter's own numbered blocks
(`docx_editor.list_blocks`/`blocks_as_text`, read fresh each turn — so a second turn sees the
first turn's own edits, not the master CV's/template's original state); the three profile
documents; the job description; the positioning breakdown document; the writing rules (the
cover letter's own punctuation/length rules are enforced in code after applying, not just
instructed, same as the one-shot step); the conversation so far; the new message.

The answer is the same block-id operations the one-shot steps already use, applied with
`docx_editor.apply_operations` (now exposed as the shared `apply_docx_edits`) against the
*current* file's bytes rather than the master CV's/template's:

```
=== EDIT ===
ID: <a block id from above>
TEXT: <its full replacement text>
=== END EDIT ===

=== INSERT AFTER ===
ID: <the block id this new one goes after>
TEXT: <the new block's text - formatting is cloned from the ID it follows>
=== END INSERT AFTER ===

=== REMOVE ===
ID: <a block id to delete entirely>
=== END REMOVE ===

=== ADD ROW AFTER ===     (Tailored CV only, for a skills-table row)
ID: <a table row id this new row goes after, e.g. T1R2>
CELLS: <cell text, in column order, separated by " | ">
=== END ADD ROW AFTER ===
```

An unknown block id rejects the whole turn, the file left exactly as it was — the same
verbatim-or-fail guarantee D-130 already established for the one-shot step, now reapplied turn
by turn. The cover letter's style check runs after applying the edits to the *resulting*
document, not just the changed blocks, since an edit to one paragraph can still produce a letter
that violates the overall punctuation or length rule.

## Trace, honesty, and routes

Same as `revise-steps.md`: the runner streams the answer in (`--include-partial-messages`), so
the chat's visible states are queued, started, streaming text, then done (cost and duration) or
failed. The honesty rule is D-125's own, reapplied to a chat edit rather than relaxed for one.

Routes mirror the profile ones, scoped by application and section:
`GET`/`POST /job-applications/{id}/revise/{section_kind}/turns`. An unknown `section_kind` or a
missing application 404s; a section with nothing yet to revise 400s with a message naming why.
