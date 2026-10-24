# Profile steps: contracts for the three profile prompts

Phase 2 (D-85, D-86). Each prompt is one Claude Job prompt, run through the `Runner` with no JSON
schema. Each answer is a single Markdown document, stored as a new version in `profile_outputs`.
Nothing is overwritten.

## Common rules

- **Order:** the career history, then the questionnaire analysis, then the strategy. Each later
  prompt may read the earlier documents in full.
- **Input:** the extracted text of the profile files that extracted with status `ok` (see Phase 2
  step 6). Each file is written into the prompt in a block headed with its `file_id`, its kind and
  its name. The runner gives the model no tools (`--tools ""`), so a prompt never reads files
  itself.
- **Building:** each prompt is built when it runs, not when the job is queued, because each one
  uses the documents stored before it. The built text is stored with the prompt.
- **Writing rules:** every prompt includes the writing rules in force. These are the user's own
  uploaded rules if there are any (their latest extracted text), otherwise `Agent/rules/honesty.md`.
- **Size:** if the built prompt is larger than 150,000 characters, the prompt is not sent. The
  prompt fails with a message that says the input is too large. Splitting large inputs is not part
  of Phase 2.
- **Answer:** the whole answer is one Markdown document, in the voice and structure of the
  document it replaces (a CV-style career history, a questionnaire report, a positioning strategy).
  No surrounding JSON, no code fence.
- **Sourcing:** a claim that comes from a specific file says so inline, in words (for example "per
  the 09-26 CV" or "per the questionnaire, Q3"), not as a structured reference. This is a writing
  instruction, not a field the code checks.
- **Honesty:** documents follow `Agent/rules/honesty.md` and D-85. They use only what the inputs
  say, and do not invent or embellish a claim. The user reviews the document before anything later
  uses it.

## 1. Career history

Input: every master CV, every older CV, every older cover letter, every additional file (Phase 12,
D-256) and the user's own career history, as extracted text.

Purpose: one history of the career, reconciling what the separate CVs and letters say (D-40). Where
sources disagree, the document says so in prose (for example "the 02-18 CV gives 2019 as the end
date; the 09-26 CV gives 2020") rather than resolving the conflict. The user reviews and edits the
result on the Profile page. This document is the one evidentiary source for the two prompts after
it: there is no separate Fact Sheet (D-86).

Additional files (reference letters, work attestations, academic transcripts and similar, D-255)
are read as secondary, corroborating evidence, not as a primary source: the prompt tells Claude to
use them to support or add detail to what the CVs and letters already establish, not to build a new
career entry from one alone (D-258).

Minimum evidence: generating a career history needs at least one master CV or older CV present.
Older cover letters and additional files are read as content once that minimum is met, but neither
satisfies it alone (D-257) — this phase tightens what had been, in code, any evidence item (an older
letter with no CV present was previously enough), to match what this section already said.

Code checks: the answer is not empty.

## 2. Questionnaire analysis (the questionnaire report)

Input: the questionnaire (extracted text), and the career history.

Purpose: the report on what the questionnaire says. Its sections follow the report the user writes
(D-73): how the material reads as a whole, the career narrative, recurring patterns, independent
work, CV-support points, nuance, CV implications, and open items. The prompt asks for these as
Markdown headings, not as separate structured fields.

Code checks: the answer is not empty.

## 3. Strategy (the positioning strategy)

Input: the questionnaire analysis, and the career history.

Purpose: the positioning strategy. Its sections follow the strategy the user writes (D-73): a
differentiator, main/secondary/tertiary lanes (D-221 — tertiary covers everything else the
material supports, not roles to avoid) each with a fit rating (0.5 to 5, in steps of 0.5) and why,
geography, a comp anchor, effort allocation, and open questions. The prompt asks for these as
Markdown headings, not as separate structured fields.

Code checks: the answer is not empty.

## Own versions and what a run does (D-68, D-69, D-86)

The user can upload their own version of each output: the career history (`own_full_cv_history`),
the questionnaire analysis (`own_questionnaire_analysis`) and the positioning strategy
(`own_strategy`). An uploaded file is used in place of a generated one, copied in as-is with no
reformatting call to Claude, since there is no schema left to convert it into (this simplifies
D-68, which previously had the CLI rewrite an upload into a structured shape).

Each run decides what to do for each output, in order:

- **generate**: no own file, and the output is missing, or an output it is built on was made again
  in this run. A prompt is sent to Claude.
- **use own**: an own file exists and its content is not yet the current document. The file's text
  becomes the current version, recorded against its hash. No prompt is sent.
- **skip**: the current document (generated or the user's own) is already up to date. No prompt is
  sent, and it is recorded as "Skipped: already in place."

The documents are built on each other in this order: the career history, then the questionnaire
analysis and the strategy. So a new career history makes a new questionnaire analysis and strategy,
unless the user's own version of one of them is in place.

The run refuses to start when nothing is missing, and it says what to upload. A run needs a master
CV or older CV, or an own career history, if it has to make the career history (D-257), and a
questionnaire or an own questionnaire analysis if it has to make the questionnaire analysis.

Master CVs are one kind, `master_cv`, for English and French alike (D-67). The language is not
stored.

## Additional files: manual text (Phase 12, D-259)

Additional files are expected to include scans with no text layer — nothing is OCR'd (D-41), so
extraction for one of these can come back `no_text`, `unsupported` or `failed`. For this kind only,
the user can type the text themselves in place of extraction. The typed text becomes that file's
`extracted_text`, read by the career history prompt exactly like any other extraction, and is also
written to a sidecar `.txt` file next to the original upload, so the managed folder shows what was
typed beside the scan it belongs to. The row's `extraction_status` becomes `manual`; the extraction
re-run every profile analysis performs on every file (D-83) skips a `manual` row rather than
overwriting it from the original file. This does not apply to any other kind — CVs, cover letters
and the cover letter template are expected to stay text-native.

## Review

Each document is read and, if needed, edited directly on the Profile page (the same editor
`full_cv_history` and `strategy` already use). There is no per-claim verify or reject step: the
user's review is of the whole document, the way they already review a CV or cover letter before it
is used (D-85).
