# LocalJobTracker: Development Plan

**Current phase: 0.** Status: draft for review.

This plan says what gets built, in what order, and how we know a phase is done. `CLAUDE.md` holds the rules. `DECISIONS.md` holds why things are the way they are.

## How we work

- Each phase begins with a step list written under the phase heading. You approve it before any product code is written.
- Steps are small. After each step, the command output or screenshot is shown.
- A phase is done when every "Done when" item is checked with evidence and you confirm in chat.
- Tick items as they pass. Record any new decision in `DECISIONS.md`.

## Phase overview

| # | Phase | Main outcome |
|---|---|---|
| 0 | Setup | Repo docs, Agent folder, tools checked, Claude runner confirmed |
| 1 | Skeleton | Backend, UI, runner and database run end to end with fake data |
| 2 | Profile onboarding | Your files in, a reviewed Fact Sheet out |
| 3 | Tracker | Real data in a table, editable, with file preview |
| 4 | Add job | A listing (text, URL, HTML file or PDF) becomes a file and a tracker row |
| 5 | Job workspace | Positioning, tailored CV and cover letter, revised by comment |
| 6 | Emails and chat | Email files attached to a job; chat proposes actions you confirm |
| 7 | Question memory | Answered clarifying questions are found again |
| 8 | Shell and hardening | Electron shell, backups, run log, optional board |
| Parked | Not scheduled | Browser assist, managed agent loop, form filling |

---

## Phase 0: Setup

**Goal:** the repo and tools are ready, and the Claude runner behaves as the notes say.

Scope
- Write `CLAUDE.md`, `DECISIONS.md`, `DEVELOPMENT-PLAN.md`, `README.md` (this step).
- Create the `Agent/` folder with `skills/`, `rules/` and `specs/`. Git ignores empty folders, so each one gets a file once it has content.
- Check versions: `uv`, Python 3.12, Node, `claude`.
- Smoke test: `claude -p "reply OK"` from a scratch folder outside the repo.
- Create `planning/runner-notes.md` from the archived spike, re-checked against the current `claude` help output.
- Create `planning/mockup-notes.md` listing the known mockup flaws (placeholder model labels, a false "local" claim, the mono font not loaded, the cut-down command palette and sub-scores).

Done when
- [x] Version commands print their output. (2026-10-05: uv 0.12.23, Python 3.12.8, Node v24.11.1, Claude Code 2.1.289)
- [x] `claude -p "reply OK"` returns a reply. (2026-10-05: `OK`, exit 0, run from a scratch folder outside the repo)
- [x] `runner-notes.md` matches the current `claude` help. (2026-10-05: each flag checked against 2.1.289 help; `--max-turns` confirmed absent)
- [x] `mockup-notes.md` exists and lists the flaws. (2026-10-05: five flaws, each with file and line)
- [x] You approve the four root documents.

---

## Phase 1: Skeleton

**Goal:** the whole stack runs end to end with fake data.

Scope
- FastAPI backend on 127.0.0.1 with a per-launch token and a health endpoint.
- Vite, React, TypeScript, Tailwind v4 and shadcn/ui. Fonts self-hosted.
- App shell, and a Jobs table page with synthetic seed jobs in `tests/fixtures/synthetic/`.
- `Runner` interface with `FakeRunner` and `ClaudeCodeRunner`. One real Claude call started from a button, with its output shown in the UI.
- SQLite database at `%LOCALAPPDATA%\LocalJobTracker\` with a first migration.
- One `check` command that runs lint, type checks and tests. Add its command to `CLAUDE.md`.

Done when
- [ ] `check` is green (output shown).
- [ ] The real Claude call appears in the UI.
- [ ] The browser's network log shows no requests to external hosts.
- [ ] The Jobs table matches the table mockup in `planning/`. You compare the two.
- [ ] Stopping the backend leaves no orphan process.

---

## Phase 2: Profile onboarding

**Goal:** your background becomes a reviewed Fact Sheet that later documents may use.

Scope
- Upload screen for: master CVs (English and French), older CVs, older cover letters, and the questionnaire. Files are copied into app data. Originals are never touched.
- Claude produces three outputs from these files: a questionnaire analysis, a strategy overview, and a non-positioned CV Fact Sheet. Each fact has a source file, a location in it, and a date.
- Conflicts between files: the master CVs win, and the conflict is shown to you.
- Review screen: edit facts, mark each one verified or rejected. Only verified facts are usable later.
- Upload screen for your own writing rules. They are stored in app data and override the defaults in `Agent/rules/`.
- Create `Agent/specs/profile-steps.md` (inputs, outputs, validation) and `Agent/rules/honesty.md` (default) before this phase's code.

Done when
- [ ] The analysis runs on your real files, and you check its output.
- [ ] Every fact has a source and a date (automated check).
- [ ] You verify or correct the Fact Sheet in the UI.
- [ ] Personal-data scan of the repo is clean.

Out of scope: positioning for a specific job.

---

## Phase 3: Tracker

**Goal:** your tracker data lives in the database, with a table, editing and file preview.

Scope
- Import from `Job Application Tracker.xlsx`. A dry-run report comes first. The import is idempotent and read-only on the source. The 8 "Identified" rows become "Not Started" (see DECISIONS.md), and the dry run lists them.
- Table: sort, filter by status, search, and a due or overdue section at the top.
- Inline editing: status, lane, dates, next action, notes, file links. Each status change writes a history row.
- File preview: `.docx` is converted to PDF in a temporary file and deleted after viewing. `.eml` and `.msg` are rendered as HTML or text. An "Open in Word" button opens the file with the system handler.
- Skills in `Agent/skills/`: convert docx to PDF, and read docx. Check how the runner loads them (this is verified in this phase, not assumed).
- Specs: `Agent/specs/domain.md` (entities and statuses), `Agent/specs/files.md` (managed folder layout).

Done when
- [ ] The dry-run report matches the spreadsheet: row counts, the 8 changed rows, and three spot-checked rows.
- [ ] Running the import twice creates no duplicates.
- [ ] An edit survives an app restart.
- [ ] One `.docx`, one `.eml` and one `.msg` preview correctly. "Open in Word" works.
- [ ] Migrations apply and roll back.

Out of scope: the Kanban board (see Phase 8).

---

## Phase 4: Add job

**Goal:** a listing becomes a file and a tracker row.

Scope
- Four ways in: raw text (pasted), a URL, a saved HTML page, or a PDF file. `.txt` and `.docx` files are accepted too.
- Text is extracted by code, not by Claude:
  - Raw text: whitespace and encoding are normalised.
  - URL: the app fetches the page with a timeout and a size cap, then keeps the readable text and drops navigation, scripts and footers.
  - Saved HTML file: the same conversion as for a URL.
  - PDF: the text layer is read page by page. No OCR in this phase. A PDF with no text layer is reported as a fallback case.
  - DOCX: paragraph and table text.
- Every intake records how the text was obtained: method, source URL or file name, and the date.
- The extracted text is shown to you before Claude runs. You can edit it, so a bad capture (cookie banner, cut-off PDF) is caught early.
- Fallbacks: a blocked URL, a page with no readable text (for example one that loads its content with JavaScript), or a PDF with no text layer. In each case the UI says which one happened and suggests saving the page as HTML or pasting the text.
- Claude receives the reviewed text and returns the listing file plus structured fields: company, role, lane suggestion, location, work mode, requirements. This step gets no tools.
- Duplicate check by URL and by content hash.
- The listing is saved to the managed folder (`files/<company>/<role>/listing.txt`), and a tracker row is created.
- Create `Agent/specs/intake-steps.md` (extraction rules per input type, and the Claude step contract).
- Candidate libraries, confirmed in this phase: `pypdf` (or PyMuPDF) for PDF, an HTML-to-text extractor such as `trafilatura`, and `python-docx` for DOCX.

Done when
- [ ] Raw text, one URL, one saved HTML page and one text-layer PDF each produce listing text, and you check the output.
- [ ] A scanned PDF and a JavaScript-only page each show the fallback message, not an empty listing.
- [ ] A blocked URL falls back to the saved-HTML or paste path.
- [ ] The extracted text can be edited before Claude runs.
- [ ] A hostile fixture ("ignore previous instructions...") changes nothing beyond the extracted fields.
- [ ] A repeat of an added listing is detected.
- [ ] Synthetic fixtures for each input type exist under `tests/fixtures/synthetic/`.

---

## Phase 5: Job workspace and documents

**Goal:** for one job, the positioning, tailored CV and cover letter are produced and revised by comment.

Scope
- Job page: the listing on one side, the documents on the other.
- Buttons: Prepare positioning (fit, gaps, one score, with evidence per requirement), Write tailored CV, Write cover letter, and Prepare all. The positioning comes first in the chain.
- Each output is a new version file. Nothing is overwritten.
- A comment on any version produces a new version. Comments are kept with the versions.
- Positioning may ask clarifying questions. Answers go into the job's record. (Storage of answers for reuse is Phase 7.)
- Every claim cites a verified fact id. Code checks that each cited id exists and is verified.
- Cover letter checks in code: no colon or dash used as sentence punctuation, and the length limit.
- CV: a copy of the chosen master (English or French), with edits. The formatting-preservation check compares page count and styles against the master.
- Create `Agent/specs/steps.md` (positioning, CV and letter contracts) and `Agent/skills/edit-docx/`.

Done when
- [ ] On a real listing, you judge the positioning, CV and letter. Quality is your call.
- [ ] A comment produces v2, and v1 is kept.
- [ ] Every cited fact id exists and is verified (automated check).
- [ ] Cover letter checks pass on positive and negative samples.
- [ ] CV formatting checks pass against the master.

---

## Phase 6: Emails and chat

**Goal:** email files attach to a job, and chat can propose changes that you confirm.

Scope
- "Add email" button on a job and in the table.
- Parse `.eml` (standard library) and `.msg` (`extract-msg`). Store each file in the job's correspondence folder.
- Claude proposes status or next-action changes from the email. Each proposal shows as a preview with Confirm.
- Chat panel: slide-out on the right, scoped to a job or to General. It can only propose actions. Nothing runs without Confirm.

Done when
- [ ] Injection text in an email changes nothing without Confirm.
- [ ] A proposed update applies only after Confirm.
- [ ] Three real emails are filed to the right jobs (you check).

---

## Phase 7: Question memory

**Goal:** answered clarifying questions are found again instead of asked twice.

Scope
- Questions and answers are stored in SQLite, which is the source of truth.
- Retrieval starts with keyword search. A FAISS index is added only if keyword search misses real questions in testing. The index is built from SQLite and lives in app data.
- Choosing an embedding model is a decision (see DECISIONS.md, Open). Claude does not offer an embeddings API.

Done when
- [ ] Questions asked in Phase 5 are stored with their answers.
- [ ] Five paraphrases of a stored question are each matched, or the misses are recorded.

---

## Phase 8: Shell and hardening

**Goal:** the app is safe to use every day.

Scope
- Electron shell that starts and stops the backend.
- Backup: copy the database and managed files on a schedule. A restore drill.
- Run log: each Claude call with its token count and cost.
- Log redaction and a secrets scan.
- Board view, if you still want it after using the table.

Done when
- [ ] The restore drill recovers a deleted database.
- [ ] Secrets and personal-data scans are clean.
- [ ] A week of real use, and your go or no-go.

---

## Parked (not scheduled)

- **Apply with AI** (browser beside a job). Conflicts with the form-filling non-goal. A narrower, read-only version can be reconsidered after Phase 8.
- **Managed agent loop** (replacing one step with our own loop, to compare). A learning goal. Optional, after Phase 8, with its own design note.
- **Form filling and auto-submission.** Out of scope.
