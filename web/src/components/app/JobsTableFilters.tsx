import { ArrowDown, ArrowUp, ArrowUpDown, Filter } from 'lucide-react'
import { useState } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Slider } from '@/components/ui/slider'
import { cn } from '@/lib/utils'
import { QUEUE_STATUS_ORDER, STATUS_ORDER, type JobApplication, type QueueStatus } from '@/lib/types'

// The checklist value standing in for a null lane/location - an actual lane or location named
// this is not realistically possible, so no real value can collide with it.
export const UNSET = '(none)'

export type SortColumn =
  | 'company'
  | 'role_title'
  | 'lane'
  | 'location'
  | 'status'
  | 'last_updated'
  | 'match_score'
  | 'queue'

export type SortState = { column: SortColumn; direction: 'asc' | 'desc' } | null

export type Filters = {
  company: Set<string>
  role_title: Set<string>
  lane: Set<string>
  location: Set<string>
  status: Set<string>
  queue: Set<QueueStatus>
  lastUpdatedFrom: string | null
  lastUpdatedTo: string | null
  matchScoreMin: number
  matchScoreMax: number
  includeUnscored: boolean
}

export const DEFAULT_FILTERS: Filters = {
  company: new Set(),
  role_title: new Set(),
  lane: new Set(),
  location: new Set(),
  status: new Set(),
  queue: new Set(),
  lastUpdatedFrom: null,
  lastUpdatedTo: null,
  matchScoreMin: 0,
  matchScoreMax: 100,
  includeUnscored: true,
}

export type FilterOption = { value: string; label: string; count: number }

// Distinct values actually present in the data, alphabetical, with a null tally appended last as
// the UNSET option - used for Company, Title, Lane and Location, none of which has a closed set
// of possible values.
export function textOptions(values: (string | null)[]): FilterOption[] {
  const counts = new Map<string, number>()
  let nullCount = 0
  for (const value of values) {
    if (value === null) {
      nullCount += 1
      continue
    }
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  const options = [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([value, count]) => ({ value, label: value, count }))
  if (nullCount > 0) options.push({ value: UNSET, label: UNSET, count: nullCount })
  return options
}

// Every value in `order` is listed, even with a zero count - used for Status and Queue, both a
// closed, defined set (D-44/D-101's stages; the queue's own lifecycle), so the checklist stays
// the same regardless of what the current data happens to contain.
export function orderedOptions<T extends string>(order: readonly T[], values: string[]): FilterOption[] {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  return order.map((value) => ({ value, label: value, count: counts.get(value) ?? 0 }))
}

export function filtersAreActive(filters: Filters): boolean {
  return (
    filters.company.size > 0 ||
    filters.role_title.size > 0 ||
    filters.lane.size > 0 ||
    filters.location.size > 0 ||
    filters.status.size > 0 ||
    filters.queue.size > 0 ||
    filters.lastUpdatedFrom !== null ||
    filters.lastUpdatedTo !== null ||
    filters.matchScoreMin !== DEFAULT_FILTERS.matchScoreMin ||
    filters.matchScoreMax !== DEFAULT_FILTERS.matchScoreMax ||
    !filters.includeUnscored
  )
}

export function applicationMatchesFilters(
  app: JobApplication,
  queueStatus: QueueStatus,
  filters: Filters
): boolean {
  if (filters.company.size > 0 && !filters.company.has(app.company)) return false
  if (filters.role_title.size > 0 && !filters.role_title.has(app.role_title)) return false
  if (filters.lane.size > 0 && !filters.lane.has(app.lane ?? UNSET)) return false
  if (filters.location.size > 0 && !filters.location.has(app.location ?? UNSET)) return false
  if (filters.status.size > 0 && !filters.status.has(app.status)) return false
  if (filters.queue.size > 0 && !filters.queue.has(queueStatus)) return false
  const day = app.last_updated.slice(0, 10)
  if (filters.lastUpdatedFrom && day < filters.lastUpdatedFrom) return false
  if (filters.lastUpdatedTo && day > filters.lastUpdatedTo) return false
  if (app.match_score === null) {
    if (!filters.includeUnscored) return false
  } else {
    const rounded = Math.round(app.match_score)
    if (rounded < filters.matchScoreMin || rounded > filters.matchScoreMax) return false
  }
  return true
}

// Null always sorts last, in either direction - an unset lane/location/score is "unknown", not
// "least", so flipping the direction shouldn't move it to the front.
function compareNullableStrings(a: string | null, b: string | null, direction: 1 | -1): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return direction * a.localeCompare(b)
}

function compareNullableNumbers(a: number | null, b: number | null, direction: 1 | -1): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return direction * (a - b)
}

export function compareApplications(
  a: { app: JobApplication; queue: QueueStatus },
  b: { app: JobApplication; queue: QueueStatus },
  sort: SortState
): number {
  if (!sort) return 0
  const direction = sort.direction === 'asc' ? 1 : -1
  switch (sort.column) {
    case 'company':
      return direction * a.app.company.localeCompare(b.app.company)
    case 'role_title':
      return direction * a.app.role_title.localeCompare(b.app.role_title)
    case 'lane':
      return compareNullableStrings(a.app.lane, b.app.lane, direction)
    case 'location':
      return compareNullableStrings(a.app.location, b.app.location, direction)
    case 'status':
      return (
        direction *
        ((STATUS_ORDER as readonly string[]).indexOf(a.app.status) -
          (STATUS_ORDER as readonly string[]).indexOf(b.app.status))
      )
    case 'last_updated':
      return direction * a.app.last_updated.localeCompare(b.app.last_updated)
    case 'match_score':
      return compareNullableNumbers(a.app.match_score, b.app.match_score, direction)
    case 'queue':
      return direction * (QUEUE_STATUS_ORDER.indexOf(a.queue) - QUEUE_STATUS_ORDER.indexOf(b.queue))
  }
}

// Clicking an unsorted column sorts it ascending; clicking the active column flips direction;
// clicking it again (now descending) clears the sort back to the table's natural order.
export function cycleSort(previous: SortState, column: SortColumn): SortState {
  if (previous?.column !== column) return { column, direction: 'asc' }
  if (previous.direction === 'asc') return { column, direction: 'desc' }
  return null
}

export function SortableHeader({
  column,
  label,
  sort,
  onSort,
}: {
  column: SortColumn
  label: string
  sort: SortState
  onSort: (column: SortColumn) => void
}) {
  const active = sort?.column === column
  const Icon = !active ? ArrowUpDown : sort.direction === 'asc' ? ArrowUp : ArrowDown
  return (
    <button
      type="button"
      onClick={() => onSort(column)}
      className={cn(
        'inline-flex items-center gap-1 hover:text-foreground',
        active && 'text-foreground'
      )}
    >
      {label}
      <Icon className={cn('size-3', !active && 'text-muted-foreground/50')} aria-hidden="true" />
    </button>
  )
}

function FilterTrigger({ active, label }: { active: boolean; label: string }) {
  return (
    <PopoverTrigger
      aria-label={`Filter ${label}`}
      className={cn(
        buttonVariants({ variant: 'ghost', size: 'icon-xs' }),
        active ? 'text-primary' : 'text-muted-foreground/50'
      )}
    >
      <Filter className="size-3" aria-hidden="true" />
    </PopoverTrigger>
  )
}

export function TextFilterPopover({
  label,
  options,
  selected,
  onChange,
}: {
  label: string
  // Already in the order the checklist should display (alphabetical, or a defined stage order).
  options: { value: string; label: string; count: number }[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
}) {
  const [search, setSearch] = useState('')
  const visible =
    search.trim() === ''
      ? options
      : options.filter((option) => option.label.toLowerCase().includes(search.trim().toLowerCase()))
  const active = selected.size > 0

  function toggle(value: string) {
    const next = new Set(selected)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    onChange(next)
  }

  return (
    <Popover>
      <FilterTrigger active={active} label={label} />
      <PopoverContent align="start" className="w-56">
        {options.length > 6 && (
          <Input
            placeholder={`Search ${label.toLowerCase()}...`}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-7 text-xs"
          />
        )}
        <div className="flex max-h-56 flex-col gap-0.5 overflow-y-auto">
          {visible.map((option) => (
            <label
              key={option.value}
              className="flex items-center gap-2 rounded px-1 py-1 text-xs hover:bg-accent"
            >
              <Checkbox
                checked={selected.has(option.value)}
                onCheckedChange={() => toggle(option.value)}
              />
              <span className="flex-1 truncate">{option.label}</span>
              <span className="font-mono text-[10px] text-muted-foreground">{option.count}</span>
            </label>
          ))}
          {visible.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted-foreground">No matches.</p>
          )}
        </div>
        {active && (
          <button
            type="button"
            onClick={() => onChange(new Set())}
            className="self-start text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Clear filter
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}

export function DateRangeFilterPopover({
  label,
  from,
  to,
  onChange,
}: {
  label: string
  from: string | null
  to: string | null
  onChange: (from: string | null, to: string | null) => void
}) {
  const active = from !== null || to !== null
  return (
    <Popover>
      <FilterTrigger active={active} label={label} />
      <PopoverContent align="start" className="w-64">
        <div className="flex flex-col gap-1.5">
          <label className="text-xs text-muted-foreground">
            From
            <Input
              type="date"
              value={from ?? ''}
              onChange={(event) => onChange(event.target.value || null, to)}
              className="mt-0.5 h-7 text-xs"
            />
          </label>
          <label className="text-xs text-muted-foreground">
            To
            <Input
              type="date"
              value={to ?? ''}
              onChange={(event) => onChange(from, event.target.value || null)}
              className="mt-0.5 h-7 text-xs"
            />
          </label>
        </div>
        {active && (
          <button
            type="button"
            onClick={() => onChange(null, null)}
            className="self-start text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Clear filter
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}

export function MatchScoreFilterPopover({
  label,
  min,
  max,
  includeUnscored,
  onChange,
}: {
  label: string
  min: number
  max: number
  includeUnscored: boolean
  onChange: (min: number, max: number, includeUnscored: boolean) => void
}) {
  const active =
    min !== DEFAULT_FILTERS.matchScoreMin ||
    max !== DEFAULT_FILTERS.matchScoreMax ||
    !includeUnscored

  return (
    <Popover>
      <FilterTrigger active={active} label={label} />
      <PopoverContent align="start" className="w-64">
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between font-mono text-xs text-muted-foreground">
            <span>{min}%</span>
            <span>{max}%</span>
          </div>
          <Slider
            value={[min, max]}
            min={0}
            max={100}
            onValueChange={(value) => {
              const [lo, hi] = value as number[]
              onChange(lo, hi, includeUnscored)
            }}
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Checkbox
              checked={includeUnscored}
              onCheckedChange={(checked) => onChange(min, max, checked)}
            />
            Include not yet scored
          </label>
        </div>
        {active && (
          <button
            type="button"
            onClick={() =>
              onChange(DEFAULT_FILTERS.matchScoreMin, DEFAULT_FILTERS.matchScoreMax, true)
            }
            className="self-start text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Clear filter
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}
