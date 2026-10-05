# LocalJobTracker

A local, single-user desktop app for a job search. It keeps a tracker, takes in job listings, and produces the positioning, tailored CV and cover letter for each application. You review and approve every result. Nothing is sent or saved as final without you.

Status: Phase 1 (skeleton) in progress. The API, the web app, the database and a Jobs table run with synthetic data.

## Running in development

Prerequisites: Python 3.12 with `uv`, and Node.js.

```powershell
cd api; uv sync; cd ..
cd web; npm install; cd ..
python scripts/dev.py
```

Then open http://127.0.0.1:5173/. `dev.py` starts the API on 127.0.0.1:8765 and the web dev server with one launch token. The browser never sees the token: the dev server adds it to each `/api` request. Press Ctrl+C to stop both.

To load the synthetic jobs, use a separate data folder so they stay out of the real app database. Set the same folder before starting `dev.py`:

```powershell
$env:LJT_DATA_DIR = "$env:LOCALAPPDATA\LocalJobTracker-dev"
cd api; uv run python -m localjobtracker.seed; cd ..
python scripts/dev.py
```

Without `LJT_DATA_DIR`, the app uses `%LOCALAPPDATA%\LocalJobTracker`.

Checks: `python scripts/check.py` runs lint, format, types and tests for both halves.

## Where to start

- `CLAUDE.md`: rules and working style for the people and tools building the app.
- `DEVELOPMENT-PLAN.md`: phases, and the one that is current.
- `DECISIONS.md`: what has been decided, and what is still open.

## Layout

- `Agent/`: skills, default rules and specs that the in-app Claude uses.
- `planning/`: Stitch mockups and notes for building the UI.

Personal data is never stored in this repo. It lives under `%LOCALAPPDATA%\LocalJobTracker\`.
