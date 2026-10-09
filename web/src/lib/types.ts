// One row of the Applications table (D-46). Field names match the API.
export type JobApplication = {
  id: number
  company: string
  role_title: string
  lane: string | null
  location: string | null
  status: string
  last_updated: string
  match_score: number | null
}

export type StatusHistoryEntry = {
  status: string
  changed_at: string
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
}

// A PATCH /job-applications/{id} body (D-116): only the fields a form actually sends are
// written server-side, so a field left out here leaves that column untouched, not cleared.
// Matches the API's JobApplicationEdit.
export type JobApplicationEdit = Partial<{
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
}

// The sidebar's display name, read from and saved to /settings.
export type Settings = {
  user_name: string
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
  status: string
  error: string | null
  created_at: string
  updated_at: string
  resume_at: string | null
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
