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
  | 'master_cv_en'
  | 'master_cv_fr'
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
