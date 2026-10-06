# LocalJobTracker: Development Plan

**Current phase: 2.** Phase 0 and Phase 1 are done. Phase 2's step list is approved in chat (2026-10-06) and waits for your go to start. O-08, O-09 and O-10 are answered (D-62 to D-64). Tables are renamed as D-59 proposes (`job_applications`, `status_history`).

This plan says what gets built, in what order, and how we know a phase is done. `CLAUDE.md` holds the rules. `DECISIONS.md` holds why things are the way they are.

## How we work

- Each phase begins with a step list written under the phase heading. You approve it before any product code is written.
- Steps are small. After each step, the command output or screenshot is shown.
- A phase is done when every "Done when" item is checked with evidence and you confirm in chat.
- Tick items as they pass. Record any new decision in `DECISIONS.md`.
- Git, per phase (D-61): create the phase's branch from `main` when the phase starts, for example `phase-2-profile`. Build on that branch and commit locally. When the phase is done, fast-forward `main` to it with `git merge --ff-only`, and keep the branch. Nothing is pushed until the whole project is done.

## Phase overview

| # | Phase | Main outcome |
|---|---|---|
| 0 | Setup | Repo docs, Agent folder, tools checked, Claude runner confirmed |
| 1 | Skeleton | Backend, UI, runner and database run end to end with fake data |
| 2 | Profile onboarding | Your files in, a reviewed Fact Sheet out, and the Claude Jobs queue running |
| 3 | Tracker | Real data in a table with status history, editable, with file preview |
| 4 | Add job | A listing (text, URL, HTML file or PDF) becomes a file, a tracker row and a queued positioning Claude Job |
| 5 | Job workspace | Job page with positioning and match score, tailored CV and cover letter, revised by comment |
| 6 | Emails and chat | Email history on the job page; chat proposes actions you confirm |
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
- App shell, and a Jobs table page with synthetic seed jobs in `tests/fixtures/synthetic/`. The table columns change to the D-46 list (added 2026-10-06).
- `Runner` interface with `FakeRunner` and `ClaudeCodeRunner`. One real Claude call started from a button, with its output shown in the UI.
- SQLite database at `%LOCALAPPDATA%\LocalJobTracker\` with a first migration.
- One `check` command that runs lint, type checks and tests. Add its command to `CLAUDE.md`.

Done when
- [x] `check` is green (output shown). (2026-10-05: `python scripts/check.py` on commit f265885: 7 of 7 steps PASS, exit 0. API: 23 passed, 1 live test deselected. Web: lint, build and 2 vitest tests pass.)
- [x] The real Claude call appears in the UI. (2026-10-05: "Run Claude check" button returned `OK`, 2.7 s, estimated cost $0.0039. Screenshot taken in the browser pane.)
- [x] The browser's network log shows no requests to external hosts. (2026-10-05: dev server and production build (`vite preview`) both contacted only 127.0.0.1. Fonts are local. The check button's call goes to the local API, which calls Claude Code.)
- [x] The table shows the D-46 columns (Company, Title, Lane, Location, Status, Last updated, Match score, queue badge), with synthetic data in each. (2026-10-06: screenshot at 1400 px, six synthetic applications, each column filled or a dash where empty. Migration 2 also run on the existing dev database: six rows kept, each with a history row. Empty state checked. Commits 677722d and dc8cc45.)
- [x] The Jobs table matches the look of the table mockup in `planning/`. You compare the two. (2026-10-06: you confirmed in chat that the table looks good. Accepted differences: triage cards, search, filters and footer are left out (D-03, D-04, Phase 3). Icons are Lucide, not Material Symbols. The columns follow D-46, not the mockup.) (Built as the first column set and screenshotted. Known differences: triage cards, search, filters and footer left out (D-03, D-04, Phase 3). Icons are Lucide, not Material Symbols. Waiting for your comparison, after the D-46 columns are in.)
- [x] Stopping the backend leaves no orphan process. (2026-10-05: stopped the API under `scripts/dev.py`. The launcher exited and stopped Vite. No `localjobtracker`, `vite` or `node` process was left, and ports 5173 and 8765 were free.)

---

## Phase 2: Profile onboarding

**Goal:** your background becomes a reviewed Fact Sheet that later documents may use.

Scope
- Upload screen for: master CVs (English and French), older CVs, older cover letters, and the questionnaire. Files are copied into app data. Originals are never touched.
- Claude produces four outputs from these files, in this order: `FULL_CV_HISTORY` (D-40, D-64), a non-positioned CV Fact Sheet, a questionnaire analysis, and a strategy overview. Each fact has a source file, a location in it, and a date.
- Conflicts between files: the master CVs win, and the conflict is shown to you.
- Review screen: edit facts, mark each one verified or rejected. Only verified facts are usable later.
- Upload screen for your own writing rules. They are stored in app data and override the defaults in `Agent/rules/`.
- Profile page (D-58): old CVs, old cover letters, master CVs, the questionnaire, the questionnaire report, and the positioning strategy with its lanes (O-12).
- Claude Jobs queue (D-49 to D-52): one Claude Job runs at a time, in creation order, and all of its prompts finish before the next one starts. The queue is stored in SQLite and survives a restart (O-10). A plan limit pauses the queue and shows a Resume button (O-09). The queue sits between the app and the runner. `ClaudeCodeRunner` does not know about it.
- O-08, O-09 and O-10 are answered (D-62, D-63, D-64). The queue pauses on a plan limit and resumes on a Resume click (D-63).
- Create `Agent/specs/profile-steps.md` (inputs, outputs, validation) and `Agent/rules/honesty.md` (default) before this phase's code.

Step list (approved in chat 2026-10-06; starts when you say go)

1. Cut `phase-2-profile` from `main` (D-61). Write `Agent/specs/profile-steps.md` (inputs, outputs, validation for the four prompts, including `FULL_CV_HISTORY`) and `Agent/rules/honesty.md` (generic default). Docs only.
2. Migration 3: `claude_jobs` (kind, optional `job_application_id`, status), `claude_job_prompts` (ordered), `profile_files` (kind, app-data path, SHA-256, upload date, extracted text), `profile_outputs` (versioned `FULL_CV_HISTORY`, Fact Sheet, questionnaire analysis, strategy), `facts` (text, source file, location, date, status unverified, verified or rejected). Tests: applies on a copy of the dev database, and an empty database.
3. Runner: a `RateLimitError` type in the `Runner` interface. `FakeRunner` can simulate it. `ClaudeCodeRunner` maps the CLI's `rate_limit` events to it (runner-notes). Check whether the CLI reports a reset time: record the result in `planning/runner-notes.md`. The only outcome the app relies on is Resume (D-63).
4. Claude Jobs queue as an app module between the API and the `Runner` (D-51). One job at a time, in creation order, all prompts before the next. Stored in SQLite (D-62). On startup, a job left `processing` returns to `queued`, and its interrupted prompt runs again from the start. Pause on `RateLimitError`. Resume and Cancel endpoints. Cancel sends SIGTERM and marks the job cancelled (runner-notes). Tests with `FakeRunner`: pause at a simulated limit, resume, restart survival, cancel.
5. Upload endpoints and screen for master CVs (EN and FR), older CVs, older cover letters, and the questionnaire. Files are copied into `%LOCALAPPDATA%\LocalJobTracker\`, with a SHA-256 hash. Upload of your own writing rules, also in app data. Test: the source file is unchanged after upload.
6. Text extraction by code: `pypdf` for PDF, `python-docx` for DOCX, plain text for `.txt`. The result is stored with the file, and any file with no text is reported. Synthetic fixtures under `tests/fixtures/synthetic/`.
7. The four Claude Jobs, one per output, in the D-64 order: `FULL_CV_HISTORY`, Fact Sheet, questionnaire analysis, strategy. Each is a headless prompt with a structured output (`--json-schema`), checked against `Agent/specs/profile-steps.md`. Code checks that every fact has a source and a date, and that each source file exists. Conflicts between sources are recorded with both sides.
8. Fact Sheet review screen: edit, verify or reject each fact, and see its conflicts. One function returns only verified facts; later steps may use only that function.
9. Profile page (D-58): old CVs, old cover letters, master CVs, questionnaire, questionnaire report, `FULL_CV_HISTORY`, and the strategy with editable lanes (O-12).
10. Claude Jobs queue screen: idle, queued, processing, paused, cancelled and done. Resume and Cancel buttons. The header counter, and the table badge later, read "Claude: queued" (D-59).
11. Checks: `python scripts/check.py` output; personal-data scan of the repo; screenshots of the pause and resume (fake runner) and of a queue that survives a restart; a note in `planning/runner-notes.md` for the reset-time result.
12. The real-file run: you upload your files, the four Claude Jobs run, and you check the output. Quality is your call.

Done when
- [ ] The analysis runs on your real files, and you check its output.
- [ ] Every fact has a source and a date (automated check).
- [ ] You verify or correct the Fact Sheet in the UI.
- [ ] A queued Claude Job pauses at a simulated plan limit (fake runner) and resumes on click.
- [ ] Queued Claude Jobs survive an app restart.
- [ ] Personal-data scan of the repo is clean.

Out of scope: positioning for a specific job.

---

## Phase 3: Tracker

**Goal:** your tracker data lives in the database, with a table, editing and file preview.

Scope
- Import from `Job Application Tracker.xlsx`. A dry-run report comes first. The import is idempotent and read-only on the source. The 8 "Identified" rows become "Not Started" (see DECISIONS.md), and the dry run lists them.
- Table: the D-46 columns, sort, filter by status and search. The due or overdue section is removed (D-46). A queue badge (idle, queued, processing) comes from the Claude Jobs queue, and a queue counter sits beside Add Job.
- Statuses per D-44: Not Started, Applied, Screening, Interview, Offer, with Rejected and Withdrawn as end states. The import maps the spreadsheet's values to these (D-05, D-44).
- Status history (D-45): each change is stored with its date and time. "Last updated" is the newest row's date. Only forward moves count as progress.
- Job Application fields (D-54, D-55): portal (name and URL), location, work mode, contract type, description, requirements, lane, notes, next action, due date, file links. Location is free text, and Claude's suggested city match is confirmed by the user (D-53).
- Inline editing on the table: status, lane, location, and the file links. Next action, due date and notes are edited on the job page (D-56).
- File preview: `.docx` is converted to PDF in a temporary file and deleted after viewing. `.eml` and `.msg` are rendered as HTML or text. An "Open in Word" button opens the file with the system handler.
- Skills in `Agent/skills/`: convert docx to PDF, and read docx. Check how the runner loads them (this is verified in this phase, not assumed).
- Specs: `Agent/specs/domain.md` (entities: Job Application, status history, Claude Job with its prompts, requirement with weight and match; statuses), `Agent/specs/files.md` (managed folder layout).

Done when
- [ ] The dry-run report matches the spreadsheet: row counts, the 8 changed rows, and three spot-checked rows.
- [ ] Running the import twice creates no duplicates.
- [ ] An edit survives an app restart.
- [ ] One `.docx`, one `.eml` and one `.msg` preview correctly. "Open in Word" works.
- [ ] Each status change writes a history row. "Last updated" matches the newest row, and the job page timeline shows the dates reached (screenshot).
- [ ] The table shows the D-46 columns, and the queue badge reflects the queue state.
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
- Claude receives the reviewed text and returns the listing file plus structured fields: company, role, lane suggestion, location (matched to an existing city value where one fits, for the user to confirm), work mode (Onsite, Hybrid, Remote, Unknown), contract type (Full-Time, Part-Time, Contract/Short Term, Other, Unknown), portal (name and URL, or "Email"), description and requirements. This step gets no tools.
- Duplicate check by URL and by content hash.
- The listing is saved to the managed folder (`files/<company>/<role>/listing.txt`), and a tracker row is created.
- A new Job Application starts as Not Started, and it queues one positioning Claude Job (D-49). The positioning output itself is built in Phase 5.
- Create `Agent/specs/intake-steps.md` (extraction rules per input type, and the Claude step contract).
- Candidate libraries, confirmed in this phase: `pypdf` (or PyMuPDF) for PDF, an HTML-to-text extractor such as `trafilatura`, and `python-docx` for DOCX.

Done when
- [ ] Raw text, one URL, one saved HTML page and one text-layer PDF each produce listing text, and you check the output.
- [ ] A scanned PDF and a JavaScript-only page each show the fallback message, not an empty listing.
- [ ] A blocked URL falls back to the saved-HTML or paste path.
- [ ] The extracted text can be edited before Claude runs.
- [ ] A hostile fixture ("ignore previous instructions...") changes nothing beyond the extracted fields.
- [ ] A repeat of an added listing is detected.
- [ ] Adding a listing creates its tracker row with status Not Started and queues one positioning Claude Job, which the queue badge shows.
- [ ] Synthetic fixtures for each input type exist under `tests/fixtures/synthetic/`.

---

## Phase 5: Job workspace and documents

**Goal:** for one job, the positioning, tailored CV and cover letter are produced and revised by comment.

Scope
- Job page, top to bottom (D-56): header with title and company; the "not done yet" flags for positioning, tailored CV and cover letter (D-48); job details (portal, description, requirements, location, work mode, contract type); application history (status timeline with achieved statuses dated and the rest greyed out, notes, next action, due date); positioning analysis; files.
- Positioning runs automatically when a Job Application is added (D-49). Each requirement gets a weight (0 to 10) and a match (0 to 10), each with evidence. Code computes the fit % (D-47). The analysis also gives fit bullets, gap bullets and a job-specific strategy. The match score shows in the table too.
- Buttons: Re-run positioning, Write tailored CV, Write cover letter, and Prepare all. Each button queues a Claude Job. Positioning comes first in the chain.
- Files (D-57): Claude proposes a master CV when the listing is added, and the user can change it. Tailored CV and cover letter each have a button to write one.
- Each output is a new version file. Nothing is overwritten.
- A comment on any version produces a new version. Comments are kept with the versions.
- Positioning may ask clarifying questions. Answers go into the job's record. (Storage of answers for reuse is Phase 7.)
- Every claim cites a verified fact id. Code checks that each cited id exists and is verified.
- Cover letter checks in code: no colon or dash used as sentence punctuation, and the length limit.
- CV: a copy of the chosen master (English or French), with edits. The formatting-preservation check compares page count and styles against the master.
- Create `Agent/specs/steps.md` (positioning, CV and letter contracts) and `Agent/skills/edit-docx/`.

Done when
- [ ] On a real listing, you judge the positioning, CV and letter. Quality is your call.
- [ ] The fit % matches a hand calculation from the stored weights and matches.
- [ ] The "not done yet" flags clear as each output is written.
- [ ] A comment produces v2, and v1 is kept.
- [ ] Every cited fact id exists and is verified (automated check).
- [ ] Cover letter checks pass on positive and negative samples.
- [ ] CV formatting checks pass against the master.

---

## Phase 6: Emails and chat

**Goal:** email files attach to a job, and chat can propose changes that you confirm.

Scope
- "Add email" button on a job. The email history on the job page lists each email by title as a preview, and clicking one expands it (D-57).
- Parse `.eml` (standard library) and `.msg` (`extract-msg`). Store each file in the job's correspondence folder.
- Claude proposes status or next-action changes from the email. Each proposal shows as a preview with Confirm.
- Chat panel: slide-out on the right, scoped to a job or to General. It can only propose actions. Nothing runs without Confirm.

Done when
- [ ] Injection text in an email changes nothing without Confirm.
- [ ] A proposed update applies only after Confirm.
- [ ] Email previews list by title and expand on click (screenshot).
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
