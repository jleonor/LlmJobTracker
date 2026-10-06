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
