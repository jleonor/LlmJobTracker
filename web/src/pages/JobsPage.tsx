import { useEffect, useState } from 'react'

import { RunnerCheck } from '@/components/app/RunnerCheck'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError, fetchJobs } from '@/lib/api'
import type { Job } from '@/lib/types'

type State = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; jobs: Job[] }

const HEAD = 'font-mono text-[10px] uppercase tracking-wider'

export function JobsPage() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    fetchJobs()
      .then((jobs) => {
        if (!cancelled) setState({ kind: 'ready', jobs })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'Could not load jobs.'
        setState({ kind: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section aria-labelledby="jobs-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 id="jobs-heading" className="text-xl font-semibold tracking-tight">
          Jobs
        </h1>
        {state.kind === 'ready' && (
          <span className="font-mono text-xs text-muted-foreground">
            {state.jobs.length} {state.jobs.length === 1 ? 'job' : 'jobs'}
          </span>
        )}
      </div>

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading jobs...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' && state.jobs.length === 0 && (
        <p className="rounded border border-border p-6 text-center text-sm text-muted-foreground">
          No jobs yet. Seed synthetic jobs with the command in the README.
        </p>
      )}

      {state.kind === 'ready' && state.jobs.length > 0 && (
        <div className="overflow-x-auto rounded border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className={HEAD}>Company</TableHead>
                <TableHead className={HEAD}>Role title</TableHead>
                <TableHead className={HEAD}>Lane</TableHead>
                <TableHead className={HEAD}>Status</TableHead>
                <TableHead className={HEAD}>Next action</TableHead>
                <TableHead className={HEAD}>Due</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.jobs.map((job) => (
                <TableRow key={job.id}>
                  <TableCell className="font-semibold">{job.company}</TableCell>
                  <TableCell>{job.role_title}</TableCell>
                  <TableCell>
                    {job.lane ? (
                      <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal">
                        {job.lane}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={job.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{job.next_action ?? '-'}</TableCell>
                  <TableCell className="font-mono text-xs">{job.due_date ?? '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <RunnerCheck />
    </section>
  )
}
