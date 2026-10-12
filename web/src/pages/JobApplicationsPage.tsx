import { Plus } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { AddJobOverlay } from '@/components/app/AddJobOverlay'
import {
  DEFAULT_FILTERS,
  DateRangeFilterPopover,
  MatchScoreFilterPopover,
  SortableHeader,
  TextFilterPopover,
  applicationMatchesFilters,
  compareApplications,
  cycleSort,
  filtersAreActive,
  orderedOptions,
  textOptions,
  type Filters,
  type SortState,
} from '@/components/app/JobsTableFilters'
import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { RunnerCheck } from '@/components/app/RunnerCheck'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError, fetchJobApplicationDetail, fetchJobApplications } from '@/lib/api'
import { queueStatusFor, type QueueState } from '@/lib/useClaudeJobs'
import { STATUS_ORDER, QUEUE_STATUS_ORDER, type JobApplication, type JobApplicationDetailData } from '@/lib/types'
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

  const applications = useMemo<JobApplication[]>(
    () => (state.kind === 'ready' ? state.applications : []),
    [state]
  )
  // Each row's live queue status, computed once per render alongside the application it belongs
  // to, so sorting/filtering by Queue and the table's own badge always agree.
  const rows = useMemo(
    () => applications.map((app) => ({ app, queue: queueStatusFor(queue.jobs, app.id) })),
    [applications, queue.jobs]
  )
  const visibleRows = useMemo(
    () =>
      rows
        .filter((row) => applicationMatchesFilters(row.app, row.queue, filters))
        .sort((a, b) => compareApplications(a, b, sort)),
    [rows, filters, sort]
  )
  // Option lists reflect the full, unfiltered set, not just what the other filters currently
  // allow through - simpler, and stays stable while a filter popover is open.
  const companyOptions = useMemo(() => textOptions(applications.map((app) => app.company)), [applications])
  const titleOptions = useMemo(() => textOptions(applications.map((app) => app.role_title)), [applications])
  const laneOptions = useMemo(() => textOptions(applications.map((app) => app.lane)), [applications])
  const locationOptions = useMemo(() => textOptions(applications.map((app) => app.location)), [applications])
  const statusOptions = useMemo(
    () => orderedOptions(STATUS_ORDER, applications.map((app) => app.status)),
    [applications]
  )
  const queueOptions = useMemo(
    () => orderedOptions(QUEUE_STATUS_ORDER, rows.map((row) => row.queue)),
    [rows]
  )

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
                  {visibleRows.length} of {applications.length}
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
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="company" label="Company" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Company"
                      options={companyOptions}
                      selected={filters.company}
                      onChange={(next) => setFilters((f) => ({ ...f, company: next }))}
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="role_title" label="Title" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Title"
                      options={titleOptions}
                      selected={filters.role_title}
                      onChange={(next) => setFilters((f) => ({ ...f, role_title: next }))}
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="lane" label="Lane" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Lane"
                      options={laneOptions}
                      selected={filters.lane}
                      onChange={(next) => setFilters((f) => ({ ...f, lane: next }))}
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="location" label="Location" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Location"
                      options={locationOptions}
                      selected={filters.location}
                      onChange={(next) => setFilters((f) => ({ ...f, location: next }))}
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="status" label="Status" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Status"
                      options={statusOptions}
                      selected={filters.status}
                      onChange={(next) => setFilters((f) => ({ ...f, status: next }))}
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader
                      column="last_updated"
                      label="Last updated"
                      sort={sort}
                      onSort={(c) => setSort(cycleSort(sort, c))}
                    />
                    <DateRangeFilterPopover
                      label="Last updated"
                      from={filters.lastUpdatedFrom}
                      to={filters.lastUpdatedTo}
                      onChange={(from, to) =>
                        setFilters((f) => ({ ...f, lastUpdatedFrom: from, lastUpdatedTo: to }))
                      }
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader
                      column="match_score"
                      label="Match score"
                      sort={sort}
                      onSort={(c) => setSort(cycleSort(sort, c))}
                    />
                    <MatchScoreFilterPopover
                      label="Match score"
                      min={filters.matchScoreMin}
                      max={filters.matchScoreMax}
                      includeUnscored={filters.includeUnscored}
                      onChange={(min, max, includeUnscored) =>
                        setFilters((f) => ({ ...f, matchScoreMin: min, matchScoreMax: max, includeUnscored }))
                      }
                    />
                  </div>
                </TableHead>
                <TableHead className={HEAD}>
                  <div className="flex items-center gap-1">
                    <SortableHeader column="queue" label="Queue" sort={sort} onSort={(c) => setSort(cycleSort(sort, c))} />
                    <TextFilterPopover
                      label="Queue"
                      options={queueOptions}
                      selected={filters.queue}
                      onChange={(next) =>
                        setFilters((f) => ({ ...f, queue: next as Filters['queue'] }))
                      }
                    />
                  </div>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleRows.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={8} className="text-center text-sm text-muted-foreground">
                    No applications match the current filters.
                  </TableCell>
                </TableRow>
              )}
              {visibleRows.map(({ app, queue: queueStatus }) => (
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
                    <QueueStatusBadge status={queueStatus} />
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
