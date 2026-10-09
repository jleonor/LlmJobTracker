# LocalJobTracker: Development Plan

**Current phase: 3, not started.** Phases 0 through 2 are done; `main` is fast-forwarded to Phase 2's end (D-61). Phase 3's step list is drafted (D-97) and awaiting your approval before any product code is written (CLAUDE.md rule 7).

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
| 2 | Profile onboarding | Your files in, a reviewed career history, questionnaire analysis and strategy out, and the Claude Jobs queue running |
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

**Goal:** your background becomes a reviewed career history, questionnaire analysis and strategy that later documents may use.

Scope
- Upload screen for: master CVs (one kind for English and French, D-67), older CVs, older cover letters, the questionnaire, the cover letter template (D-71), and optionally the user's own career history, questionnaire analysis and positioning strategy (D-68, narrowed by D-86). Files are copied into app data. Originals are never touched.
- Claude produces three documents from these files, in this order: the career history (D-40, D-86), a questionnaire analysis, and a strategy overview. Each is Markdown prose, with a claim's source given in words where it matters, not as a structured field (D-86).
- Conflicts between files: recorded in the career history's prose, not resolved by the app; the user reads and judges them.
- The career history, questionnaire analysis and strategy are read and edited as documents on the Profile page (D-85, D-86). There is no per-claim verify or reject step.
- Upload screen for your own writing rules. They are stored in app data and override the defaults in `Agent/rules/`.
- Profile page (D-58): old CVs, old cover letters, master CVs, the questionnaire, the questionnaire report, and the positioning strategy with its lanes (O-12).
- Claude Jobs queue (D-49 to D-52): one Claude Job runs at a time, in creation order, and all of its prompts finish before the next one starts. The queue is stored in SQLite and survives a restart (O-10). A plan limit pauses the queue and shows a Resume button (O-09). The queue sits between the app and the runner. `ClaudeCodeRunner` does not know about it.
- O-08, O-09 and O-10 are answered (D-62, D-63, D-64). The queue pauses on a plan limit and resumes on a Resume click (D-63).
- Create `Agent/specs/profile-steps.md` (inputs, outputs, validation) and `Agent/rules/honesty.md` (default) before this phase's code.

Step list (approved in chat 2026-10-06; starts when you say go. Steps 7 to 9 and the done-when list revised 2026-10-07 per D-85/D-86: the Fact Sheet is dropped, and the three remaining outputs are Markdown documents, not a validated JSON schema.)

1. Cut `phase-2-profile` from `main` (D-61). Write `Agent/specs/profile-steps.md` (inputs, outputs, validation for the four prompts, including `FULL_CV_HISTORY`) and `Agent/rules/honesty.md` (generic default). Docs only.
2. Migration 3: `claude_jobs` (kind, optional `job_application_id`, status), `claude_job_prompts` (ordered), `profile_files` (kind, app-data path, SHA-256, upload date, extracted text), `profile_outputs` (versioned `FULL_CV_HISTORY`, Fact Sheet, questionnaire analysis, strategy), `facts` (text, source file, location, date, status unverified, verified or rejected). Tests: applies on a copy of the dev database, and an empty database. (2026-10-07: migration 10 drops the Fact Sheet's part of this schema; see step 7.)
3. Runner: a `RateLimitError` type in the `Runner` interface. `FakeRunner` can simulate it. `ClaudeCodeRunner` maps the CLI's `rate_limit` events to it (runner-notes). Check whether the CLI reports a reset time: record the result in `planning/runner-notes.md`. The only outcome the app relies on is Resume (D-63).
4. Claude Jobs queue as an app module between the API and the `Runner` (D-51). One job at a time, in creation order, all prompts before the next. Stored in SQLite (D-62). On startup, a job left `processing` returns to `queued`, and its interrupted prompt runs again from the start. Pause on `RateLimitError`. Resume and Cancel endpoints. Cancel sends SIGTERM and marks the job cancelled (runner-notes). Tests with `FakeRunner`: pause at a simulated limit, resume, restart survival, cancel.
5. Upload endpoints and screen for master CVs (EN and FR), older CVs, older cover letters, and the questionnaire. Files are copied into `%LOCALAPPDATA%\LocalJobTracker\`, with a SHA-256 hash. Upload of your own writing rules, also in app data. Test: the source file is unchanged after upload.
6. Text extraction by code: `pypdf` for PDF, `python-docx` for DOCX, plain text for `.txt`. The result is stored with the file, and any file with no text is reported. Synthetic fixtures under `tests/fixtures/synthetic/`.
7. (Revised 2026-10-07, D-85/D-86.) Three Claude Jobs, one per document, in order: the career history, the questionnaire analysis, the strategy. Each makes only what is missing, and uses the user's own upload as-is where one exists, with no reformatting call (D-69, D-86). Each is a headless prompt with no schema; the answer is Markdown, checked only for being non-empty against `Agent/specs/profile-steps.md`. Migration 10 drops the Fact Sheet's schema: the `facts` table, the `fact_sheet` and `own_fact_sheet` kinds.
8. (Revised 2026-10-07, D-85/D-86. Replaces the Fact Sheet review screen.) The career history, questionnaire analysis and strategy are each read and edited as a document on the Profile page, the way `full_cv_history` and `strategy` already could. No per-claim verify or reject step.
9. Profile page (D-58): old CVs, old cover letters, master CVs, questionnaire, questionnaire report, career history, and the strategy, each editable as a document (O-12).
10. Claude Jobs queue screen: idle, queued, processing, paused, cancelled and done. Resume and Cancel buttons. The header counter, and the table badge later, read "Claude: queued" (D-59).
11. Checks: `python scripts/check.py` output; personal-data scan of the repo; screenshots of the pause and resume (fake runner) and of a queue that survives a restart; a note in `planning/runner-notes.md` for the reset-time result.
12. The real-file run: you upload your files, the three Claude Jobs run, and you check the output. Quality is your call.

Done when
- [x] The analysis runs on your real files, and you check its output. (2026-10-07: run on your real CVs, letters and questionnaire this session; you confirmed in chat you are happy with the career history, questionnaire analysis and strategy it produced.)
- [x] Each document is reviewed by opening its file in the Profile page's upload section (revised 2026-10-07, D-87: there is no longer an in-app viewer). (2026-10-07: you confirmed in chat you are happy with the outputs and with the Profile page and LLM history UI you used to review them.)
- [x] A queued Claude Job pauses at a simulated plan limit (fake runner) and resumes on click. (2026-10-06: `test_a_plan_limit_pauses_the_job_and_resume_runs_the_prompt_again`. In the browser, Resume on a paused demo job moved it to done, with both prompts done. Screen read through the page text.)
- [x] Queued Claude Jobs survive an app restart. (2026-10-06: tests in `api/tests/test_claude_job_queue.py` restart the app with a job paused, a job left processing, and a prompt half done. Each comes back as the decisions say (D-62, D-63).)
- [x] Personal-data scan of the repo is clean. (2026-10-07: every tracked file scanned for the user's name and email, case-insensitive — no matches. Commit messages (`git log --all`) scanned the same way — no matches. `planning/` holds nothing tracked, per `.gitignore`.)

Out of scope: positioning for a specific job.

---

## Phase 3: Tracker

**Goal:** your tracker data lives in the database, with a table, editing and file preview.

Scope
- Import from `Job Application Tracker.xlsx`. A dry-run report comes first. The import is idempotent and read-only on the source. The 8 "Identified" rows need no renaming now that the app's own first status reads "Identified" too (D-101, narrows D-05); the dry run still lists them.
- Table: the D-46 columns, sort, filter by status and search. The due or overdue section is removed (D-46). A queue badge (idle, queued, processing) comes from the Claude Jobs queue, and a queue counter sits beside Add Job.
- Statuses per D-44/D-101: Identified, Applied, Screening, Interview, Offer, with Rejected and Withdrawn as end states. The import maps the spreadsheet's values to these (D-05, D-44, D-101).
- Status history (D-45): each change is stored with its date and time. "Last updated" is the newest row's date. Only forward moves count as progress.
- Job Application fields (D-54, D-55): portal (name and URL), location, work mode, contract type, description, requirements, lane, notes, next action, due date, file links. Location is free text, and Claude's suggested city match is confirmed by the user (D-53).
- Inline editing on the table: status, lane, location, and the file links. Next action, due date and notes are edited on the job page (D-56).
- File preview: `.docx` is converted to PDF in a temporary file and deleted after viewing. `.eml` and `.msg` are rendered as HTML or text. An "Open in Word" button opens the file with the system handler.
- Skills in `Agent/skills/`: convert docx to PDF, and read docx. Check how the runner loads them (this is verified in this phase, not assumed).
- Specs: `Agent/specs/domain.md` (entities: Job Application, status history, Claude Job with its prompts, requirement with weight and match; statuses), `Agent/specs/files.md` (managed folder layout).

Step list (drafted 2026-10-07, awaiting approval; reordered per D-97 so the job page is designed against real data shape and a Claude-CLI backfill is tried before the definitive migration and import are written)

1. Cut `phase-3-tracker` from `main` (D-61). Write `Agent/specs/domain.md` and `Agent/specs/files.md`. Docs only.
2. Extend the synthetic fixture (`tests/fixtures/synthetic/job_applications.json`) with the fields the job page needs but the table didn't: description, requirements, notes, and a sample file link.
3. Build the Job Application page against that seed data: the D-56/D-98 layout — flags, header (with a per-application queue badge beside the status tag), job details (portal, description, requirements, location, work mode, contract type), positioning analysis (fit bullets, gap bullets, match score with a visual, all from seed data), application history (status timeline, notes, next action, due date), files. The tailored CV, cover letter and the positioning breakdown document stay "not done yet" (D-48); their content is Phase 5. Check the result against the `planning/stitch` job-detail mockups before calling it done.
4. Side experiment, not wired into the app: a throwaway script that reads the real `Job Application Tracker.xlsx` (read-only) and the reference folder, and asks the Claude CLI to classify the fields the spreadsheet doesn't have for a sample of real rows — lane, work mode, contract type. Nothing is committed; `description` and `requirements` are left out of the experiment since older rows have no real source for them and backfilling would mean inventing content (D-85). Note which fields came back reliably in `planning/import-backfill-notes.md`.
5. Migration: add `description`, `requirements`, `notes` to `job_applications`; add a file-links table per `files.md`. Tests: applies on a copy of the dev database and an empty database, and rolls back.
6. Dry-run import: read the spreadsheet read-only, map columns (including the D-05/D-101 status mapping), apply whatever step 4 found reliable, and report row counts and the changed rows. No writes.
7. Apply import: idempotent insert of `job_applications` and `status_history` rows; a second run creates no duplicates.
8. Table UI: the D-46 columns, sort, status filter, search, the queue badge (idle, queued, processing), and a queue counter beside Add Job.
9. Inline table editing: status, lane, location, file links.
10. File preview: `.docx` to a temporary PDF deleted after viewing, `.eml`/`.msg` rendered as HTML or text, "Open in Word" via the system handler. `Agent/skills/`: convert-docx-to-pdf, read-docx — check how the runner actually loads them, not assumed.
11. Checks: `scripts/check.py` output; personal-data scan; screenshots of the job page on seed data, the dry-run report, table filters/search, inline edit, each preview type, and migration rollback.

Step list, continued (added 2026-10-09, D-113): step 5's migration and the hand-picked real-job import (`import_real_jobs.py`) put real `description`/`requirements`/`notes` and `job_files` rows in the database, but the job detail page (step 3) still shows seed data (`sampleJobDetail.ts`) for every application, real or synthetic — the real rows fall through to an empty fallback. Appended here rather than reopening steps 1-11, following D-104's pattern.

12. Backend: `GET /job-applications/{id}`, returning the full row (including `description`, `requirements`, `notes`) plus its `status_history` and `job_files` rows. 404 for an unknown id. Positioning fields (`fit`, `gaps`, `unclear`, `match_score`) are not computed here (D-48) — the endpoint returns what is actually stored, which for now means those stay null/empty for every row.
13. Frontend: `JobApplicationsPage.tsx` fetches the detail by id from the new endpoint instead of calling `sampleDetailFor`. `sampleJobDetail.ts` and the "seed data" comments in `types.ts`/`JobApplicationDetailPage.tsx` are retired once nothing depends on them.
14. Checks: `scripts/check.py` output; a screenshot of one of the 4 real imported applications' detail page showing its real description, requirements, notes, status history and files.

Step list, continued (added 2026-10-09, D-116): Preview, Upload, Open and Edit become real, and the Master CV selector becomes functional, for the Job Application page's Files, Job details, Positioning analysis and Application history sections. Appended here rather than reopening earlier steps, following D-104's pattern.

15. Migration 16: `job_applications.master_cv_profile_file_id` (references `profile_files(id)`, `ON DELETE SET NULL`), and manual positioning fields `fit`/`gaps`/`unclear` (JSON) and `strategy` (text). Tests: applies and rolls back, and the FK clears to null when the referenced profile file is deleted.
16. Backend: `PATCH /job-applications/{id}` (Job details, Application history and the manual positioning fields, partial — only the fields a request sends are written); `POST /job-applications/{id}/master-cv` (set or clear the reference, validated against `profile_files.kind = 'master_cv'`); `POST /job-applications/{id}/files/{kind}` (upload, keeps the file's own name rather than a content hash), `GET /job-applications/{id}/files/{file_id}/preview` and `POST /job-applications/{id}/files/{file_id}/open` (both reuse the Profile page's own logic, `file_preview.py` and `open_in_default_app`).
17. Frontend: Positioning analysis gains a Strategy field between the fit/gap row and Unclear. `FilePreview.tsx` gains the `{table: 'job_file', applicationId, id}` source case. Each file row in Files gets Preview and Open buttons (mirroring the Profile page's `FileRow`); each Files subsection's Upload button opens a file picker and calls the new upload endpoint. Job details, Positioning analysis and Application history's Edit buttons open an inline form for their section's fields and save through the new PATCH. The Master CV dropdown lists the Profile page's master CVs and calls the new selection endpoint.
18. Checks: `scripts/check.py` output; screenshots of a Preview, an Upload, an Edit save and a Master CV selection against the real imported applications.

Step list, continued (added 2026-10-09, D-117): Application history's Edit dialog can only edit notes/next action/due date, not the status timeline itself — real applications (especially the hand-imported ones) need their stage dates entered or corrected by hand. Appended here rather than reopening earlier steps, following D-104's pattern.

19. Backend: `PUT /job-applications/{id}/status-history`, replacing the application's entire `status_history` with at most one row per status and recomputing `status` as the furthest-reached main status (or the later end state). Rejects an empty entry list.
20. Frontend: Application history's Edit dialog gains a Stages section, one date field per status (five main plus Rejected/Withdrawn) with a Today button and a clear button, saved through the new endpoint alongside the existing notes/next action/due date PATCH.
21. Checks: `scripts/check.py` output; a screenshot of the Stages editor setting a date with Today and the timeline/status badge updating after save.

Step list, continued (added 2026-10-09, D-119 to D-123): the first of the job page's six
Generate/Revise (LLM) buttons (D-103/D-114) becomes real — Listing. Full contract in
`Agent/specs/job-llm-steps.md`. Job details, Positioning analysis and Application history follow
the same pattern in their own appended batches once this one is built and reviewed, matching how
every earlier continuation on this list was appended one reviewed batch at a time rather than
planned to code-level detail upfront. Tailored CV and Cover letter stay disabled (D-119) — Phase
5's own scope.

22. Add `trafilatura` and promote `httpx` from a dev dependency to a runtime one
    (`api/pyproject.toml`). Smoke-test outside the app: fetch a real job-posting URL and run the
    same extraction on a saved HTML fixture, confirm readable text comes out, not navigation or
    boilerplate.
23. Migration 17: add `sha256`, `extraction_status`, `extraction_message`, `extracted_text` to
    `job_files` (D-122), the same four columns `profile_files` already has. Tests: applies and
    rolls back on a copy of the dev database and an empty database.
24. Extraction code for a job file's own content, by kind: PDF (`pypdf`), DOCX (`python-docx`),
    HTML (the new readability extractor), TXT/MD (as-is). Writes the migration 17 columns.
    Synthetic PDF/HTML/DOCX/TXT job-listing fixtures under `tests/fixtures/synthetic/`.
25. Backend: a code-only extraction endpoint taking a URL, pasted text, or an uploaded file, and
    returning the extracted text plus how it was obtained (method, source, date) for the user to
    review and edit — no Claude call here. A blocked URL, a PDF with no text layer, or empty HTML
    returns a fallback reason instead of text, per Phase 4's already-decided fallback rule
    (CLAUDE.md, D-32).
26. `check_job_listing_text` Claude Job (job-llm-steps.md §1): submit function, renderer,
    on_result parsing the `LOOKS_LIKE_A_JOB_POSTING:` line, wired into a new `job_pipeline.py`
    (D-123). Tests with `FakeRunner`: a yes answer, a no answer, a malformed answer (treated as
    no, per the spec's fail-open rule).
27. `generate_job_listing` Claude Job (job-llm-steps.md §1): submit function, renderer built from
    the reviewed text, on_result storing the Markdown answer as `job_files` kind `listing` with
    its extraction columns filled directly from the generated text. Tests with `FakeRunner`.
28. Frontend: a Generate Listing overlay, following `ReviseOverlay`'s layout (current document on
    one side; on the other, this flow's own steps — pick a source (paste, URL, upload), review
    and edit the extracted text, see the sanity-check result if it came back `no`, then run
    generation with `RunTrace` showing it). Replaces the Listing subsection's disabled `LlmButton`
    stub in `JobApplicationDetailPage.tsx`.
29. Checks: `scripts/check.py` output; personal-data scan; screenshots of a URL, pasted text, and
    an uploaded PDF each producing a reviewed-then-generated listing, and of the sanity check
    firing on a deliberately bad fixture (a saved cookie-banner-only HTML page).

Done when
- [ ] The Job Application page, built on seed data, matches the D-56 layout (screenshot, compared against the job-detail mockups).
- [ ] The dry-run report matches the spreadsheet: row counts, the 8 changed rows, and three spot-checked rows.
- [ ] Running the import twice creates no duplicates.
- [ ] An edit survives an app restart.
- [ ] One `.docx`, one `.eml` and one `.msg` preview correctly. "Open in Word" works.
- [ ] Each status change writes a history row. "Last updated" matches the newest row, and the job page timeline shows the dates reached (screenshot).
- [ ] The table shows the D-46 columns, and the queue badge reflects the queue state.
- [ ] Migrations apply and roll back.
- [ ] A real Job Application's detail page shows its real description, requirements, notes, status history and files — not seed data (screenshot, D-113).
- [ ] A real job file previews, uploads, opens and is edited through the page, and a Master CV selection persists after a reload (screenshot, D-116).
- [ ] A stage date set with Today in the Edit dialog updates the timeline and the current status badge (screenshot, D-117).
- [ ] A Job Application gets a Listing file through Generate (LLM): a real URL, pasted text, and an uploaded PDF each produce extracted text the user reviews, then a generated Markdown listing (screenshot, D-119 to D-123).

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
- A new Job Application starts as Identified, and it queues one positioning Claude Job (D-49). The positioning output itself is built in Phase 5.
- Create `Agent/specs/intake-steps.md` (extraction rules per input type, and the Claude step contract).
- Candidate libraries, confirmed in this phase: `pypdf` (or PyMuPDF) for PDF, an HTML-to-text extractor such as `trafilatura`, and `python-docx` for DOCX.

Done when
- [ ] Raw text, one URL, one saved HTML page and one text-layer PDF each produce listing text, and you check the output.
- [ ] A scanned PDF and a JavaScript-only page each show the fallback message, not an empty listing.
- [ ] A blocked URL falls back to the saved-HTML or paste path.
- [ ] The extracted text can be edited before Claude runs.
- [ ] A hostile fixture ("ignore previous instructions...") changes nothing beyond the extracted fields.
- [ ] A repeat of an added listing is detected.
- [ ] Adding a listing creates its tracker row with status Identified and queues one positioning Claude Job, which the queue badge shows.
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
