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

export type RunResult = {
  ok: boolean
  text: string
  error: string | null
  duration_ms: number
  cost_usd: number | null
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

// The three profile documents (Phase 2, D-85, D-86). Each is Markdown prose.
export type ProfileOutput = {
  id: number
  kind: 'full_cv_history' | 'questionnaire_analysis' | 'strategy'
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
