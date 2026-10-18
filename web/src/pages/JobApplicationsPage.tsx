import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type VisibilityState,
} from '@tanstack/react-table'
import { Loader2, Plus, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { AddJobOverlay } from '@/components/app/AddJobOverlay'
import {
  ColumnFilterPopover,
  DEFAULT_FILTERS,
  SortableHeader,
  applicationMatchesFilters,
  compareApplications,
  cycleSort,
  filtersAreActive,
  type Filters,
  type SortState,
} from '@/components/app/JobsTableFilters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, fetchJobApplicationDetail, fetchJobApplications } from '@/lib/api'
import { COLUMN_BY_ID, DEFAULT_COLUMN_IDS, JOB_COLUMNS, type ColumnId } from '@/lib/jobColumns'
import type { JobApplication, JobApplicationDetailData, QueueStatus } from '@/lib/types'
import { queueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
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

// D-227: the per-row Claude Job indicator beside the company name, replacing the old Queue
// column entirely. Nothing renders for idle/done/cancelled - only a state that needs attention
// (processing, queued) or a stuck job (paused/failed) shows anything here.
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

function companyCell(app: JobApplication, status: QueueStatus) {
  return (
    <div className="flex items-center gap-1.5">
      <QueueIndicator status={status} />
      <div className="min-w-0 flex-1">{COLUMN_BY_ID.company.cell(app)}</div>
    </div>
  )
}

function buildTanstackColumns(queueJobs: QueueState['jobs']): ColumnDef<JobApplication>[] {
  return JOB_COLUMNS.map((column) => ({
    id: column.id,
    accessorFn: () => null,
    header: column.label,
    size: column.defaultWidth,
    minSize: 60,
    cell: ({ row }) =>
      column.id === 'company'
        ? companyCell(row.original, queueStatusFor(queueJobs, row.original.id))
        : column.cell(row.original),
  }))
}

function visibilityFor(visible: readonly ColumnId[]): VisibilityState {
  const state: VisibilityState = {}
  for (const column of JOB_COLUMNS) state[column.id] = visible.includes(column.id)
  return state
}

export function JobApplicationsPage({
  queue,
  resetSignal = 0,
}: {
  queue: QueueState
  // Bumped by App.tsx every time "Job Applications" is clicked in the sidebar, including while
  // this screen is already showing - the only way to tell "clicked again" apart from "nothing
  // happened," since the screen itself never changed. 0 means never clicked, the same
  // never-triggered convention RunTrace's own clearSignal uses.
  resetSignal?: number
}) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [addJobOpen, setAddJobOpen] = useState(false)
  const [sort, setSort] = useState<SortState>(null)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const [columnOrder] = useState<ColumnId[]>(() => JOB_COLUMNS.map((column) => column.id))
  const [columnVisibility] = useState<VisibilityState>(() => visibilityFor(DEFAULT_COLUMN_IDS))
  const [columnSizing] = useState({})

  const applications = useMemo<JobApplication[]>(
    () => (state.kind === 'ready' ? state.applications : []),
    [state]
  )
  const visibleApplications = useMemo(
    () =>
      applications
        .filter((app) => applicationMatchesFilters(app, filters))
        .sort((a, b) => compareApplications(a, b, sort)),
    [applications, filters, sort]
  )

  const tanstackColumns = useMemo(() => buildTanstackColumns(queue.jobs), [queue.jobs])
  const table = useReactTable({
    data: visibleApplications,
    columns: tanstackColumns,
    state: { columnOrder, columnVisibility, columnSizing },
    getRowId: (app) => String(app.id),
    getCoreRowModel: getCoreRowModel(),
  })
  const visibleColumnIds = table.getVisibleLeafColumns().map((column) => column.id as ColumnId)

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

  useEffect(() => {
    if (resetSignal === 0) return // the initial render, not an actual click
    backToList()
    // backToList is stable in practice; resetSignal's own change is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal])

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
              {filtersAreActive(filters) ? (
                <>
                  {visibleApplications.length} of {applications.length}
                </>
              ) : (
                <>
                  {applications.length} {applications.length === 1 ? 'application' : 'applications'}
                </>
              )}
            </span>
          )}
          {filtersAreActive(filters) && (
            <button
              type="button"
              onClick={() => setFilters(DEFAULT_FILTERS)}
              className="text-xs text-muted-foreground hover:text-foreground hover:underline"
            >
              Clear filters
            </button>
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

      {state.kind === 'ready' && applications.length === 0 && (
        <p className="rounded border border-border p-6 text-center text-sm text-muted-foreground">
          No job applications yet. To load synthetic ones, close this and run .\run.ps1 -Seed
        </p>
      )}

      {state.kind === 'ready' && applications.length > 0 && (
        <div className="overflow-x-auto rounded border border-border bg-card">
          <Table className="table-fixed">
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id} className="hover:bg-transparent">
                  {headerGroup.headers.map((header) => {
                    const columnId = header.column.id as ColumnId
                    return (
                      <TableHead
                        key={header.id}
                        className={HEAD}
                        style={{ width: header.getSize() }}
                      >
                        <div className="flex items-center gap-1 overflow-hidden">
                          <SortableHeader
                            column={columnId}
                            label={COLUMN_BY_ID[columnId].label}
                            sort={sort}
                            onSort={(c) => setSort(cycleSort(sort, c))}
                          />
                          <ColumnFilterPopover
                            column={columnId}
                            applications={applications}
                            filters={filters}
                            onChange={setFilters}
                          />
                        </div>
                      </TableHead>
                    )
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={visibleColumnIds.length} className="text-center text-sm text-muted-foreground">
                    No applications match the current filters.
                  </TableCell>
                </TableRow>
              )}
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  onClick={() => setSelectedId(row.original.id)}
                  className="cursor-pointer"
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className="overflow-hidden"
                      style={{ width: cell.column.getSize() }}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}
