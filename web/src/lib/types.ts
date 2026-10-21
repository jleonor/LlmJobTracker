// One row of the Applications table (D-227): every field any of its 26 selectable columns might
// need. Field names match the API.
export type JobApplication = {
  id: number
  company: string
  role_title: string
  lane: string | null
  location: string | null
  status: string
  last_updated: string
  match_score: number | null
  portal_name: string | null
  portal_url: string | null
  work_mode: string
  contract_type: string
  notes: string | null
  next_action: string | null
  due_date: string | null
  status_history: StatusHistoryEntry[]
  has_listing: boolean
  has_details: boolean
  has_analysis: boolean
  has_tailored_cv: boolean
  has_cover_letter: boolean
  has_interview_prep: boolean
}

export type StatusHistoryEntry = {
  status: string
  changed_at: string
}

// One of Interview preparation's ten question/answer pairs (D-166, job-llm-steps.md §7). score
// (D-173) is out of 10, how strong the answer is for this role - null for a pair added by hand
// through the Edit dialog, which has no model judgment behind it.
export type InterviewPrepPair = {
  question: string
  answer: string
  score: number | null
}

export type JobApplicationFile = {
  id: number
  name: string
  kind: string
  // When this file is an email (kind "eml" or "msg"), the date it was received. The Application
  // history page's Emails column (D-111) is this same array filtered to those two kinds, sorted
  // by this field — an email can only show there if it is also listed as a file (D-112).
  date?: string
  // Set only for the listing (D-122, job-llm-steps.md): whether its text could be read, for
  // Job details and Positioning analysis to use as context. Null for every other kind today.
  extraction_status?: string | null
  extraction_message?: string | null
}

// A Job Application's own Claude Jobs (D-49 to D-52), shown beside its status tag (D-56). Idle
// means nothing is queued for this application; the rest mirror CLAUDE_JOB_STATUSES.
export type QueueStatus = 'idle' | 'queued' | 'processing' | 'paused' | 'cancelled' | 'done' | 'failed'

// The defined stage order (D-44, D-101), used for the tracker table's Status sort and filter -
// not alphabetical, since the stages have a real sequence. Matches StatusBadge's own tone order.
export const STATUS_ORDER = [
  'Identified',
  'Applied',
  'Screening',
  'Interview',
  'Offer',
  'Rejected',
  'Withdrawn',
  'Expired',
] as const

// Same idea for the Queue column: a lifecycle order, not alphabetical. Matches QueueStatusBadge's
// own tone order.
export const QUEUE_STATUS_ORDER: readonly QueueStatus[] = [
  'idle',
  'queued',
  'processing',
  'paused',
  'done',
  'failed',
  'cancelled',
]

// What GET /job-applications/{id} returns (D-113, D-116): the table row's fields plus everything
// else actually stored for one Job Application. Field names match the API.
export type JobApplicationDetailData = JobApplication & {
  portal_name: string | null
  portal_url: string | null
  work_mode: string
  contract_type: string
  description: string | null
  requirements: string[]
  notes: string | null
  next_action: string | null
  due_date: string | null
  status_history: StatusHistoryEntry[]
  files: JobApplicationFile[]
  // D-116: a reference to one of the Profile page's master CVs (profile_files.id), not a copied
  // job file — it has no preview or open of its own, the Profile page is where that happens.
  // master_cv_name is the chosen file's display name, joined in server-side for convenience.
  master_cv_profile_file_id: number | null
  master_cv_name: string | null
  // Positioning analysis (D-98, D-116): fit and gap bullets, a prose strategy, and points the
  // LLM (or, for now, the user) flagged as unclear (D-102). The per-requirement weights, matches
  // and reasoning behind match_score are not shown inline — they are the breakdown document in
  // `files`, not a structured field here (D-99). match_score itself stays code-computed (D-47),
  // not part of this manually-editable set.
  fit: string[]
  gaps: string[]
  strategy: string | null
  unclear: string[]
  // Interview preparation (D-166): ten question/answer pairs, generated the same way as the
  // fields above and manually editable through its own Edit button (D-168).
  interview_prep: InterviewPrepPair[]
}

// A PATCH /job-applications/{id} body (D-116): only the fields a form actually sends are
// written server-side, so a field left out here leaves that column untouched, not cleared.
// Matches the API's JobApplicationEdit.
export type JobApplicationEdit = Partial<{
  lane: string | null
  role_title: string
  portal_name: string | null
  portal_url: string | null
  location: string | null
  work_mode: string
  contract_type: string
  description: string | null
  requirements: string[]
  notes: string | null
  next_action: string | null
  due_date: string | null
  fit: string[]
  gaps: string[]
  strategy: string | null
  unclear: string[]
  interview_prep: InterviewPrepPair[]
}>

// The Job Application page's full shape (D-56, D-98, planning/product-model.md). Extends the API
// response with the one thing nothing computes yet: the queue badge. JobApplicationsPage.tsx
// fills it in with a "not run" default.
export type JobApplicationDetail = JobApplicationDetailData & {
  queue_status: QueueStatus
}

export type RunResult = {
  ok: boolean
  text: string
  error: string | null
  duration_ms: number
  cost_usd: number | null
  model: string | null
}

// The sidebar's display name, read from and saved to /settings.
// The backend the app currently uses for reasoning tasks (D-195: one global switch).
export type Backend = 'claude_code' | 'codex'
// D-201: how a paused-at-a-rate-limit job resumes.
export type RetryPolicy = 'reset_time' | 'fixed_interval' | 'manual_only'

export type Settings = {
  user_name: string
  backend: Backend
  retry_policy: RetryPolicy
  retry_interval_minutes: number
  retry_max_attempts: number
  // D-206: which model each backend uses, selected from that provider's own price table.
  claude_code_model: string
  codex_model: string
  // D-212: where "Open LLM app" rebuilds its export. null means the default (Downloads).
  llm_export_path: string | null
}

// "Open LLM app" (D-202, D-210): which backend's desktop app was launched, and where the
// export it was pointed at lives.
export type LlmAppOpened = {
  backend: Backend
  bundle_path: string
}

// Whether a backend's desktop app is installed (D-210), mirroring AuthStatus's shape (D-203).
export type LlmAppStatus = {
  installed: boolean
  detail: string
}

// One stored price row (D-198).
export type ModelPrice = {
  provider: Backend
  model: string
  input_price_per_token: number
  output_price_per_token: number
  updated_at: string
}

// A price row proposed by the "fetch and update" scrape, not yet saved (D-198).
export type ParsedModelPrice = {
  model: string
  input_price_per_token: number
  output_price_per_token: number
}

// Whether a backend's CLI is currently logged in (D-203).
export type AuthStatus = {
  logged_in: boolean
  detail: string
}

// One uploaded profile file (Profile page). The kinds follow migration 3.
export type ProfileFileKind =
  | 'master_cv'
  | 'older_cv'
  | 'older_letter'
  | 'questionnaire'
  | 'writing_rules'
  | 'own_full_cv_history'
  | 'own_questionnaire_analysis'
  | 'own_strategy'
  | 'cover_letter_template'

export type ProfileFile = {
  id: number
  kind: ProfileFileKind
  original_name: string
  sha256: string
  size_bytes: number
  uploaded_at: string
  extraction_status: string | null
  extraction_message: string | null
  generated: boolean
}

// The approved, named list of positioning directions a Job Application's lane field picks from
// (D-182, D-214). Edited inline on the Profile page; (re)populated in bulk from the positioning
// strategy document by the Sync from strategy action.
export type Lane = {
  id: number
  name: string
  description: string | null
  reasoning: string | null
  position: number
  // The Dashboard's per-lane strengths/weaknesses summary (D-238) - null until "Analyze lanes"
  // has run for this lane at least once.
  fit_gap_summary: string | null
  fit_gap_summary_generated_at: string | null
}

// The Dashboard's "Analyze lanes" action (D-238). Same GET-previews/POST-runs shape as
// PositioningRescoreSummary and LaneReassignmentSummary.
export type LaneAnalysisSummary = {
  queued: number
  skipped: number
}

// The Dashboard's cross-lane overview report (D-245): all fields null until "Summarize lanes"
// has run at least once. `summary` is the short synopsis shown always; `overall_fit`/
// `overall_gaps` are the two detail sections, collapsed by default.
export type LaneOverview = {
  summary: string | null
  overall_fit: string | null
  overall_gaps: string | null
  generated_at: string | null
}

// Settings' "Re-score all positioning analyses" action (D-218). GET previews these counts
// read-only; POST runs it for real and returns the same shape.
export type PositioningRescoreSummary = {
  queued: number
  skipped: number
}

// The Lanes section's "Reassign missing lanes" action (D-222). Same GET-previews/POST-runs
// shape as PositioningRescoreSummary.
export type LaneReassignmentSummary = {
  queued: number
  skipped: number
}

// The Lanes section's "Clear all lanes" and "Clear all not in list" actions (D-222).
export type LaneClearSummary = {
  cleared: number
}

// The newest version of one of the three generated profile documents (D-86), as /profile/outputs
// lists it. kind is one of PROMPT_KINDS: full_cv_history, questionnaire_analysis, strategy.
export type ProfileOutput = {
  id: number
  kind: string
  version: number
  claude_job_id: number | null
  document: string
  created_at: string
}

// A Claude Job as the API lists it (no prompt text).
export type ClaudeJobPrompt = {
  position: number
  prompt_kind: string
  status: string
  error: string | null
  cost_usd: number | null
  duration_ms: number | null
  model: string | null
  // Token counts (D-197). Only cost_usd is free from every backend; these are the figure every
  // backend is expected to supply, cost computed from them when a backend doesn't report it.
  input_tokens: number | null
  output_tokens: number | null
  started_at: string | null
  finished_at: string | null
  skipped: boolean
  skip_reason: string | null
  answer_chars: number | null
  // The answer streamed so far, while this prompt is running (D-105). Null once it isn't.
  live_text: string | null
}

export type ClaudeJob = {
  id: number
  label: string
  kind: string
  job_application_id: number | null
  lane_id: number | null
  status: string
  error: string | null
  created_at: string
  updated_at: string
  resume_at: string | null
  // Consecutive rate-limit pauses with no success since (D-201's fixed_interval policy).
  retry_attempts: number
  prompts: ClaudeJobPrompt[]
}

// What was sent to Claude for one prompt, and what came back (D-77). Read on demand, since the
// prompt can be very large.
export type PromptExchange = {
  position: number
  prompt_kind: string
  prompt_text: string
  result_text: string | null
  error: string | null
}

// One Revise (LLM) chat turn and the Claude Job it queued (D-106).
export type ReviseTurn = {
  id: number
  message: string
  created_at: string
  job: ClaudeJob
}

// What GET /profile/files/{id}/preview (or a future job-file equivalent) returns, read from the
// response's content type (D-107, D-109). "pdf" carries a Blob so the caller can build an object
// URL for an <iframe>; everything else is decoded text.
export type FilePreviewData =
  | { kind: 'pdf'; blob: Blob }
  | { kind: 'text' | 'markdown' | 'html'; text: string }

// What one of the Listing's extract-url/extract-paste/extract-upload routes returns (D-121,
// job-llm-steps.md): code-only extraction, reviewable before any model step runs. status is one
// of the same EXTRACTION_STATUSES every other extraction uses (ok, no_text, unsupported, failed).
export type ListingExtraction = {
  method: 'url' | 'paste' | 'upload'
  source: string | null
  status: string
  message: string | null
  text: string
}

// Add Job (Agent/specs/intake-steps.md, D-143 to D-146). The three chains queue_add_job_chain
// knows how to build, in increasing scope.
export type AddJobWorkflow = 'basic' | 'positioning' | 'full'

// GET /job-applications/intake/duplicate-check's result: the one existing application (if any)
// whose listing matches the reviewed text's content hash or source URL, checked before any
// Claude call runs. Never matched on company/role title (D-146).
export type DuplicateListingMatch = {
  application_id: number
  company: string
  role_title: string
  matched_by: 'content' | 'url'
}

// GET /job-applications/intake/identity/{job_id}'s parsed answer: company and role_title are
// the only two fields that can reject the whole answer (missing/Unknown fails closed); every
// other field is null, not the literal word "Unknown", when the listing doesn't say.
export type JobIdentityAnswer = {
  company: string
  role_title: string
  lane: string | null
  location: string | null
  portal_name: string | null
  portal_url: string | null
}

// POST /job-applications's body: the identity fields the user confirmed or typed by hand, the
// reviewed listing text and how it was obtained, the chosen workflow, and an optional Master CV
// reference.
export type CreateJobApplicationRequest = {
  company: string
  role_title: string
  lane: string | null
  location: string | null
  portal_name: string | null
  portal_url: string | null
  listing_method: ListingExtraction['method']
  listing_text: string
  listing_source_url: string | null
  workflow: AddJobWorkflow
  master_cv_profile_file_id: number | null
}

// POST /job-applications's result: the new row's id and every Claude Job queued for it, in
// queued order (Listing, Job details, then the rest of the chosen workflow, D-144).
export type AddJobResult = {
  application_id: number
  claude_job_ids: number[]
}
