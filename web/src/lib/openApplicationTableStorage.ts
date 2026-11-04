import type { ColumnSizingState, VisibilityState } from '@tanstack/react-table'

import type { Filters, SortState } from '@/components/app/OpenApplicationsTableFilters'
import { OPEN_APPLICATION_COLUMNS, type ColumnId } from '@/lib/openApplicationColumns'
import type { ViewId } from '@/lib/openApplicationViews'

// Mirrors jobTableStorage.ts (D-229), under its own key so it doesn't collide with the Job
// Applications table's own persisted state.
const STORAGE_KEY = 'ljt.openApplicationsView'

type PersistedFilterValue =
  | { kind: 'text'; selected: string[] }
  | { kind: 'date'; from: string | null; to: string | null }

export type PersistedTableState = {
  activeViewId: ViewId | 'custom'
  columnOrder: ColumnId[]
  columnVisibility: VisibilityState
  columnSizing: ColumnSizingState
  sort: SortState
  filters: Partial<Record<ColumnId, PersistedFilterValue>>
}

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

function isValidPersistedState(value: unknown): value is PersistedTableState {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  if (!Array.isArray(candidate.columnOrder)) return false
  const knownIds = new Set(OPEN_APPLICATION_COLUMNS.map((column) => column.id))
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
