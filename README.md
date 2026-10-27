<p align="center">
  <img src=".github/banner.svg" alt="LlmJobTracker — a local, single-user job-search tracker" width="900">
</p>

# LlmJobTracker

## Overview

LlmJobTracker is a local, single-user desktop app for a job search. It takes in job listings and produces what an application needs: a tracker row, a listing file, a positioning analysis, a tailored CV, a cover letter, and the record of status changes — automating the manual, file-by-file workflow it replaces.

Every generated document is reviewed and approved by you before it is saved as final, sent, or changed in the tracker. Generated content uses only what your own career history, questionnaire analysis and strategy documents say; nothing is invented or embellished.

The app runs on your machine: the backend binds to 127.0.0.1, data lives in a local SQLite database under `%LOCALAPPDATA%\LlmJobTracker\`, and every generation step runs through a headless LLM CLI (Claude Code or Codex) behind a swappable `Runner` interface. The only traffic that leaves your machine is that CLI's own call to its provider.

Status: Phase 15 (Packaging and installers) in progress. Phases 0 through 14 are done — the tracker, profile onboarding, job intake, multi-LLM support, lanes, the dashboard, Open Applications, additional profile files and the Electron shell all run end to end against real data.

## Key features

- **Track job applications** — a tracker table (Company, Title, Lane, Location, Status, Last updated, Fit %, LLM queue badge) with full status history, inline editing, file previews, and a configurable column/view system, alongside a lighter Open Applications table for talent pools and cold outreach.
- **LLM analysis of your profile** — upload your CVs, cover letters and questionnaire once; an LLM turns them into a reviewed career history, questionnaire analysis and positioning strategy that every later document is grounded in.
- **LLM-assisted job-posting creation** — give it raw text, a URL, a saved HTML page or a PDF; the app extracts the text for you to review first, then an LLM turns the reviewed text into a clean, structured listing document.
- **Listing analysis, tailored CV and cover letter** — an LLM scores each requirement against your career history (the Fit % itself is computed in code from those scores, never guessed by the model), then writes a tailored CV and cover letter from your master CV and cover letter template as a set of tracked, reviewable edits.
- **Dashboard with lane analysis** — slicer-driven charts, a calendar heatmap, and per-lane strengths/weaknesses, with Active/Cold application tracking measured against a date you control.

## Running in development

Prerequisites: Python 3.12 with `uv`, and Node.js.

Start the app with one command from the repo root:

```powershell
.\run.ps1
```

If PowerShell blocks the script, use `powershell -ExecutionPolicy Bypass -File .\run.ps1`. The script installs missing dependencies, starts the API on 127.0.0.1:8765 and the web app on http://127.0.0.1:5173/, and opens the browser. Press Ctrl+C in that window to stop both.

Under the hood, `scripts/dev.py` starts both servers with one launch token. The browser never sees the token: the dev server adds it to each `/api` request.

To run with the synthetic jobs, use `-Seed`. The jobs go to a separate folder, `%LOCALAPPDATA%\LlmJobTracker-dev`, so the real app database stays untouched:

```powershell
.\run.ps1 -Seed
```

Without `-Seed`, the app uses `%LOCALAPPDATA%\LlmJobTracker`.

Checks: `python scripts/check.py` runs lint, format, types and tests for both halves.

## Where to start

- `CLAUDE.md`: rules and working style for the people and tools building the app.
- `DEVELOPMENT-PLAN.md`: phases, and the one that is current.
- `DECISIONS.md`: what has been decided, and what is still open.

## Layout

- `Agent/`: skills, default rules and specs that the in-app Claude uses.
- `planning/`: Stitch mockups and notes for building the UI.

Personal data is never stored in this repo. It lives under `%LOCALAPPDATA%\LlmJobTracker\`.
