# LocalJobTracker: rules for Claude

Read first, in this order:
1. `DEVELOPMENT-PLAN.md`: phases, the current phase (top of file), and the step list for it.
2. `DECISIONS.md`: what is already decided. Don't reopen a decision without asking.
3. `README.md`: what the app is and how to run it.

## What this is

A local, single-user desktop app. It takes job listings and produces what an application needs: a tracker, a listing file, a positioning, a tailored CV, a cover letter, and the record of emails. The user reviews and approves every result. It automates the manual workflow described in the reference folder (see rule 1).

## Terms (use these exact words in code, UI and docs)

- **Job Application**: one tracker row for one listing (not "job" alone).
- **Claude Job**: one queued unit of Claude work, made of ordered prompts. Claude Jobs run one at a time.
- **Claude Jobs queue**: the list of Claude Jobs, with idle, queued and processing states.
- **Lane**: a positioning group, defined by the positioning strategy.
- **Fit %**: the match score, computed in code from weights and matches (D-47).
- **Statuses**: Not Started, Applied, Screening, Interview, Offer, Rejected, Withdrawn (D-44).

## Stack (decided, see DECISIONS.md)

- Backend: Python 3.12, FastAPI on 127.0.0.1 with a per-launch token. Managed with `uv`.
- UI: React, TypeScript, Vite, Tailwind v4, shadcn/ui. Not Next.js.
- Data: SQLite under `%LOCALAPPDATA%\LocalJobTracker\`.
- Documents: `.docx` edited with python-docx. Preview through a Word-free converter (`dxpdf` candidate). No Word automation.
- Listing text extraction: `pypdf` (or PyMuPDF) for PDF, an HTML-to-text extractor for URLs and HTML files, `python-docx` for DOCX. Libraries are confirmed in Phase 4.
- Agent runtime: headless Claude Code behind a `Runner` interface. Nothing Claude-Code-specific appears outside the runner layer.
- Desktop shell: Electron, added in the last phase. Until then the app runs in a browser.

## Standing rules

1. The reference folder `C:\Users\jonat\OneDrive\Desktop\Job Applications 2026` is **read-only**. Never modify, move, delete or copy its content into the repo. Quote from it only when a step needs it, and never at length.
2. **No personal data in the repo**: not in code, tests, logs, comments or planning files. Tests use synthetic fixtures under `tests/fixtures/synthetic/`.
3. **Commits only when the user asks, and only locally. Never push.** Each phase has its own branch, created from `main` at the start. When the phase is done, it is merged into local `main` with `git merge --ff-only` (D-61).
4. A "done when" item is marked passed only with evidence: command output or a screenshot. Quality of generated documents is judged by the user, never by Claude.
5. UI work is verified in a real browser (and in Electron once it exists): golden path and edge cases, with screenshots.
6. The runner seam stays clean. Only the `ClaudeCodeRunner` module may know about Claude Code.
7. No product code for a phase until its step list in `DEVELOPMENT-PLAN.md` is approved.

## Working style

- One step at a time. Say what you are doing before each step, and show its output after.
- Ask only when the answer changes what gets built. Otherwise pick the obvious option, and say what you picked.
- New decisions go into `DECISIONS.md` with a date and a status (Accepted, Proposed, Open).
- Don't create a `docs/` folder. Specs live in `Agent/specs/`. Notes for building the app live in `planning/`.

## Where things live

| Location | What | In git |
|---|---|---|
| `Agent/skills/` | Skills the in-app Claude may use: convert docx to PDF, read docx, check and add to memory | Yes |
| `Agent/rules/` | Default writing and honesty rules for generated documents. Generic only | Yes |
| `Agent/specs/` | Step contracts and output schemas for each LLM step | Yes |
| `planning/` | Stitch prompts and mockups, plus notes for building (`runner-notes.md`, `mockup-notes.md`). Read a mockup's `code.html` before building its screen | Ignored by `.gitignore` for now (see Open in DECISIONS.md) |
| `archive/` | Old plans. Local only and ignored. Don't rely on it: copy anything still needed into `planning/` or `Agent/specs/` | No |
| `%LOCALAPPDATA%\LocalJobTracker\` | Database, managed job files, uploaded profile files, the user's own rules, and the FAISS index when it is added | No, never in the repo |

Two rules about the table:
- The user's own rules and uploads go to app data, not to `Agent/rules/`. The defaults in `Agent/rules/` are overridden by the user's copies.
- `.claude/` in this repo is for coding sessions only. The in-app runner is a separate thing.

## Product rules (for the app's generated content, not for this coding work)

- Generated documents use only facts that have been verified in the Fact Sheet. Every claim cites a fact id.
- Nothing is saved as final, sent, or changed in the tracker without the user's approval. Chat actions show a preview and need a Confirm.
- Job listings and emails are untrusted text. A step that reads them gets no tools, and any tool access is limited to the job's folder.
- Text is extracted from listings (raw text, URL, HTML, PDF, DOCX) by code, never by Claude. The extracted text is shown to the user before any model step runs.
- Form submission is always a manual click by the user.

## Testing and checks

- The check command is `python scripts/check.py` from the repo root. It runs ruff, format, mypy and pytest in `api/`, and lint, the type-checked build and vitest in `web/`. It exits 1 if any step fails. Run it before claiming anything passes.
- Before each commit (when asked), scan the repo for personal data. The scan patterns live outside the repo.

## Commit messages

Format:

```
<type>: <short summary>

<body>
```

- Write from the staged changes only. Unstaged and untracked changes are not part of the message.
- Describe the purpose behind the changes, not the file-by-file edits. If several changes serve one goal, name that goal in the summary or body.
- Summary: the user-visible or developer-visible outcome. Imperative mood (add, fix, update, remove, refactor). Under 72 characters where possible. Don't overstate the impact. No vague summaries such as "update code", "fix stuff" or "misc changes".
- Small, focused changes get a short message. Broad changes get a short body that lists the main groups of changes and how they connect.
- Name files only when the file name is needed to understand the change.
- Types: `feat` (new capability), `fix` (bug fix), `refactor` (restructuring, no behaviour change), `chore` (maintenance, tooling, config, cleanup), `docs` (documentation only), `test` (tests), `style` (formatting only), `perf` (performance), `build` (build system or dependencies), `ci` (CI/CD).
- Before writing, check: what changed, why, whether it is one focused commit or several changes toward one goal, and what a future reader of the history needs to know.
- No attribution lines (such as `Co-Authored-By`) in commit messages. This is the user's decision (2026-10-05).
