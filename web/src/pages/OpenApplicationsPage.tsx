import { Loader2, Plus, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { AddOpenApplicationOverlay } from '@/components/app/AddOpenApplicationOverlay'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, fetchOpenApplicationDetail, fetchOpenApplications } from '@/lib/api'
import type { OpenApplication, OpenApplicationDetailData, QueueStatus } from '@/lib/types'
import { openApplicationQueueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
import { OpenApplicationDetailPage } from '@/pages/OpenApplicationDetailPage'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; applications: OpenApplication[] }

type DetailState =
  | { kind: 'error'; id: number; message: string }
  | { kind: 'ready'; id: number; detail: OpenApplicationDetailData }

const HEAD = 'font-mono text-[10px] uppercase tracking-wider'

const TARGET_TYPE_LABELS: Record<string, string> = {
  talent_pool: 'Talent pool',
  unsolicited: 'Unsolicited CV drop',
  cold_outreach: 'Cold outreach',
}

// Mirrors JobApplicationsPage.tsx's own QueueIndicator (D-227), scoped to Open Applications.
function QueueIndicator({ status }: { status: QueueStatus }) {
  if (status === 'processing') {
    return (
      <Tooltip>
        <TooltipTrigger render={<span />} className="inline-flex shrink-0 cursor-default">
          <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Processing" />
        </TooltipTrigger>
        <TooltipContent>Processing</TooltipContent>
      </Tooltip>
    )
  }
  if (status === 'queued') {
    return (
      <Badge
        variant="outline"
        className="shrink-0 rounded-sm font-mono text-[10px] font-normal text-muted-foreground"
      >
        Queued
      </Badge>
    )
  }
  if (status === 'paused' || status === 'failed') {
    return (
      <Tooltip>
        <TooltipTrigger render={<span />} className="inline-flex shrink-0 cursor-default">
          <TriangleAlert
            className="size-3.5 text-[#ffca85]"
            aria-label={status === 'paused' ? 'Paused' : 'Failed'}
          />
        </TooltipTrigger>
        <TooltipContent>{status === 'paused' ? 'Paused - needs Resume' : 'Failed'}</TooltipContent>
      </Tooltip>
    )
  }
  return null
}

// A second table, deliberately simpler than the Job Applications one (D-250): Company, Target
// type, Status, Last updated, the same inline queue indicator - no Lane or Match score columns,
// since neither exists for this entity, and no column customization (D-227's scope was never
// asked for here).
export function OpenApplicationsPage({ queue }: { queue: QueueState }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  function reloadApplications() {
    fetchOpenApplications()
      .then((applications) => setState({ kind: 'ready', applications }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load applications.'
        setState({ kind: 'error', message })
      })
  }

  useEffect(() => {
    reloadApplications()
  }, [])

  useEffect(() => {
    if (selectedId === null) return
    let cancelled = false
    fetchOpenApplicationDetail(selectedId)
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

  function reloadDetail() {
    if (selectedId === null) return
    fetchOpenApplicationDetail(selectedId)
      .then((data) => setDetailState({ kind: 'ready', id: selectedId, detail: data }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load this application.'
        setDetailState({ kind: 'error', id: selectedId, message })
      })
  }

  function backToList() {
    setSelectedId(null)
    reloadApplications()
  }

  // "Add Open Application" immediately queues Company details' Generate step (D-251) and lands
  // straight on this detail page, unlike Add Job's own overlay (which stays open showing a
  // RunTrace until the user clicks through) - so this page watches the queue itself and reloads
  // once that job (or any later one queued from here) finishes, instead of leaving the page
  // stale until the user navigates away and back.
  const selectedQueueStatus = selectedId === null ? 'idle' : openApplicationQueueStatusFor(queue.jobs, selectedId)
  useEffect(() => {
    if (selectedId === null) return
    if (selectedQueueStatus === 'idle') reloadDetail()
    // reloadDetail is stable in practice; the status transition is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedQueueStatus])

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
          <OpenApplicationDetailPage
            application={{
              ...current.detail,
              queue_status: openApplicationQueueStatusFor(queue.jobs, current.detail.id),
            }}
            onBack={backToList}
            onChanged={reloadDetail}
            onDeleted={backToList}
          />
        )}
      </>
    )
  }

  const applications = state.kind === 'ready' ? state.applications : []

  return (
    <section aria-labelledby="open-applications-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h1 id="open-applications-heading" className="text-xl font-semibold tracking-tight">
            Open Applications
          </h1>
          {state.kind === 'ready' && (
            <span className="font-mono text-xs text-muted-foreground">
              {applications.length} {applications.length === 1 ? 'application' : 'applications'}
            </span>
          )}
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="size-4" aria-hidden="true" />
          Add Open Application
        </Button>
      </div>

      <AddOpenApplicationOverlay
        open={addOpen}
        onOpenChange={setAddOpen}
        onCreated={reloadApplications}
        onOpenApplication={(applicationId) => setSelectedId(applicationId)}
      />

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading applications...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' && applications.length === 0 && (
        <p className="rounded border border-border p-6 text-center text-sm text-muted-foreground">
          No open applications yet - talent pools, unsolicited CV drops, or cold outreach.
        </p>
      )}

      {state.kind === 'ready' && applications.length > 0 && (
        <div className="overflow-x-auto rounded border border-border bg-card">
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className={HEAD}>Company</TableHead>
                <TableHead className={HEAD}>Target type</TableHead>
                <TableHead className={HEAD}>Status</TableHead>
                <TableHead className={HEAD}>Last updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {applications.map((app) => (
                <TableRow
                  key={app.id}
                  onClick={() => setSelectedId(app.id)}
                  className="cursor-pointer"
                >
                  <TableCell className="overflow-hidden">
                    <div className="flex items-center gap-1.5">
                      <QueueIndicator status={openApplicationQueueStatusFor(queue.jobs, app.id)} />
                      <span className="truncate font-medium">{app.target_name ?? '(unnamed)'}</span>
                    </div>
                  </TableCell>
                  <TableCell className="overflow-hidden text-sm text-muted-foreground">
                    {app.target_type ? TARGET_TYPE_LABELS[app.target_type] : '-'}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={app.status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{app.last_updated.slice(0, 10)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}
