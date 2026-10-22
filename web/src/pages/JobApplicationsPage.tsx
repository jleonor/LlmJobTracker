import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnSizingState,
  type VisibilityState,
} from '@tanstack/react-table'
import { Columns3, Loader2, Plus, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

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
import { Button, buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, fetchJobApplicationDetail, fetchJobApplications } from '@/lib/api'
import { COLUMN_BY_ID, DEFAULT_COLUMN_IDS, JOB_COLUMNS, type ColumnId } from '@/lib/jobColumns'
import { JOB_VIEWS, type JobView, type ViewId } from '@/lib/jobViews'
import {
  deserializeFilters,
  loadPersistedTableState,
  savePersistedTableState,
  serializeFilters,
} from '@/lib/jobTableStorage'
import type { JobApplication, JobApplicationDetailData, QueueStatus } from '@/lib/types'
import { queueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
import { cn } from '@/lib/utils'
import { JobApplicationDetailPage } from '@/pages/JobApplicationDetailPage'
import { OpenApplicationsPage } from '@/pages/OpenApplicationsPage'

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

// TanStack's columnOrder must list every column (visibility, not order, decides what's shown) -
// a view's own columns come first, in the order it names them, with the rest appended afterward
// in their registry order so nothing is ever missing from columnOrder.
function orderForView(columns: readonly ColumnId[]): ColumnId[] {
  const rest = JOB_COLUMNS.map((column) => column.id).filter((id) => !columns.includes(id))
  return [...columns, ...rest]
}

// D-227's "Select columns" - a checklist over all 27 columns (declaration order, so the list
// doesn't reshuffle as the user reorders the table itself), toggling columnVisibility.
function SelectColumnsPopover({
  visibility,
  onToggle,
}: {
  visibility: VisibilityState
  onToggle: (id: ColumnId, visible: boolean) => void
}) {
  const [search, setSearch] = useState('')
  const query = search.trim().toLowerCase()
  const visibleOptions = JOB_COLUMNS.filter(
    (column) => query === '' || column.label.toLowerCase().includes(query)
  )

  return (
    <Popover>
      <PopoverTrigger className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}>
        <Columns3 className="size-4" aria-hidden="true" />
        Select columns
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64">
        <Input
          placeholder="Search columns..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-7 text-xs"
        />
        <div className="flex max-h-72 flex-col gap-0.5 overflow-y-auto">
          {visibleOptions.map((column) => (
            <label
              key={column.id}
              className="flex items-center gap-2 rounded px-1 py-1 text-xs hover:bg-accent"
            >
              <Checkbox
                checked={visibility[column.id] ?? false}
                onCheckedChange={(checked) => onToggle(column.id, checked === true)}
              />
              <span className="flex-1 truncate">{column.label}</span>
            </label>
          ))}
          {visibleOptions.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">No matches.</p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
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
  // D-250: a toggle at the top of this page switches between the existing Job Applications
  // table/detail flow below and a second, separate Open Applications one - not a merged table.
  const [mode, setMode] = useState<'targeted' | 'open'>('targeted')
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [addJobOpen, setAddJobOpen] = useState(false)
  // D-229: read once on mount - whatever this run's sessionStorage held, or nothing on a fresh
  // app launch - and used to seed every piece of view state below.
  const [persisted] = useState(() => loadPersistedTableState())
  const [sort, setSort] = useState<SortState>(() => persisted?.sort ?? null)
  const [filters, setFilters] = useState<Filters>(() =>
    persisted ? deserializeFilters(persisted.filters) : DEFAULT_FILTERS
  )
  // D-227/D-230: which of the seven views is active, or 'custom' once the user resizes,
  // reorders or changes column selection away from a predefined one (sort/filter adjustments
  // alone don't fork - a view stays "active" with a different sort or filter applied).
  const [activeViewId, setActiveViewId] = useState<ViewId | 'custom'>(
    () => persisted?.activeViewId ?? 'default'
  )
  const [columnOrder, setColumnOrder] = useState<ColumnId[]>(
    () => persisted?.columnOrder ?? JOB_COLUMNS.map((column) => column.id)
  )
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    () => persisted?.columnVisibility ?? visibilityFor(DEFAULT_COLUMN_IDS)
  )
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(
    () => persisted?.columnSizing ?? {}
  )
  // Native HTML5 drag-and-drop (D-228: no second DnD library) - the column id currently being
  // dragged, read by the drop target to know what to move.
  const draggedColumn = useRef<ColumnId | null>(null)

  // D-229: written on every change to the view state, so the active view and any Custom
  // customization survive navigating around the app and reloading the page.
  useEffect(() => {
    savePersistedTableState({
      activeViewId,
      columnOrder,
      columnVisibility,
      columnSizing,
      sort,
      filters: serializeFilters(filters),
    })
  }, [activeViewId, columnOrder, columnVisibility, columnSizing, sort, filters])

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
    onColumnOrderChange: (updater) =>
      setColumnOrder((current) =>
        (typeof updater === 'function' ? updater(current) : updater) as ColumnId[]
      ),
    onColumnSizingChange: (updater) => {
      setColumnSizing(updater)
      setActiveViewId('custom')
    },
    onColumnVisibilityChange: setColumnVisibility,
    columnResizeMode: 'onChange',
    getRowId: (app) => String(app.id),
    getCoreRowModel: getCoreRowModel(),
  })
  const visibleColumnIds = table.getVisibleLeafColumns().map((column) => column.id as ColumnId)

  function toggleColumn(id: ColumnId, visible: boolean) {
    setColumnVisibility((current) => ({ ...current, [id]: visible }))
    setActiveViewId('custom')
  }

  function moveColumn(from: ColumnId, to: ColumnId) {
    if (from === to) return
    setColumnOrder((current) => {
      const next = [...current]
      const fromIndex = next.indexOf(from)
      const toIndex = next.indexOf(to)
      if (fromIndex === -1 || toIndex === -1) return current
      next.splice(fromIndex, 1)
      next.splice(toIndex, 0, from)
      return next
    })
    setActiveViewId('custom')
  }

  // D-227/D-230: switching views replaces columns/order/sizing/sort/filter atomically, using the
  // raw setters directly (never toggleColumn/moveColumn) so this never itself forks into Custom.
  function switchView(view: JobView) {
    setActiveViewId(view.id)
    setColumnOrder(orderForView(view.columns))
    setColumnVisibility(visibilityFor(view.columns))
    setColumnSizing({})
    setSort(view.sort)
    setFilters(view.filters)
  }

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
    setMode('targeted')
    backToList()
    // backToList is stable in practice; resetSignal's own change is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetSignal])

  const toggle = (
    <div className="flex gap-1.5">
      <button
        type="button"
        onClick={() => setMode('targeted')}
        className={cn(buttonVariants({ variant: mode === 'targeted' ? 'default' : 'outline', size: 'sm' }))}
      >
        Targeted applications
      </button>
      <button
        type="button"
        onClick={() => setMode('open')}
        className={cn(buttonVariants({ variant: mode === 'open' ? 'default' : 'outline', size: 'sm' }))}
      >
        Open applications
      </button>
    </div>
  )

  if (mode === 'open') {
    return (
      <div className="flex flex-col gap-4">
        {toggle}
        <OpenApplicationsPage queue={queue} />
      </div>
    )
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
      {toggle}
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

      {state.kind === 'ready' && applications.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {JOB_VIEWS.map((view) => {
              const Icon = view.icon
              return (
                <button
                  key={view.id}
                  type="button"
                  onClick={() => switchView(view)}
                  className={cn(
                    buttonVariants({
                      variant: activeViewId === view.id ? 'default' : 'outline',
                      size: 'sm',
                    })
                  )}
                >
                  <Icon className="size-3.5" aria-hidden="true" />
                  {view.label}
                </button>
              )
            })}
          </div>
          <SelectColumnsPopover visibility={columnVisibility} onToggle={toggleColumn} />
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
                        className={cn(HEAD, 'relative')}
                        style={{ width: header.getSize() }}
                      >
                        <div
                          draggable
                          onDragStart={() => {
                            draggedColumn.current = columnId
                          }}
                          onDragOver={(event) => event.preventDefault()}
                          onDrop={(event) => {
                            event.preventDefault()
                            if (draggedColumn.current) moveColumn(draggedColumn.current, columnId)
                            draggedColumn.current = null
                          }}
                          className="flex cursor-grab items-center gap-1 overflow-hidden active:cursor-grabbing"
                        >
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
                        <div
                          onMouseDown={header.getResizeHandler()}
                          onTouchStart={header.getResizeHandler()}
                          className={cn(
                            // A wider hit area than the visible bar (centered on the column
                            // boundary, D-227) - 1.5px alone proved too narrow to reliably grab.
                            'absolute top-0 -right-1.5 z-10 h-full w-3 cursor-col-resize touch-none select-none',
                            'after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent hover:after:bg-primary/50',
                            header.column.getIsResizing() && 'after:bg-primary'
                          )}
                        />
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
