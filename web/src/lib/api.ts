import type { Job, RunResult } from '@/lib/types'

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

export function fetchJobs(): Promise<Job[]> {
  return request<Job[]>('/api/jobs')
}

export function runClaudeCheck(): Promise<RunResult> {
  return request<RunResult>('/api/runs/check', { method: 'POST' })
}
