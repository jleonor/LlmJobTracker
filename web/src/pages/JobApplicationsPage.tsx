import { useEffect, useState } from 'react'

import { RunnerCheck } from '@/components/app/RunnerCheck'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError, fetchJobApplicationDetail, fetchJobApplications } from '@/lib/api'
import type { JobApplication, JobApplicationDetail, JobApplicationDetailData } from '@/lib/types'
import { JobApplicationDetailPage } from '@/pages/JobApplicationDetailPage'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; applications: JobApplication[] }

// Keyed by id so a stale result from the previous selection can't render as if it were current
// (and so showing "loading" needs no setState call of its own at the top of the effect below).
type DetailState =
  | { kind: 'error'; id: number; message: string }
  | { kind: 'ready'; id: number; detail: JobApplicationDetail }

// The queue badge and positioning's fit/gap/unclear bullets aren't computed by anything yet
// (D-48, Phase 5), so the page shows them as "not run" rather than leaving the API response short
// of the shape JobApplicationDetailPage expects.
function withNotRunDefaults(data: JobApplicationDetailData): JobApplicationDetail {
  return { ...data, queue_status: 'idle', fit: [], gaps: [], unclear: [] }
}

const HEAD = 'font-mono text-[10px] uppercase tracking-wider'

// Column order from D-46. The queue badge stays "idle" until the Claude Jobs queue exists (Phase 2).
const COLUMNS = [
  'Company',
  'Title',
  'Lane',
  'Location',
  'Status',
  'Last updated',
  'Match score',
  'Queue',
] as const

export function JobApplicationsPage() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchJobApplications()
      .then((applications) => {
        if (!cancelled) setState({ kind: 'ready', applications })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'Could not load applications.'
        setState({ kind: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    let cancelled = false
    fetchJobApplicationDetail(selectedId)
      .then((data) => {
        if (!cancelled) setDetailState({ kind: 'ready', id: selectedId, detail: withNotRunDefaults(data) })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'Could not load this application.'
        setDetailState({ kind: 'error', id: selectedId, message })
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  if (selectedId !== null) {
    const current = detailState?.id === selectedId ? detailState : null
    return (
      <>
        {current === null && <p className="text-sm text-muted-foreground">Loading application...</p>}
        {current?.kind === 'error' && (
          <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
            {current.message}
          </div>
        )}
        {current?.kind === 'ready' && (
          <JobApplicationDetailPage application={current.detail} onBack={() => setSelectedId(null)} />
        )}
      </>
    )
  }

  return (
    <section aria-labelledby="applications-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 id="applications-heading" className="text-xl font-semibold tracking-tight">
          Job Applications
        </h1>
        {state.kind === 'ready' && (
          <span className="font-mono text-xs text-muted-foreground">
            {state.applications.length}{' '}
            {state.applications.length === 1 ? 'application' : 'applications'}
          </span>
        )}
      </div>

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading applications...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' && state.applications.length === 0 && (
        <p className="rounded border border-border p-6 text-center text-sm text-muted-foreground">
          No job applications yet. To load synthetic ones, close this and run .\run.ps1 -Seed
        </p>
      )}

      {state.kind === 'ready' && state.applications.length > 0 && (
        <div className="overflow-x-auto rounded border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                {COLUMNS.map((column) => (
                  <TableHead key={column} className={HEAD}>
                    {column}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.applications.map((app) => (
                <TableRow
                  key={app.id}
                  onClick={() => setSelectedId(app.id)}
                  className="cursor-pointer"
                >
                  <TableCell className="font-semibold">{app.company}</TableCell>
                  <TableCell>{app.role_title}</TableCell>
                  <TableCell>
                    {app.lane ? (
                      <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal">
                        {app.lane}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </TableCell>
                  <TableCell>{app.location ?? <span className="text-muted-foreground">-</span>}</TableCell>
                  <TableCell>
                    <StatusBadge status={app.status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{app.last_updated.slice(0, 10)}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {app.match_score === null ? (
                      <span className="text-muted-foreground">-</span>
                    ) : (
                      `${Math.round(app.match_score)}%`
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal text-muted-foreground">
                      idle
                    </Badge>
                  </TableCell>
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
