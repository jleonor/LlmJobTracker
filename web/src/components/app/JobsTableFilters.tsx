import { ArrowDown, ArrowUp, ArrowUpDown, Filter } from 'lucide-react'
import { useState } from 'react'

import { buttonVariants } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Slider } from '@/components/ui/slider'
import { COLUMN_BY_ID, UNSET, type ColumnId } from '@/lib/jobColumns'
import { cn } from '@/lib/utils'
import type { JobApplication } from '@/lib/types'

export type SortState = { column: ColumnId; direction: 'asc' | 'desc' } | null

// D-227: one filter value per column kind, keyed by whichever columns the active view actually
// shows - unlike the pre-D-227 fixed `Filters` shape, a column not currently visible simply has
// no entry here.
export type FilterValue =
  | { kind: 'text'; selected: Set<string> }
  | { kind: 'date'; from: string | null; to: string | null }
  | { kind: 'score'; min: number; max: number; includeUnscored: boolean }

export type Filters = Partial<Record<ColumnId, FilterValue>>

export const DEFAULT_FILTERS: Filters = {}

export type FilterOption = { value: string; label: string; count: number }

// Distinct values actually present in the data, alphabetical, with a null tally appended last as
// the UNSET option - used for every free-text column (Company, Title, Lane, Location, Job
// portal, Next action, Notes), none of which has a closed set of possible values.
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

// Every value in `order` is listed, even with a zero count - used for Status and every "status
// flag" column (Done/Not done), both closed, defined sets, so the checklist stays the same
// regardless of what the current data happens to contain.
export function orderedOptions(order: readonly string[], values: string[]): FilterOption[] {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  return order.map((value) => ({ value, label: value, count: counts.get(value) ?? 0 }))
}

export function optionsForColumn(column: ColumnId, applications: JobApplication[]): FilterOption[] {
  const spec = COLUMN_BY_ID[column].filter
  if (!spec) return []
  if (spec.kind === 'text') return textOptions(applications.map(spec.value))
  if (spec.kind === 'ordered') return orderedOptions(spec.order, applications.map(spec.value))
  return []
}

export function filtersAreActive(filters: Filters): boolean {
  return Object.values(filters).some((value) => {
    if (!value) return false
    if (value.kind === 'text') return value.selected.size > 0
    if (value.kind === 'date') return value.from !== null || value.to !== null
    return value.min !== 0 || value.max !== 100 || !value.includeUnscored
  })
}

export function applicationMatchesFilters(app: JobApplication, filters: Filters): boolean {
  for (const key of Object.keys(filters)) {
    const value = filters[key as ColumnId]
    if (!value) continue
    const spec = COLUMN_BY_ID[key as ColumnId].filter
    if (!spec) continue
    if (spec.kind === 'text' || spec.kind === 'ordered') {
      if (value.kind !== 'text') continue
      if (value.selected.size === 0) continue
      const raw = spec.value(app)
      if (!value.selected.has(raw ?? UNSET)) return false
    } else if (spec.kind === 'date') {
      if (value.kind !== 'date') continue
      const raw = spec.value(app)
      const day = raw ? raw.slice(0, 10) : null
      if (value.from && (!day || day < value.from)) return false
      if (value.to && (!day || day > value.to)) return false
    } else if (spec.kind === 'score') {
      if (value.kind !== 'score') continue
      if (app.match_score === null) {
        if (!value.includeUnscored) return false
      } else {
        const rounded = Math.round(app.match_score)
        if (rounded < value.min || rounded > value.max) return false
      }
    }
  }
  return true
}

export function compareApplications(a: JobApplication, b: JobApplication, sort: SortState): number {
  if (!sort) return 0
  const column = COLUMN_BY_ID[sort.column]
  const direction = sort.direction === 'asc' ? 1 : -1
  return column.compare(a, b, direction)
}

// Clicking an unsorted column sorts it ascending; clicking the active column flips direction;
// clicking it again (now descending) clears the sort back to the table's natural order.
export function cycleSort(previous: SortState, column: ColumnId): SortState {
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
  column: ColumnId
  label: string
  sort: SortState
  onSort: (column: ColumnId) => void
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

const SCORE_MIN = 0
const SCORE_MAX = 100

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
  const active = min !== SCORE_MIN || max !== SCORE_MAX || !includeUnscored

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
            onClick={() => onChange(SCORE_MIN, SCORE_MAX, true)}
            className="self-start text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            Clear filter
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}

// Renders the right filter popover for a visible column, reading/writing its slice of `Filters`
// - the one place that bridges the registry's column-agnostic FilterSpec onto the three concrete
// popover components above.
export function ColumnFilterPopover({
  column,
  applications,
  filters,
  onChange,
}: {
  column: ColumnId
  applications: JobApplication[]
  filters: Filters
  onChange: (next: Filters) => void
}) {
  const definition = COLUMN_BY_ID[column]
  const spec = definition.filter
  if (!spec) return null
  const current = filters[column]

  if (spec.kind === 'text' || spec.kind === 'ordered') {
    const selected = current?.kind === 'text' ? current.selected : new Set<string>()
    return (
      <TextFilterPopover
        label={definition.label}
        options={optionsForColumn(column, applications)}
        selected={selected}
        onChange={(next) => onChange({ ...filters, [column]: { kind: 'text', selected: next } })}
      />
    )
  }
  if (spec.kind === 'date') {
    const from = current?.kind === 'date' ? current.from : null
    const to = current?.kind === 'date' ? current.to : null
    return (
      <DateRangeFilterPopover
        label={definition.label}
        from={from}
        to={to}
        onChange={(from, to) => onChange({ ...filters, [column]: { kind: 'date', from, to } })}
      />
    )
  }
  const min = current?.kind === 'score' ? current.min : SCORE_MIN
  const max = current?.kind === 'score' ? current.max : SCORE_MAX
  const includeUnscored = current?.kind === 'score' ? current.includeUnscored : true
  return (
    <MatchScoreFilterPopover
      label={definition.label}
      min={min}
      max={max}
      includeUnscored={includeUnscored}
      onChange={(min, max, includeUnscored) =>
        onChange({ ...filters, [column]: { kind: 'score', min, max, includeUnscored } })
      }
    />
  )
}
