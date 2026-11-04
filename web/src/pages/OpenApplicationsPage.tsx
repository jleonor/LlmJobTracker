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

import { AddOpenApplicationOverlay } from '@/components/app/AddOpenApplicationOverlay'
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
} from '@/components/app/OpenApplicationsTableFilters'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ApiError, fetchOpenApplicationDetail, fetchOpenApplications } from '@/lib/api'
import {
  COLUMN_BY_ID,
  DEFAULT_COLUMN_IDS,
  OPEN_APPLICATION_COLUMNS,
  type ColumnId,
} from '@/lib/openApplicationColumns'
import {
  deserializeFilters,
  loadPersistedTableState,
  savePersistedTableState,
  serializeFilters,
} from '@/lib/openApplicationTableStorage'
import { OPEN_APPLICATION_VIEWS, type OpenApplicationView, type ViewId } from '@/lib/openApplicationViews'
import { QUEUE_STATUS_TEXT } from '@/lib/tone'
import type { OpenApplication, OpenApplicationDetailData, QueueStatus } from '@/lib/types'
import { openApplicationQueueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
import { cn } from '@/lib/utils'
import { OpenApplicationDetailPage } from '@/pages/OpenApplicationDetailPage'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; applications: OpenApplication[] }

type DetailState =
  | { kind: 'error'; id: number; message: string }
  | { kind: 'ready'; id: number; detail: OpenApplicationDetailData }

const HEAD = 'font-mono text-[10px] uppercase tracking-wider'

// D-298 (Phase 17): mirrors JobApplicationsPage.tsx's own QueueIndicator, including the 'staged'
// state the original, pre-registry version of this table never handled (D-296 gives Open
// Applications their own staged workflow chains now, the same way Add Job already had one).
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
  if (status === 'staged') {
    return (
      <Tooltip>
        <TooltipTrigger render={<span />} className="inline-flex shrink-0 cursor-default">
          <Badge
            variant="outline"
            className={cn('rounded-sm font-mono text-[10px] font-normal', QUEUE_STATUS_TEXT.staged)}
          >
            Staged
          </Badge>
        </TooltipTrigger>
        <TooltipContent>Staged - waiting on Trigger workflows</TooltipContent>
      </Tooltip>
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

function targetNameCell(app: OpenApplication, status: QueueStatus) {
  return (
    <div className="flex items-center gap-1.5">
      <QueueIndicator status={status} />
      <div className="min-w-0 flex-1">{COLUMN_BY_ID.target_name.cell(app)}</div>
    </div>
  )
}

function buildTanstackColumns(queueJobs: QueueState['jobs']): ColumnDef<OpenApplication>[] {
  return OPEN_APPLICATION_COLUMNS.map((column) => ({
    id: column.id,
    accessorFn: () => null,
    header: column.label,
    size: column.defaultWidth,
    minSize: 60,
    cell: ({ row }) =>
      column.id === 'target_name'
        ? targetNameCell(row.original, openApplicationQueueStatusFor(queueJobs, row.original.id))
        : column.cell(row.original),
  }))
}

function visibilityFor(visible: readonly ColumnId[]): VisibilityState {
  const state: VisibilityState = {}
  for (const column of OPEN_APPLICATION_COLUMNS) state[column.id] = visible.includes(column.id)
  return state
}

function orderForView(columns: readonly ColumnId[]): ColumnId[] {
  const rest = OPEN_APPLICATION_COLUMNS.map((column) => column.id).filter(
    (id) => !columns.includes(id)
  )
  return [...columns, ...rest]
}

function SelectColumnsPopover({
  visibility,
  onToggle,
}: {
  visibility: VisibilityState
  onToggle: (id: ColumnId, visible: boolean) => void
}) {
  const [search, setSearch] = useState('')
  const query = search.trim().toLowerCase()
  const visibleOptions = OPEN_APPLICATION_COLUMNS.filter(
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

// A second table, deliberately simpler than the Job Applications one (D-250): no Lane or Match
// score columns, since neither exists for this entity (D-249). D-298 (Phase 17) brings the same
// column-registry/resize/reorder/"Select columns"/saved-views mechanism Phase 9 gave Job
// Applications, trimmed to this entity's own fields.
export function OpenApplicationsPage({ queue }: { queue: QueueState }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailState, setDetailState] = useState<DetailState | null>(null)
  const [addOpen, setAddOpen] = useState(false)

  const [persisted] = useState(() => loadPersistedTableState())
  const [sort, setSort] = useState<SortState>(() => persisted?.sort ?? null)
  const [filters, setFilters] = useState<Filters>(() =>
    persisted ? deserializeFilters(persisted.filters) : DEFAULT_FILTERS
  )
  const [activeViewId, setActiveViewId] = useState<ViewId | 'custom'>(
    () => persisted?.activeViewId ?? 'default'
  )
  const [columnOrder, setColumnOrder] = useState<ColumnId[]>(
    () => persisted?.columnOrder ?? OPEN_APPLICATION_COLUMNS.map((column) => column.id)
  )
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    () => persisted?.columnVisibility ?? visibilityFor(DEFAULT_COLUMN_IDS)
  )
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(
    () => persisted?.columnSizing ?? {}
  )
  const draggedColumn = useRef<ColumnId | null>(null)

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

  // "Add Open Application" now stages its chosen workflow chain (D-296) instead of always
  // queueing Company details immediately, so this page watches the queue and reloads once
  // whatever is in flight for the selected application finishes, the same way it already did.
  const selectedQueueStatus = selectedId === null ? 'idle' : openApplicationQueueStatusFor(queue.jobs, selectedId)
  useEffect(() => {
    if (selectedId === null) return
    if (selectedQueueStatus === 'idle') reloadDetail()
    // reloadDetail is stable in practice; the status transition is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selectedQueueStatus])

  const applications = useMemo<OpenApplication[]>(
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

  function switchView(view: OpenApplicationView) {
    setActiveViewId(view.id)
    setColumnOrder(orderForView(view.columns))
    setColumnVisibility(visibilityFor(view.columns))
    setColumnSizing({})
    setSort(view.sort)
    setFilters(typeof view.filters === 'function' ? view.filters(new Date()) : view.filters)
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

  return (
    <section aria-labelledby="open-applications-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-3">
          <h1 id="open-applications-heading" className="text-xl font-semibold tracking-tight">
            Open Applications
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

      {state.kind === 'ready' && applications.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {OPEN_APPLICATION_VIEWS.map((view) => {
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
          No open applications yet - talent pools, unsolicited CV drops, or cold outreach.
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
