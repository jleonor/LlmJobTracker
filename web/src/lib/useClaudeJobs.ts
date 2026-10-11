import { useCallback, useEffect, useState } from 'react'

import { ApiError, fetchClaudeJobs } from '@/lib/api'
import type { ClaudeJob, QueueStatus } from '@/lib/types'

// How often the queue is read while nothing is running. Tightened while a job is processing
// (D-105), so a streaming trace panel has something fresh to show.
const POLL_MS = 4000
const ACTIVE_POLL_MS = 1000

export type QueueState = {
  jobs: ClaudeJob[]
  error: string | null
  reload: () => void
}

// The Claude Jobs queue, read from the API every few seconds (Phase 2 step 10).
export function useClaudeJobs(): QueueState {
  const [jobs, setJobs] = useState<ClaudeJob[]>([])
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(() => {
    fetchClaudeJobs()
      .then((list) => {
        setJobs(list)
        setError(null)
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the queue.')
      })
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  // Re-evaluated on every poll (jobs is a new array each time), so the cadence adapts as soon
  // as a job starts or finishes processing.
  useEffect(() => {
    const active = jobs.some((job) => job.status === 'processing')
    const timer = window.setInterval(reload, active ? ACTIVE_POLL_MS : POLL_MS)
    return () => window.clearInterval(timer)
  }, [jobs, reload])

  return { jobs, error, reload }
}

// What the header shows: processing, paused, queued, or idle. Reads "LLM", not "Claude" (D-100,
// narrows D-59's "Claude: queued" wording).
export function queueLabel(jobs: ClaudeJob[]): string {
  if (jobs.some((job) => job.status === 'processing')) return 'LLM: processing'
  if (jobs.some((job) => job.status === 'paused')) return 'LLM: paused'
  const queued = jobs.filter((job) => job.status === 'queued').length
  if (queued > 0) return `LLM: ${queued} queued`
  return 'LLM: idle'
}

// The per-application queue badge (D-56's "beside the status tag", the table's own Queue
// column): idle unless this application has a non-terminal Claude Job of its own. A job this
// application once ran that is now done/failed/cancelled reads as idle too - nothing is
// currently pending, which is what the badge is for (D-49 to D-52).
export function queueStatusFor(jobs: ClaudeJob[], applicationId: number): QueueStatus {
  const mine = jobs.filter((job) => job.job_application_id === applicationId)
  if (mine.some((job) => job.status === 'processing')) return 'processing'
  if (mine.some((job) => job.status === 'paused')) return 'paused'
  if (mine.some((job) => job.status === 'queued')) return 'queued'
  return 'idle'
}
