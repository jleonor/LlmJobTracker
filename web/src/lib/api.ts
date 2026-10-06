import type {
  ClaudeJob,
  Fact,
  FactChange,
  FactSheet,
  JobApplication,
  ProfileFile,
  ProfileFileKind,
  ProfileOutput,
  RunResult,
} from '@/lib/types'

export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  // The dev proxy answers 502-504 when the API process is not listening.
  if (response.status >= 502 && response.status <= 504) {
    throw new ApiError('The API is not running on 127.0.0.1:8765.', response.status)
  }
  if (response.status === 401) {
    throw new ApiError('The API rejected the launch token. Restart the dev launcher.', 401)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as T
}

// The API gives a reason in `detail` for refusals (for example a bad date). Show it when it is there.
async function errorMessage(response: Response): Promise<string> {
  const detail = await response
    .json()
    .then((body: { detail?: unknown }) => (typeof body.detail === 'string' ? body.detail : null))
    .catch(() => null)
  return detail ?? `The API returned HTTP ${response.status}.`
}

export function fetchJobApplications(): Promise<JobApplication[]> {
  return request<JobApplication[]>('/api/job-applications')
}

export function runClaudeCheck(): Promise<RunResult> {
  return request<RunResult>('/api/runs/check', { method: 'POST' })
}

export function fetchProfileFiles(): Promise<ProfileFile[]> {
  return request<ProfileFile[]>('/api/profile/files')
}

// Sends the file's bytes. The name goes in a header, URL-encoded (the API decodes it).
// The API's own message (for example "already uploaded") is shown when it gives one.
export async function uploadProfileFile(kind: ProfileFileKind, file: File): Promise<ProfileFile> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${kind}`, {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as ProfileFile
}

export function fetchFactSheet(): Promise<FactSheet> {
  return request<FactSheet>('/api/profile/facts')
}

export function updateFact(id: number, change: FactChange): Promise<Fact> {
  return request<Fact>(`/api/profile/facts/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(change),
  })
}

export function fetchProfileOutputs(): Promise<ProfileOutput[]> {
  return request<ProfileOutput[]>('/api/profile/outputs')
}

// Saves an edited output as a new version. The API checks it the same way as Claude's answer.
export function saveProfileOutput(kind: string, body: Record<string, unknown>): Promise<ProfileOutput> {
  return request<ProfileOutput>(`/api/profile/outputs/${kind}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function startProfileAnalysis(): Promise<ClaudeJob> {
  return request<ClaudeJob>('/api/profile/analysis', { method: 'POST' })
}

export function fetchClaudeJobs(): Promise<ClaudeJob[]> {
  return request<ClaudeJob[]>('/api/claude-jobs')
}

export function resumeClaudeJob(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/claude-jobs/${id}/resume`, { method: 'POST' })
}

export function cancelClaudeJob(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/claude-jobs/${id}/cancel`, { method: 'POST' })
}
