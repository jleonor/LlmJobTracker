# Domain: Job Application, status history, and the positioning requirement

Phase 3. Entities for the tracker itself. Profile entities are `profile-steps.md`'s; Claude Jobs
and their prompts are `claude_jobs`/`claude_job_prompts` (Phase 2, D-59); this file does not
repeat either.

## Job Application

One tracker row for one listing (D-46, D-56). Table `job_applications`.

- `company`, `role_title`: required text.
- `lane`: free text, set by the positioning strategy (O-12) or left blank until it is. Manually
  editable through Job details' Edit dialog (D-178), the same as the rest of that section's
  fields — the strategy's own suggestion is a starting point, not the only way it can be set.
- `location`: free text (D-53). A Job Application's own suggestion-and-confirm flow is Phase 4.
- `work_mode`: Onsite, Hybrid, Remote, Unknown (D-54).
- `contract_type`: Full-Time, Part-Time, Contract/Short Term, Other, Unknown (D-54).
- `portal_name`, `portal_url`: the application source (D-55). `portal_url` may be null — some
  portals (LinkedIn Easy Apply, a recruiter's own site) give no stable public URL.
- `status`: Identified, Applied, Screening, Interview, Offer, Rejected, Withdrawn (D-44, D-101).
- `match_score`: the fit % (D-47), null until positioning has run (Phase 5).
- `description`: prose, what the role is and its context. Written by the Job details Generate
  (LLM) step, from the listing file's extracted text (`job-llm-steps.md`), once that step exists;
  by hand for anything added before that, or when there is no listing file to read. Never
  invented from nothing: if there is no listing text to summarise, this stays null (D-85's rule
  against unsupported claims applies here too, even though a job description is not a claim about
  the user).
- `requirements`: a JSON array of short strings, stored in one `TEXT` column (same shallow
  shape `profile_outputs.input_sha256s` already uses for a list, not a separate table — D-99
  already decided the richer per-requirement weight/match detail lives in the positioning
  breakdown document, not a structured table, and a plain requirements list does not need one
  either).
- `notes`: free text. Previously the user's own, never generated (D-127); superseded by D-177 —
  Application history's Generate/Revise (LLM) now writes it too, a readable record of the
  application's status history plus whatever the filed emails add, the same replace-in-slot
  convention every other generated field in this app uses. Still manually editable through
  Application history's Edit dialog at any time.
- `next_action`, `due_date`: free text / date, edited on the Job Application page (D-56).
- `master_cv_profile_file_id`: nullable, references `profile_files(id)` ON DELETE SET NULL
  (D-116). Which Profile page master CV this application uses — a reference, not a copied file:
  no bytes are duplicated, and the master CV is previewed and opened from the Profile page, not
  here. Deleting the referenced profile file clears this back to null rather than touching the
  Job Application itself.
- `fit`, `gaps`, `unclear`: JSON arrays of short strings, same shallow shape as `requirements`.
  `strategy`: free text. Manually editable through Positioning analysis's Edit button (D-116) —
  this supersedes the Requirement section below, which had these three living only in the
  positioning breakdown document's prose. They start empty/null and are filled in by hand until
  Phase 5's Revise/Generate (LLM) buttons compute them for real.

## Status history

Table `status_history` (D-45). One row per change: `job_application_id`, `status`, `changed_at`.
"Last updated" is the newest row's date. Only a forward move in the D-44 order counts as
progress; a backward move or a correction is still recorded as a row, just not as progress. A
Job Application can have more than one row for the same status (a correction), and the history
is never edited in place, only appended to — except through Application history's stage editor
(D-117), which replaces the whole table for one application with at most one row per status, a
narrower editing model purpose-built for backfilling real dates by hand. The application's
current `status` is recomputed from the furthest-reached main status (or the later end state)
whenever the editor saves.

## Requirement (positioning, Phase 5)

Not a table. Per D-99, the per-requirement breakdown (weight 0–10, match 0–10, reasoning) lives
in the positioning breakdown document — a file (`files.md`), read as prose, not queried as rows.
`match_score` is the one number code computes from that document's table (D-47) and stores on
the Job Application itself, and stays code-computed, not manually edited (D-47, D-116). The
page's `fit`/`gaps`/`strategy`/`unclear` fields are now columns on `job_applications` itself
(D-116, superseding this file's original "part of that same document's prose" description),
manually editable until Phase 5 computes them for real.
