# Files: a Job Application's managed folder and the file-links table

Phase 3. Profile files are `profile_files` (Phase 2); this is the equivalent for a Job
Application's own files — the listing, CVs, cover letters, the positioning breakdown document,
and filed emails.

## Managed folder layout

    %LOCALAPPDATA%\LlmJobTracker\files\<company>\<role_title>\<name>

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
  not yet given its own kind. `master_cv` stays in this list for schema stability but is not
  actually used: D-116 makes the Master CV selector a reference to `profile_files`
  (`job_applications.master_cv_profile_file_id`), not a copied job file, so nothing inserts a
  `job_files` row with this kind.
- `name`: the display name, matching the frontend's `JobApplicationFile.name` (D-111's Emails
  column strips a trailing `.eml`/`.msg` for display; the stored name keeps it).
- `stored_path`: the file's path under the managed folder above, relative to
  `%LOCALAPPDATA%\LlmJobTracker\files\` (not absolute — the data directory itself can move,
  D-21's `LJT_DATA_DIR` override).
- `date`: nullable. Set for `eml`/`msg` (when the email was sent/received, D-111's sort key);
  null for every other kind today. Matches the frontend's optional `JobApplicationFile.date`.
- `created_at`: when the row was added here, default now.

`sha256`, `extraction_status`, `extraction_message`, `extracted_text`: the same four columns
`profile_files` has, added once a job's own files become prompt input — the Listing file is read
by Job details and Positioning analysis (`job-llm-steps.md`). Extraction runs the same code-only
rules as `profile_files`' (pypdf/python-docx/text; HTML gets the same readability extraction
`job-llm-steps.md`'s Listing step uses). `listing` and `other` (Additional files, D-262) are
extracted at upload time; the remaining kinds are written by a generation step (Tailored CV, Cover
letter, the positioning breakdown — Phase 5) that stores extracted text directly, or are read fresh
each run rather than stored (Emails: Application history reads a filed `.eml`/`.msg` as files, not
through `extracted_text`, `job-llm-steps.md` §4).

## Preview, Open and Upload (D-109, D-111, D-112, D-116)

A job file's own routes mirror the profile ones:

- `POST /job-applications/{application_id}/files/{kind}` — upload. Unlike
  `store_profile_file` (content-addressed by SHA-256), the file keeps its own readable name on
  disk; a same-named clash gets a short suffix rather than being overwritten or deduplicated. No
  text extraction (job files aren't prompt input yet, per the note above).
- `GET /job-applications/{application_id}/files/{file_id}/preview` — reuses `file_preview.py`'s
  `preview_for`, exactly like `GET /profile/files/{id}/preview` (D-107, D-109).
  `FilePreview.tsx`'s `PreviewSource = {table: 'job_file', applicationId, id}` case reads this.
- `POST /job-applications/{application_id}/files/{file_id}/open` — hands the file to the
  system's default app, reusing `profile_files.open_in_default_app`.

All three check the file actually belongs to `application_id`, not just that `file_id` exists.
The Master CV selector is the exception (D-116): it has no preview or open of its own, since it
references a Profile page file rather than holding a copy.
