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
}
