# LocalJobTracker: Decisions

Append-only. Each entry has a date and a status:
- **Accepted**: decided by the user.
- **Proposed**: recommended by Claude, not yet confirmed. Confirm or change it before the phase that depends on it.
- **Open**: not decided yet. Listed at the bottom.

To change a decision, add a new entry that supersedes the old one. Don't edit the old entry.

## Product and scope

| ID | Date | Status | Decision | Reason |
|---|---|---|---|---|
| D-01 | 2026-10-05 | Accepted | Local, single-user app. No hosted deployment. | Personal data, one user. |
| D-02 | 2026-10-05 | Accepted | Tracker first, as a table. Kanban board deferred to Phase 8 or later. | The user wants tabular for now. |
| D-03 | 2026-10-05 | Accepted | No command palette and no keyboard shortcuts in v1. | Simpler UI. |
| D-04 | 2026-10-05 | Accepted | Mockup extras are dropped: the four sub-scores, auto-triage, Fast Track, voice input, avatar, and placeholder model labels. | Not part of the workflow. |
| D-05 | 2026-10-05 | Accepted | Tracker status values come from the spreadsheet. "Identified" is folded into "Not Started", and the import dry run lists the 8 affected rows. | Matches the user's own tracker. |
| D-06 | 2026-10-05 | Accepted | Starting master CVs are English and French. More masters can be added later without a schema change. | Current masters are EN and FR. |
| D-07 | 2026-10-05 | Accepted | Profile onboarding uses all uploaded CVs, letters and the questionnaire. Each fact carries a source and a date. | Reference material is useful as evidence. |
| D-08 | 2026-10-05 | Proposed | When sources conflict, the master CVs win and the conflict is shown to the user. | Older archive files predate the 2024 career pivot and may hold superseded claims. |
| D-09 | 2026-10-05 | Accepted | Every fact must be verified before a generated document may use it. | Honest documents. Applies to the app's output, not to this coding work. |
| D-10 | 2026-10-05 | Superseded by D-47 | Positioning produces per-requirement evidence and one composite score, reviewed by the user. The formal rubric and calibration phase are dropped. | Simpler. The user's judgment is the check. |
| D-11 | 2026-10-05 | Superseded by D-48 | Only one status field. Progress through the process is shown by which documents exist. | Removes the separate pipeline stage. |
| D-12 | 2026-10-05 | Proposed | The app fetches listing URLs. Claude receives the text and structures it with no tools. If the fetch fails, the user pastes the text. | Untrusted pages never reach a tool-enabled prompt. |
| D-13 | 2026-10-05 | Proposed | Clarifying questions in positioning are answered in the job record first. Reuse across jobs comes in Phase 7. | Keeps Phase 5 small. |
| D-14 | 2026-10-05 | Proposed | "Apply with AI" (browser assist) is parked. Revisit only a narrower, read-only version after Phase 8. | Conflicts with the form-filling non-goal. |
| D-32 | 2026-10-05 | Proposed | Job intake accepts four inputs: raw text, a URL, a saved HTML page, and a PDF. `.txt` and `.docx` are also accepted. Code extracts the text (the app fetches URLs), the user reviews it, and then Claude structures it with no tools. Supersedes D-12. | The user wants the job text to come from any of these sources. Extraction is deterministic, so it needs no model and no tool access. |

## Architecture and runtime

| ID | Date | Status | Decision | Reason |
|---|---|---|---|---|
| D-15 | 2026-10-05 | Accepted | Backend: Python 3.12, FastAPI on 127.0.0.1, per-launch token. Managed with `uv`. | Local, testable API. |
| D-16 | 2026-10-05 | Accepted | UI: React, TypeScript, Vite, Tailwind v4, shadcn/ui. Not Next.js. | No server rendering is needed in a desktop app. |
| D-17 | 2026-10-05 | Accepted | Desktop shell: Electron, added in Phase 8. Browser development until then. | The shell can wait until the workflow works. |
| D-18 | 2026-10-05 | Accepted | Data: SQLite under `%LOCALAPPDATA%\LocalJobTracker\`, outside OneDrive. | Avoids sync corruption. |
| D-19 | 2026-10-05 | Accepted | Agent runtime: headless Claude Code behind a `Runner` interface, billed through the Claude Pro login in the CLI. No API key. | Decided in the Phase 0 spike. |
| D-20 | 2026-10-05 | Accepted | Nothing Claude-Code-specific appears outside `ClaudeCodeRunner`. | Keeps the runner swappable for a later managed loop. |
| D-21 | 2026-10-05 | Accepted | `.docx` preview without Word automation. Candidate `dxpdf`, with LibreOffice as fallback. `docx2pdf` is not used because it drives Microsoft Word. | Word COM was rejected on 2026-10-05. |
| D-22 | 2026-10-05 | Proposed | Cloud policy: profile data and job data go to Anthropic through Claude Code. v1 has no local-only path. | Claude Code sends prompts to Anthropic, so a local option would need a different model. The user must confirm. |
| D-23 | 2026-10-05 | Proposed | Files the user uploads (CVs, letters, questionnaire, their own rules) and everything derived from them (including any FAISS index) live in app data. The repo's `Agent/` folder holds only generic defaults, skills and specs. | Personal data never goes into the repo. The FAISS index is built from personal answers. |
| D-24 | 2026-10-05 | Proposed | `Agent/skills/` holds the in-app tools. The repo's `.claude/` folder is for coding sessions only. | Two audiences: the app's runner and the people building it. |
| D-25 | 2026-10-05 | Proposed | Q&A reuse starts as SQLite keyword search. FAISS is added only if keyword search misses real questions. | A few hundred rows do not need a vector index. |
| D-26 | 2026-10-05 | Proposed | Job listings and emails are untrusted text. Steps that read them get no tools, and any tool access is limited to the job's folder. | Prompt injection. |

## Repo and process

| ID | Date | Status | Decision | Reason |
|---|---|---|---|---|
| D-27 | 2026-10-05 | Accepted | Reference folder is read-only. Personal data never enters the repo, tests or logs. | The user's standing rule. |
| D-28 | 2026-10-05 | Accepted | Commits only when the user asks, and only locally. Never push. | The user's standing rule. |
| D-29 | 2026-10-05 | Accepted | Phase order follows `DEVELOPMENT-PLAN.md`. Each phase's step list is approved before code. | Keeps work reviewable. |
| D-30 | 2026-10-05 | Accepted | The new repo's `CLAUDE.md`, `DECISIONS.md`, `DEVELOPMENT-PLAN.md` and `README.md` replace the old plan set. The old set stays in `archive/`, which is gitignored. | One short set of documents for Claude to read. |
| D-31 | 2026-10-05 | Accepted | No `docs/` folder. Specs go to `Agent/specs/`, and build notes go to `planning/`. | The user's preference. |
| D-33 | 2026-10-05 | Accepted | Each phase is built on its own git branch (for example `phase-0-setup`), cut from `main`. Commits stay local, and the user pushes. | The user's preference. Extends D-28. |
| D-34 | 2026-10-05 | Accepted | Profile data and job data go to Anthropic through the Claude Code CLI. There is no local-only path in v1. This confirms D-22. | The user knows this and accepts it. |
| D-35 | 2026-10-05 | Accepted | The `planning/` folder stays out of git. Its gitignore entry remains. This resolves O-02. | The user's decision. |
| D-36 | 2026-10-05 | Accepted | The Talent Pools sheet is not imported in v1. This resolves O-04. | The user's decision. |
| D-37 | 2026-10-05 | Proposed | Conflicts between sources are shown to the user. A generated `FULL_CV_HISTORY` file becomes a main input and is expected to resolve conflicts better than the master CVs. The exact rule (which source wins, and when `FULL_CV_HISTORY` is produced) is still to be settled. This supersedes D-08 once settled. | The user's view. The master CVs are no longer the automatic winner. |
| D-38 | 2026-10-05 | Proposed | Email files keep the no-tools rule from D-26, but the reason is narrowed. The concern is hostile text inside a saved email (phishing, spam, forwarded junk) steering a proposal. It is not about whether the user downloaded the file. Every proposal still needs Confirm (Phase 6). This narrows D-26. | The user downloads emails. Their saved copies can still contain injected text. |
| D-39 | 2026-10-05 | Accepted | "Local" in the app name means the app runs and stores data on the user's machine: the backend on 127.0.0.1, SQLite and the managed files under `%LOCALAPPDATA%`. The only outbound traffic is the model calls made through the Claude Code CLI. A local LLM may replace this later, and a proof of concept with Claude Code comes first. This clarifies D-34. | The user's explanation of the name. |
| D-40 | 2026-10-05 | Accepted | `FULL_CV_HISTORY` is generated by the app once all CVs are uploaded. It is the main input for resolving conflicts between sources, and it is expected to do this more completely than the master CVs. The master CVs are templates for layout and wording. This supersedes D-08 and D-37. | The user's decision. |
| D-41 | 2026-10-05 | Accepted | Job intake accepts four inputs: raw text, a URL, a saved HTML page, and a PDF. `.txt` and `.docx` are also accepted. Code extracts the text, the user reviews it, and then Claude structures it with no tools. This confirms D-32. | The user's decision. |
| D-42 | 2026-10-05 | Accepted | Code folders are named `api/` (FastAPI backend) and `web/` (React front end), not `backend/` and `frontend/`. | Short names that match each folder's role. `web/` stays accurate when Phase 8 wraps the same front end in Electron. |
| D-43 | 2026-10-05 | Accepted | The browser never holds the launch token. The Vite dev server proxies `/api` to the API and adds the `X-Launch-Token` header on the server side. `scripts/dev.py` creates one token per launch and gives it to both processes. In Phase 8 the Electron main process will do the same job. | Keeps the token out of page scripts and out of the browser's network log. Needs no login screen. |
| D-60 | 2026-10-06 | Accepted | When a phase is done, its branch is merged into local `main` with a fast-forward merge. Nothing is pushed until the whole project is done, and the user pushes. Phase branches are kept after merging, for history. This extends D-33. | The user's decision. Keeps everything local for now. |

## Product model (2026-10-06)

Written from the user's answers on 2026-10-06. The full picture for the phase specs is in `planning/product-model.md`.

| ID | Date | Status | Decision | Reason |
|---|---|---|---|---|
| D-44 | 2026-10-06 | Accepted | Status values, in order: Not Started, Applied, Screening, Interview, Offer. Rejected and Withdrawn are end states. Screening covers every step between an application and an interview, such as a test or an assessment. This extends D-05. | The user's own process. "Screening" is the step many companies add. |
| D-45 | 2026-10-06 | Accepted | Every status change is stored as a history row with its date and time. "Last updated" is the newest row's date. Only a forward move in the D-44 order counts as progress. Backward moves and corrections are recorded, but they do not count as progress. | The job page shows the date each status was reached. |
| D-46 | 2026-10-06 | Accepted | Table columns: Company, Title, Lane, Location, Status, Last updated, Match score, and a queue badge (idle, queued or processing). Next action and Due leave the table only. | The columns the user scans to decide on a job. |
| D-47 | 2026-10-06 | Accepted | The match score is a percentage, computed in code. Claude gives each requirement a weight w (0 to 10) and a match m (0 to 10), with evidence for m. Fit % = Σ(w × m) ÷ (10 × Σw) × 100. Claude does not produce the percentage. This supersedes D-10. | The result is reproducible and can be checked by hand. |
| D-48 | 2026-10-06 | Accepted | Progress is shown by status (D-44, D-45), not by which documents exist. The job page flags what is not done yet: positioning analysis, tailored CV, cover letter. This supersedes D-11. | The user's preference. The flags cover the gap that a status alone does not show. |
| D-49 | 2026-10-06 | Accepted | Two kinds of job. A Job Application is one tracker row per listing. A Claude Job is one queued unit of Claude work, made of an ordered list of prompts. Every Job Application gets at least one Claude Job, the positioning analysis, when it is added. | The user's terms. Avoids confusing a listing with a unit of work. |
| D-50 | 2026-10-06 | Accepted | Claude Jobs run one at a time, in the order they were created. All prompts of one Claude Job finish before the next Claude Job starts. | A finished job is more useful than requests from several jobs mixed together. Keeps the plan's limit easier to reason about. |
| D-51 | 2026-10-06 | Proposed | The queue is an app module between the app and the `Runner`. It is not part of `ClaudeCodeRunner`. The runner only reports a rate-limit error. The queue pauses on that error. | Consistent with D-20. The seam stays clean. |
| D-52 | 2026-10-06 | Proposed | The Claude Job queue is built in Phase 2, the first phase with several model calls in a row. | Onboarding needs ordered calls. Phase 1 only has one button. |
| D-53 | 2026-10-06 | Accepted | Location is free text. When a Job Application is added, Claude suggests an existing city value that matches. The user confirms the suggestion before it is saved. | The user's rule. Nothing changes in the tracker without approval. |
| D-54 | 2026-10-06 | Accepted | Work mode: Onsite, Hybrid, Remote, Unknown. Contract type: Full-Time, Part-Time, Contract/Short Term, Other, Unknown. | The user's fixed lists. |
| D-55 | 2026-10-06 | Accepted | Portal: the name, plus the URL when there is one. The URL is stored as text and is not fetched by the app. An application by email has the portal "Email". Some URLs, such as LinkedIn postings, may not be readable by Claude. | The user's description. Listing text is untrusted (D-26). |
| D-56 | 2026-10-06 | Accepted | Job Application page, in order: header (title, company); job details (portal, description, requirements, location, work mode, contract type); application history (status timeline with achieved and greyed-out statuses, notes, next action, due date); positioning analysis (fit, gaps, strategy, match score); files. The "not done yet" flags from D-48 sit at the top. | The user's layout. |
| D-57 | 2026-10-06 | Accepted | Files on a Job Application: the master CV is proposed by Claude when the listing is added, and the user can change it. Tailored CV and cover letter each have a button to write one. Email history lists previews by title, and clicking one expands it. | The user's workflow. |
| D-58 | 2026-10-06 | Accepted | The Profile page shows the old CVs, old cover letters, master CVs, the questionnaire, the questionnaire report, and the positioning strategy, which outlines the lanes. | The user's layout. The strategy output from Phase 2 is the source of the lanes. |
| D-59 | 2026-10-06 | Proposed | Two kinds of job get two names in the code and the UI. A tracker row is a Job Application: table `job_applications`, route `/job-applications`, model `JobApplication`, and the page heading "Job Applications". A queued unit of work is a Claude Job: table `claude_jobs` (Phase 2), route `/claude-jobs`, model `ClaudeJob`. A Claude Job links to one Job Application, or to none (for example preparing the profile). The queue badge reads "Claude: queued", not "job". The old `jobs` table is renamed in migration 2. | The user asked for the distinction. Renaming while the tables hold synthetic data only is cheap. |

## Open

| ID | Question | Recommendation |
|---|---|---|
| O-01 | Which embedding model supports FAISS, given that Claude has no embeddings API? A local model keeps data on the machine. A cloud model would send personal answers out. | Decide before Phase 7. Local is preferred. |
| O-03 | Is the GitHub repo private? | Yes. |
| O-08 | Does `FULL_CV_HISTORY` need its own spec (fields, how conflicts are recorded, and what the user reviews)? | Write it in `Agent/specs/profile-steps.md` during Phase 2. |
| O-09 | When the plan limit is hit, should the queue pause and wait for a Resume click, or retry by itself after a delay? | Pause and show it, with a Resume button. Automatic retry needs to know the limit's reset time, which the CLI may not report. Decide before the Phase 2 step list. |
| O-10 | Should queued Claude Jobs survive an app restart? | Yes. Store them in SQLite. |
| O-11 | After Offer, which end states do you need besides Rejected and Withdrawn (for example Accepted or Declined)? | Ask the user. |
| O-12 | Where do lanes come from: the questionnaire analysis, the positioning strategy, or manual entry? | The strategy output defines them in Phase 2. The user edits them. |
| O-13 | Should the user see and edit the per-requirement weights and matches, or only the final %? | Show them with their evidence. Read-only in v1. |
| O-14 | Which master CV is proposed for a listing: the one matching the listing's language (EN or FR), or one chosen from the content? | Language first, then content. |
