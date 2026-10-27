<p align="center">
  <img src=".github/banner.svg" alt="LlmJobTracker — a local, single-user job-search tracker" width="900">
</p>

# LlmJobTracker

A local, single-user desktop app for a job search. It keeps a tracker, takes in job listings, and produces the positioning, tailored CV and cover letter for each application. You review and approve every result. Nothing is sent or saved as final without you.

Status: Phase 1 (skeleton) in progress. The API, the web app, the database and a Jobs table run with synthetic data.

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
