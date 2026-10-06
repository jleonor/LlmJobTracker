import type { JobApplication, ProfileFile, ProfileFileKind, RunResult } from '@/lib/types'

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
    throw new ApiError(`The API returned HTTP ${response.status}.`, response.status)
  }
  return (await response.json()) as T
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
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) => (typeof body.detail === 'string' ? body.detail : null))
      .catch(() => null)
    throw new ApiError(detail ?? `The API returned HTTP ${response.status}.`, response.status)
  }
  return (await response.json()) as ProfileFile
}
