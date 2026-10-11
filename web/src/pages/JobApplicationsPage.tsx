import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AddJobOverlay } from '@/components/app/AddJobOverlay'
import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { RunnerCheck } from '@/components/app/RunnerCheck'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError, fetchJobApplicationDetail, fetchJobApplications } from '@/lib/api'
import { queueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
import type { JobApplication, JobApplicationDetailData } from '@/lib/types'
import { JobApplicationDetailPage } from '@/pages/JobApplicationDetailPage'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; applications: JobApplication[] }

// Keyed by id so a stale result from the previous selection can't render as if it were current
// (and so showing "loading" needs no setState call of its own at the top of the effect below).
// queue_status is computed fresh at render time from `queue` below, not stored here, so the
// badge stays live as the queue polls rather than freezing at whatever it was on fetch.
type DetailState =
  | { kind: 'error'; id: number; message: string }
  | { kind: 'ready'; id: number; detail: JobApplicationDetailData }

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

export function JobApplicationsPage({ queue }: { queue: QueueState }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [addJobOpen, setAddJobOpen] = useState(false)

  function reloadApplications() {
    fetchJobApplications()
      .then((applications) => setState({ kind: 'ready', applications }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load applications.'
        setState({ kind: 'error', message })
      })
  }

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
        if (!cancelled) setDetailState({ kind: 'ready', id: selectedId, detail: data })
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

  // Re-reads the detail after an Edit, Upload or Master CV change on the page (D-116), instead
  // of each of those updating local state themselves.
  function reloadDetail() {
    if (selectedId === null) return
    fetchJobApplicationDetail(selectedId)
      .then((data) => setDetailState({ kind: 'ready', id: selectedId, detail: data }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load this application.'
        setDetailState({ kind: 'error', id: selectedId, message })
      })
  }

  // A detail-page edit (location, status-adjacent fields later) can change what the table shows,
  // so going back re-reads the list rather than leaving it stale until a full page reload.
  function backToList() {
    setSelectedId(null)
    reloadApplications()
  }

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
          <JobApplicationDetailPage
            application={{
              ...current.detail,
              queue_status: queueStatusFor(queue.jobs, current.detail.id),
            }}
            onBack={backToList}
            onChanged={reloadDetail}
            onDeleted={backToList}
          />
        )}
      </>
    )
  }

  return (
    <section aria-labelledby="applications-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
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
        <Button onClick={() => setAddJobOpen(true)}>
          <Plus className="size-4" aria-hidden="true" />
          Add Job
        </Button>
      </div>

      <AddJobOverlay
        open={addJobOpen}
        onOpenChange={setAddJobOpen}
        onCreated={() => reloadApplications()}
        onOpenApplication={(applicationId) => {
          setAddJobOpen(false)
          setSelectedId(applicationId)
        }}
      />

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
                    <QueueStatusBadge status={queueStatusFor(queue.jobs, app.id)} />
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
