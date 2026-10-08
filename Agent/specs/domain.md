# Domain: Job Application, status history, and the positioning requirement

Phase 3. Entities for the tracker itself. Profile entities are `profile-steps.md`'s; Claude Jobs
and their prompts are `claude_jobs`/`claude_job_prompts` (Phase 2, D-59); this file does not
repeat either.

## Job Application

One tracker row for one listing (D-46, D-56). Table `job_applications`.

- `company`, `role_title`: required text.
- `lane`: free text, set by the positioning strategy (O-12) or left blank until it is.
- `location`: free text (D-53). A Job Application's own suggestion-and-confirm flow is Phase 4.
- `work_mode`: Onsite, Hybrid, Remote, Unknown (D-54).
- `contract_type`: Full-Time, Part-Time, Contract/Short Term, Other, Unknown (D-54).
- `portal_name`, `portal_url`: the application source (D-55). `portal_url` may be null — some
  portals (LinkedIn Easy Apply, a recruiter's own site) give no stable public URL.
- `status`: Identified, Applied, Screening, Interview, Offer, Rejected, Withdrawn (D-44, D-101).
- `match_score`: the fit % (D-47), null until positioning has run (Phase 5).
- `description`: prose, what the role is and its context. Written by whoever adds the listing —
  Claude, from the listing text, once Phase 4 exists; by hand for anything added before that.
  Never invented from nothing: if there is no listing text to summarise, this stays null (D-85's
  rule against unsupported claims applies here too, even though a job description is not a claim
  about the user).
- `requirements`: a JSON array of short strings, stored in one `TEXT` column (same shallow
  shape `profile_outputs.input_sha256s` already uses for a list, not a separate table — D-99
  already decided the richer per-requirement weight/match detail lives in the positioning
  breakdown document, not a structured table, and a plain requirements list does not need one
  either).
- `notes`: free text, the user's own, never generated.
- `next_action`, `due_date`: free text / date, edited on the Job Application page (D-56).

## Status history

Table `status_history` (D-45). One row per change: `job_application_id`, `status`, `changed_at`.
"Last updated" is the newest row's date. Only a forward move in the D-44 order counts as
progress; a backward move or a correction is still recorded as a row, just not as progress. A
Job Application can have more than one row for the same status (a correction), and the history
is never edited in place, only appended to.

## Requirement (positioning, Phase 5)

Not a table. Per D-99, the per-requirement breakdown (weight 0–10, match 0–10, reasoning) lives
in the positioning breakdown document — a file (`files.md`), read as prose, not queried as rows.
`match_score` is the one number code computes from that document's table (D-47) and stores on
the Job Application itself. The page's `fit`/`gaps`/`unclear` bullets (D-98, D-102) are part of
that same document's prose, not separate columns.
