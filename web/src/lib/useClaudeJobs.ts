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
// narrows D-59's "Claude: queued" wording). Staged jobs (D-286) are never counted here - they are
// waiting on the user, not the queue, and have their own count via stagedCount below.
export function queueLabel(jobs: ClaudeJob[]): string {
  if (jobs.some((job) => job.status === 'processing')) return 'LLM: processing'
  if (jobs.some((job) => job.status === 'paused')) return 'LLM: paused'
  const queued = jobs.filter((job) => job.status === 'queued').length
  if (queued > 0) return `LLM: ${queued} queued`
  return 'LLM: idle'
}

// The header's "Trigger workflows" button (D-288): how many Claude Jobs, app-wide, are staged
// and waiting for that click.
export function stagedCount(jobs: ClaudeJob[]): number {
  return jobs.filter((job) => job.status === 'staged').length
}

// The per-application queue badge (D-56's "beside the status tag", D-227's inline table
// indicator): idle unless this application has a non-terminal Claude Job of its own, or its own
// *most recently updated* job failed and still needs attention (D-231, narrows D-227: `paused`/
// `failed` used to look at *any* job the application ever ran, so an old failure stayed visible
// forever even after a later rerun of the same kind succeeded - only the last generated output's
// own outcome matters now). A job this application once ran that is now done/cancelled reads as
// idle too - nothing is pending and nothing needs a look, which is what the badge is for (D-49
// to D-52).
export function queueStatusFor(jobs: ClaudeJob[], applicationId: number): QueueStatus {
  return queueStatusForJobs(jobs.filter((job) => job.job_application_id === applicationId))
}

// Mirrors queueStatusFor, scoped to an Open Application instead of a Job Application (D-250).
export function openApplicationQueueStatusFor(jobs: ClaudeJob[], applicationId: number): QueueStatus {
  return queueStatusForJobs(jobs.filter((job) => job.open_application_id === applicationId))
}

function queueStatusForJobs(mine: ClaudeJob[]): QueueStatus {
  if (mine.some((job) => job.status === 'processing')) return 'processing'
  const mostRecent = mine.reduce<ClaudeJob | null>(
    (latest, job) => (!latest || job.updated_at > latest.updated_at ? job : latest),
    null
  )
  if (mostRecent?.status === 'paused') return 'paused'
  if (mine.some((job) => job.status === 'queued')) return 'queued'
  // staged (D-286): nothing is queued or running yet, but a chain is waiting on the user to
  // trigger it (D-288) - shown ahead of a past failure, since it is the more actionable state.
  if (mine.some((job) => job.status === 'staged')) return 'staged'
  if (mostRecent?.status === 'failed') return 'failed'
  return 'idle'
}
