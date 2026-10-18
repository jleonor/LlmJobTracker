import type { ColumnSizingState, VisibilityState } from '@tanstack/react-table'

import type { Filters, SortState } from '@/components/app/JobsTableFilters'
import { JOB_COLUMNS, type ColumnId } from '@/lib/jobColumns'
import type { ViewId } from '@/lib/jobViews'

// D-229: the active view and any Custom customization persist in sessionStorage - read on
// mount, written on change, with no migration back to Default except a fresh app launch (a new
// sessionStorage). Not localStorage: the user's own choice, confirmed when asked, is that the
// view should survive navigation and reload within a run of the app, but always start over at
// Default the next time the app itself is run.
const STORAGE_KEY = 'ljt.jobApplicationsView'

type PersistedFilterValue =
  | { kind: 'text'; selected: string[] }
  | { kind: 'date'; from: string | null; to: string | null }
  | { kind: 'score'; min: number; max: number; includeUnscored: boolean }

export type PersistedTableState = {
  activeViewId: ViewId | 'custom'
  columnOrder: ColumnId[]
  columnVisibility: VisibilityState
  columnSizing: ColumnSizingState
  sort: SortState
  filters: Partial<Record<ColumnId, PersistedFilterValue>>
}

// Filters' Set values aren't directly JSON-serializable.
export function serializeFilters(filters: Filters): PersistedTableState['filters'] {
  const result: PersistedTableState['filters'] = {}
  for (const key of Object.keys(filters)) {
    const value = filters[key as ColumnId]
    if (!value) continue
    result[key as ColumnId] =
      value.kind === 'text' ? { kind: 'text', selected: [...value.selected] } : value
  }
  return result
}

export function deserializeFilters(raw: PersistedTableState['filters']): Filters {
  const result: Filters = {}
  for (const key of Object.keys(raw)) {
    const value = raw[key as ColumnId]
    if (!value) continue
    result[key as ColumnId] =
      value.kind === 'text' ? { kind: 'text', selected: new Set(value.selected) } : value
  }
  return result
}

// A loose but real shape check - just enough that a stale or corrupted value falls back to
// Default instead of crashing the page; not a guarantee the rest of the shape is perfect.
function isValidPersistedState(value: unknown): value is PersistedTableState {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  if (!Array.isArray(candidate.columnOrder)) return false
  const knownIds = new Set(JOB_COLUMNS.map((column) => column.id))
  if (candidate.columnOrder.length !== knownIds.size) return false
  return candidate.columnOrder.every((id) => knownIds.has(id as ColumnId))
}

export function loadPersistedTableState(): PersistedTableState | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isValidPersistedState(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function savePersistedTableState(state: PersistedTableState): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // A full storage quota or a private-browsing restriction just means this run doesn't
    // persist - the table still works, it only forgets its view on the next reload.
  }
}
