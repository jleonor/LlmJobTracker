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

export type ProfileFile = {
  id: number
  kind: ProfileFileKind
  original_name: string
  sha256: string
  size_bytes: number
  uploaded_at: string
  extraction_status: string | null
  extraction_message: string | null
}

// The Fact Sheet review (Phase 2 step 8). Field names match the API.
export type FactStatus = 'unverified' | 'verified' | 'rejected'

export type Fact = {
  id: number
  fact_key: string
  text: string
  date: string
  source_file_id: number
  source_name: string
  source_location: string
  status: FactStatus
}

export type FactConflict = {
  id: string
  fact_ids: string[]
  note: string
}

export type FactSheet = {
  output_id: number | null
  version: number | null
  facts: Fact[]
  conflicts: FactConflict[]
}

export type FactChange = {
  text?: string
  date?: string
  source_location?: string
  status?: FactStatus
}

// The profile outputs (Profile page, step 9). The bodies follow Agent/specs/profile-steps.md.
export type HistoryItem = {
  id: string
  kind: string
  text: string
  date: string
  source: { file_id: number; location: string }
  conflicts: { with: string; note: string }[]
}

export type FullCvHistoryBody = { items: HistoryItem[] }

export type QuestionnaireBody = {
  themes: { id: string; text: string; questionnaire_ref: string; fact_ids: string[] }[]
  gaps: { text: string }[]
}

export type Lane = {
  id: string
  name: string
  description: string
  fact_ids: string[]
  questionnaire_ids: string[]
}

export type StrategyBody = { overview: string; lanes: Lane[]; open_points: string[] }

export type ProfileOutput = {
  id: number
  kind: 'full_cv_history' | 'fact_sheet' | 'questionnaire_analysis' | 'strategy'
  version: number
  claude_job_id: number | null
  body: Record<string, unknown>
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
  prompts: ClaudeJobPrompt[]
}
