import {
  Activity,
  Archive,
  CalendarClock,
  History,
  Home,
  ListChecks,
  Send,
  Snowflake,
  type LucideIcon,
} from 'lucide-react'

import type { Filters, SortState } from '@/components/app/OpenApplicationsTableFilters'
import { DEFAULT_COLUMN_IDS, type ColumnId } from '@/lib/openApplicationColumns'
import { OPEN_APPLICATION_STATUS_ORDER } from '@/lib/types'

// D-298 (Phase 17), correcting the original decision's own undercount (D-299-style correction -
// Job Applications actually has seven predefined views, Cold applications (Phase 14) included,
// not six): Default plus the same seven, mimicked as closely as this entity's own fields allow.
// "To apply to" has no Match score to sort by (D-249), so it sorts by Last updated instead - the
// one deliberate difference from Job's own view.
export type ViewId =
  | 'default'
  | 'to_apply_to'
  | 'active_applications'
  | 'cold_applications'
  | 'dead_applications'
  | 'upcoming_actions'
  | 'processing_status'
  | 'history_dates'

export type OpenApplicationView = {
  id: ViewId
  label: string
  icon: LucideIcon
  columns: readonly ColumnId[]
  sort: SortState
  filters: Filters | ((now: Date) => Filters)
}

function statusFilter(statuses: string[]): Filters {
  return { status: { kind: 'text', selected: new Set(statuses) } }
}

const HAS_NEXT_ACTION_DATE: Filters = {
  next_action_date: { kind: 'date', from: '1970-01-01', to: null },
}

// Matches jobViews.tsx's own 30-day cutoff (D-275), applied here for Active/Cold's own split.
const STALE_AFTER_DAYS = 30

function daysAgoDateKey(now: Date, days: number): string {
  const date = new Date(now)
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

const DEAD_STATUSES = ['Rejected', 'Withdrawn', 'Expired']
const NON_DEAD_STATUSES = OPEN_APPLICATION_STATUS_ORDER.filter(
  (status) => !DEAD_STATUSES.includes(status)
)

export const OPEN_APPLICATION_VIEWS: readonly OpenApplicationView[] = [
  {
    id: 'default',
    label: 'Default',
    icon: Home,
    columns: DEFAULT_COLUMN_IDS,
    sort: null,
    filters: {},
  },
  {
    id: 'to_apply_to',
    label: 'To apply to',
    icon: Send,
    columns: ['target_name', 'target_type', 'status', 'last_updated'],
    sort: { column: 'last_updated', direction: 'desc' },
    filters: statusFilter(['Identified']),
  },
  {
    id: 'active_applications',
    label: 'Active applications',
    icon: Activity,
    columns: ['target_name', 'target_type', 'status', 'last_updated'],
    sort: { column: 'last_updated', direction: 'desc' },
    // In progress (Applied, the only non-terminal status besides Identified) and touched within
    // the last 30 days - mirrors Job Applications' own Active/Cold split (D-275).
    filters: (now) => ({
      ...statusFilter(['Applied']),
      last_updated: { kind: 'date', from: daysAgoDateKey(now, STALE_AFTER_DAYS), to: null },
    }),
  },
  {
    id: 'cold_applications',
    label: 'Cold applications',
    icon: Snowflake,
    columns: ['target_name', 'target_type', 'status', 'last_updated'],
    sort: { column: 'last_updated', direction: 'asc' },
    filters: (now) => ({
      ...statusFilter([...NON_DEAD_STATUSES]),
      last_updated: { kind: 'date', from: null, to: daysAgoDateKey(now, STALE_AFTER_DAYS) },
    }),
  },
  {
    id: 'dead_applications',
    label: 'Dead applications',
    icon: Archive,
    columns: ['target_name', 'target_type', 'status', 'notes'],
    sort: { column: 'last_updated', direction: 'desc' },
    filters: statusFilter(DEAD_STATUSES),
  },
  {
    id: 'upcoming_actions',
    label: 'Upcoming actions',
    icon: CalendarClock,
    columns: ['target_name', 'target_type', 'status', 'next_action_date', 'next_action'],
    sort: { column: 'next_action_date', direction: 'asc' },
    filters: { ...statusFilter(['Applied']), ...HAS_NEXT_ACTION_DATE },
  },
  {
    id: 'processing_status',
    label: 'Processing status',
    icon: ListChecks,
    columns: [
      'target_name',
      'target_type',
      'status',
      'sources_status',
      'company_details_status',
      'cv_status',
      'cover_letter_status',
      'introduction_message_status',
    ],
    sort: null,
    filters: {},
  },
  {
    id: 'history_dates',
    label: 'History dates',
    icon: History,
    columns: [
      'target_name',
      'target_type',
      'status',
      'identified_date',
      'applied_date',
      'rejected_date',
      'withdrawn_date',
      'expired_date',
    ],
    sort: null,
    filters: {},
  },
]

export const VIEW_BY_ID: Readonly<Record<ViewId, OpenApplicationView>> = Object.fromEntries(
  OPEN_APPLICATION_VIEWS.map((view) => [view.id, view])
) as Record<ViewId, OpenApplicationView>
