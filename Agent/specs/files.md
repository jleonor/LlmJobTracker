# Files: a Job Application's managed folder and the file-links table

Phase 3. Profile files are `profile_files` (Phase 2); this is the equivalent for a Job
Application's own files — the listing, CVs, cover letters, the positioning breakdown document,
and filed emails.

## Managed folder layout

    %LOCALAPPDATA%\LocalJobTracker\files\<company>\<role_title>\<name>

`<company>` and `<role_title>` are the Job Application's own fields, sanitised for the
filesystem: each of `< > : " / \ | ? *` becomes `_`, and the result is trimmed of trailing dots
and spaces (Windows rejects both). Two Job Applications for the same company and role would
collide; Phase 4's duplicate check (by URL and content hash) is what keeps that from happening
in practice, not a folder-naming scheme.

`<name>` is the file's own display name (`job_files.name`) exactly as stored — the folder holds
real, openable files with readable names ("F1 Data Scientist - Job Listing.pdf"), the same way
the reference folder this app automates does, not generated ids.

## `job_files` table

One row per file. Columns:

- `id`: primary key.
- `job_application_id`: references `job_applications(id) ON DELETE CASCADE`.
- `kind`: `listing`, `master_cv`, `tailored_cv`, `cover_letter`, `positioning_breakdown`, `eml`,
  `msg`, or `other` — the same kinds the Job Application page already groups files by (D-115's
  Files section: Master CV selector, Listing, Tailored CV, Cover letter, Emails, Additional files
  catch-all) and filters emails out of (`eml`/`msg`, D-111/D-112/D-115). `other` covers anything
  not yet given its own kind.
- `name`: the display name, matching the frontend's `JobApplicationFile.name` (D-111's Emails
  column strips a trailing `.eml`/`.msg` for display; the stored name keeps it).
- `stored_path`: the file's path under the managed folder above, relative to
  `%LOCALAPPDATA%\LocalJobTracker\files\` (not absolute — the data directory itself can move,
  D-21's `LJT_DATA_DIR` override).
- `date`: nullable. Set for `eml`/`msg` (when the email was sent/received, D-111's sort key);
  null for every other kind today. Matches the frontend's optional `JobApplicationFile.date`.
- `created_at`: when the row was added here, default now.

No `sha256`, no `extraction_status`/`extraction_message`/`extracted_text` columns the way
`profile_files` has: those exist there because a profile file's extracted text feeds a prompt
(Phase 2). A Job Application's own files are not read by Claude yet (D-109: the preview endpoint
and this table are new; nothing in this phase makes them a prompt input). Add those columns if
and when a job's own files become prompt input (positioning reading the listing again, for
example) — not before, per the project's own "don't build for a hypothetical" rule.

## Preview and Open (D-109, D-111, D-112)

`GET /profile/files/{id}/preview` is the only preview route that exists (D-109). The job-file
case `FilePreview.tsx` already anticipates (`PreviewSource = {table: 'job_file', id}`, not
written yet) reads this same table once a route for it exists: `GET /job-applications/{id}/
files` to list, and a preview route shaped like the profile one. Until then, the Job Application
page's Open and Preview buttons on a file row stay disabled, exactly as they are now — this spec
describes the storage, not the wiring, which is its own step.
