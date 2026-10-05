# LocalJobTracker

A local, single-user desktop app for a job search. It keeps a tracker, takes in job listings, and produces the positioning, tailored CV and cover letter for each application. You review and approve every result. Nothing is sent or saved as final without you.

Status: planning. No product code yet.

## Where to start

- `CLAUDE.md`: rules and working style for the people and tools building the app.
- `DEVELOPMENT-PLAN.md`: phases, and the one that is current.
- `DECISIONS.md`: what has been decided, and what is still open.

## Layout

- `Agent/`: skills, default rules and specs that the in-app Claude uses.
- `planning/`: Stitch mockups and notes for building the UI.

Personal data is never stored in this repo. It lives under `%LOCALAPPDATA%\LocalJobTracker\`.
