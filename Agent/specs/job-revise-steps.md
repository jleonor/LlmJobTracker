# Job-page revise steps: the contract for a job-section chat turn

Extends Phase 3 (D-136). A job-page revise conversation is scoped to one Job Application and one
of its five sections: `job_details`, `positioning`, `application_history`, `tailored_cv`,
`cover_letter`. Each turn the user sends is one new Claude Job, with one prompt, run through the
`Runner` with no JSON schema and no tools (`--tools ""`, same as every other job-page prompt). The
answer is a true incremental patch against the section's own current content, not a full
replacement — mirrors `revise-steps.md`'s OLD/NEW model in spirit, but each section needs its own
answer grammar, since none of the five is a single plain-text document the way a profile output
is.

`job_details` and `application_history` have a grammar so far, matching D-136's risk-ascending
order. Positioning analysis, Tailored CV and Cover letter are reserved section kinds (the
`job_revise_turns` table's CHECK constraint already allows them) with no grammar yet —
`submit_job_revise_turn` raises `JobReviseNotReady` for any of them today, naming that the chat
isn't built for that section yet.

## Job kind, table, and prompt shape

- **Kind:** `revise_<section kind>` — `revise_job_details`, `revise_application_history`. Each
  links to the `job_application_id` it's revising, unlike a profile revise turn (which links to
  none).
- **Table:** `job_revise_turns` (migration 18) — one shared table with a `section_kind` column,
  the same single-table-many-kinds shape `revise_turns` already uses for the three profile
  documents, kept separate from it since `revise_turns`'s `output_kind` CHECK and lack of a
  `job_application_id` column are profile-specific by design. `attachment_job_file_id` (D-138) is
  the `job_files` row a turn optionally carries — filed for real *before* the turn is queued (the
  route's caller uploads it first through the existing `/job-applications/{id}/files/{kind}`
  endpoint, the same as any other upload), not a separate attachment-storage mechanism of its own.
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

## Trace, honesty, and routes

Same as `revise-steps.md`: the runner streams the answer in (`--include-partial-messages`), so
the chat's visible states are queued, started, streaming text, then done (cost and duration) or
failed. The honesty rule is D-125's own, reapplied to a chat edit rather than relaxed for one.

Routes mirror the profile ones, scoped by application and section:
`GET`/`POST /job-applications/{id}/revise/{section_kind}/turns`. An unknown `section_kind` or a
missing application 404s; a `section_kind` whose grammar isn't built yet, or a section with
nothing yet to revise, 400s with a message naming why.

## Out of scope here

- Positioning analysis, Tailored CV and Cover letter's own answer grammars — each is its own
  appended batch (D-136), built and reviewed in that order before its chat turn can actually run.
