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
  name: string
  kind: string
}

// A Job Application's own Claude Jobs (D-49 to D-52), shown beside its status tag (D-56). Idle
// means nothing is queued for this application; the rest mirror CLAUDE_JOB_STATUSES.
export type QueueStatus = 'idle' | 'queued' | 'processing' | 'paused' | 'cancelled' | 'done' | 'failed'

// The Job Application page's fields beyond the table row (D-56, D-98, planning/product-model.md).
// Phase 3 design pass only: no detail endpoint exists yet, so this is seed data
// (lib/sampleJobDetail.ts), not an API response. The migration and dry-run import that back
// this for real come later in the phase's step list.
export type JobApplicationDetail = JobApplication & {
  queue_status: QueueStatus
  portal_name: string | null
  portal_url: string | null
  work_mode: string
  contract_type: string
  description: string | null
  requirements: string[]
  // Positioning analysis (D-98): fit and gap bullets. The per-requirement weights, matches and
  // reasoning behind match_score are not shown inline — they are the breakdown document in
  // `files`, not a structured field here (D-99).
  fit: string[]
  gaps: string[]
  // Points the LLM flagged as unclear while scoring, which answering would sharpen (D-102).
  unclear: string[]
  notes: string | null
  next_action: string | null
  due_date: string | null
  status_history: StatusHistoryEntry[]
  files: JobApplicationFile[]
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
