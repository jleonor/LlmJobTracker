import { useCallback, useEffect, useState } from 'react'

import { ApiError, fetchClaudeJobs } from '@/lib/api'
import type { ClaudeJob } from '@/lib/types'

// How often the queue is read while the app is open. The queue runs in the background.
const POLL_MS = 4000

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
    const timer = window.setInterval(reload, POLL_MS)
    return () => window.clearInterval(timer)
  }, [reload])

  return { jobs, error, reload }
}

// What the header shows: processing, paused, queued, or idle (D-59 reads "Claude: queued").
export function queueLabel(jobs: ClaudeJob[]): string {
  if (jobs.some((job) => job.status === 'processing')) return 'Claude: processing'
  if (jobs.some((job) => job.status === 'paused')) return 'Claude: paused'
  const queued = jobs.filter((job) => job.status === 'queued').length
  if (queued > 0) return `Claude: ${queued} queued`
  return 'Claude: idle'
}
