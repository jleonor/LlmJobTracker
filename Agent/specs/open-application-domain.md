# Domain: Open Application, its status history, research items and files

Phase 11 (D-248 to D-254). A second application type, distinct from Job Application
(`domain.md`): no listing, no lane, no match score, no positioning analysis. Claude Jobs and
their prompts are still `claude_jobs`/`claude_job_prompts` (D-59); `claude_jobs.open_application_id`
(migration 35) links a job to one Open Application, the same way `job_application_id` and
`lane_id` already link one to a Job Application or a lane.

## Open Application

One row for a talent pool submission, an unsolicited CV drop, or cold outreach — not tied to a
specific listing (D-249). Table `open_applications`.

- `target_name`, `target_type`: who/what this goes to, and what kind of outreach it is
  (`talent_pool`, `unsolicited`, `cold_outreach`). Both may be inferred by
  `generate_open_application_company_details` from the research intake, and are always
  user-editable afterward (D-251) — unlike Job Application's `company`/`role_title`, neither is
  required at creation time.
- `contact_name`, `contact_title`, `contact_email`: optional, a specific person this goes to.
- `angle`: free text, the user's own personal connection or leverage (e.g. a referral) — never
  inferred from the research items, since this is the user's own relationship, not public
  information about the target (D-251).
- `why_this_company`: free text, the user's own stated motivation, optional.
- `other_notes`: free text, anything else — appended alongside the research items' extracted
  text when building a prompt, not treated differently from them.
- `status`: Identified, Applied, Rejected, Withdrawn, Expired (D-249) — a subset of
  `migrations.STATUSES`; Screening, Interview and Offer are never written here.
- `master_cv_profile_file_id`: nullable, references `profile_files(id)` ON DELETE SET NULL, the
  same reference-only field Job Application already has (D-116).
- `notes`, `next_action`, `due_date`: free text / date, same meaning as Job Application's own
  (D-56), edited through Application history's Edit dialog (D-253).
- No `lane`, no `match_score`, no `fit`/`gaps`/`strategy`/`unclear` — this entity is never scored
  or lane-assigned (D-249).

## Status history

Table `open_application_status_history` (D-249, D-253): same shape as `status_history`
(`domain.md`), scoped by `open_application_id` instead of `job_application_id`, and checked
against the trimmed status set above, not the full `migrations.STATUSES`. Replaced wholesale by
Application history's Edit dialog the same way Job Application's Stages editor replaces
`status_history` (D-117) — there is no append-only multi-row model here, since this entity has
no Generate/Revise (LLM) step writing to it that would need one.

## Research items

Table `open_application_research_items` (D-251): up to 5 per Open Application, `position` 1-5.
Each is a URL or pasted text, extracted the same way Listing's own intake extracts a URL or
paste (`listing_intake.py`, reused directly — no new extraction logic). No category or label:
every item's `extracted_text` is concatenated verbatim, in position order, when building any
prompt that reads them (`generate_open_application_company_details` and the three document
generators) — the model does the mapping, not the schema (D-251).

- `content`: the raw URL or pasted text as given.
- `source_type`: `url` or `text`.
- `extracted_text`, `extraction_status`, `extraction_message`: same meaning as a Job
  Application's listing file (`domain.md`'s Files section) — `extraction_status` is one of
  `EXTRACTION_STATUSES` (migrations.py), set by code at intake time, never by Claude.

## Files

Table `open_application_files` (D-251, D-252, D-253): mirrors `job_files` (`files.md`), scoped
by `open_application_id`. Kinds: `tailored_cv`, `cover_letter`, `introduction_message`, `other`.
No `listing` kind (there is no listing) and no `positioning_breakdown` kind (there is no
positioning analysis, D-249). `tailored_cv` and `cover_letter` are `.docx`, generated the same
way Job Application's own are (D-130's block-id editing, reused against the Master CV / cover
letter template). `introduction_message` is Markdown/plain text, not `.docx` (D-252), and carries
its own `subject` column — the only kind that does; every other kind leaves it null. `other` is
the Additional files subsection's catch-all, same as Job Application's own (D-253).

Each kind except `other` holds at most one current file (D-115's convention, reused): a new
Generate replaces whatever was there.

## Revise turns

Table `open_application_revise_turns` (D-251, D-252): mirrors `job_revise_turns`
(`job-revise-steps.md`), using the same generic `TurnTable` (`revise_turns_shared.py`) — one row
per chat turn, scoped by `(open_application_id, section_kind)`. Four section kinds:
`company_details`, `tailored_cv`, `cover_letter`, `introduction_message`. No
`attachment_job_file_id` column — unlike Application history's own chat-revise (D-137/D-138),
Open Applications' Application history has no Generate/Revise step to attach a file to (D-253),
and no other section here takes a file attachment.
