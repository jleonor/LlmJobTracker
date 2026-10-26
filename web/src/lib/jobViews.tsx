import { Activity, Archive, CalendarClock, History, Home, ListChecks, Send, Snowflake, type LucideIcon } from 'lucide-react'

import type { Filters, SortState } from '@/components/app/JobsTableFilters'
import { DEFAULT_COLUMN_IDS, type ColumnId } from '@/lib/jobColumns'
import { STATUS_ORDER } from '@/lib/types'

// D-227/D-230: Default plus predefined views. Each one's columns/sort/filter apply atomically
// when selected (JobApplicationsPage.switchView); resizing, reordering or using "Select columns"
// afterward forks into an implicit Custom view instead of changing the predefined one's own
// definition.
export type ViewId =
  | 'default'
  | 'to_apply_to'
  | 'active_applications'
  | 'cold_applications'
  | 'dead_applications'
  | 'upcoming_actions'
  | 'processing_status'
  | 'history_dates'

export type JobView = {
  id: ViewId
  label: string
  icon: LucideIcon
  columns: readonly ColumnId[]
  sort: SortState
  // A plain Filters object for most views; a function for one whose filter is relative to today
  // (Active/Cold applications' 30-day recency condition, Phase 14 D-275) - resolved at selection
  // time (JobApplicationsPage.switchView), never baked into a stored constant, so it never goes
  // stale.
  filters: Filters | ((now: Date) => Filters)
}

function statusFilter(statuses: string[]): Filters {
  return { status: { kind: 'text', selected: new Set(statuses) } }
}

// "Has a next action date" has no dedicated filter kind - expressed as a date-range filter whose
// `from` sits before any real date, so every actual value passes while a null one still doesn't
// (applicationMatchesFilters' date branch rejects a null day whenever `from` is set).
const HAS_NEXT_ACTION_DATE: Filters = {
  next_action_date: { kind: 'date', from: '1970-01-01', to: null },
}

// Phase 14 (D-275): Active/Cold's 30-day recency cutoff, as a "YYYY-MM-DD" day string.
const STALE_AFTER_DAYS = 30

function daysAgoDateKey(now: Date, days: number): string {
  const date = new Date(now)
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

// The three dead end states (Rejected, Withdrawn, Expired) - "non-Dead" for Cold applications
// means every other status, Identified included.
const NON_DEAD_STATUSES = STATUS_ORDER.filter(
  (status) => !['Rejected', 'Withdrawn', 'Expired'].includes(status),
)

export const JOB_VIEWS: readonly JobView[] = [
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
    columns: ['company', 'role_title', 'lane', 'status', 'location', 'match_score'],
    sort: { column: 'match_score', direction: 'desc' },
    filters: statusFilter(['Identified']),
  },
  {
    id: 'active_applications',
    label: 'Active applications',
    icon: Activity,
    columns: ['company', 'role_title', 'lane', 'status', 'last_updated', 'location', 'match_score'],
    sort: { column: 'match_score', direction: 'desc' },
    // D-275: in progress (Applied through Offer) AND touched within the last 30 days.
    filters: (now) => ({
      ...statusFilter(['Applied', 'Screening', 'Interview', 'Offer']),
      last_updated: { kind: 'date', from: daysAgoDateKey(now, STALE_AFTER_DAYS), to: null },
    }),
  },
  {
    id: 'cold_applications',
    label: 'Cold applications',
    icon: Snowflake,
    columns: ['company', 'role_title', 'lane', 'status', 'last_updated', 'location', 'match_score'],
    sort: { column: 'last_updated', direction: 'asc' },
    // D-275: any non-Dead status (Identified included) untouched for more than 30 days.
    filters: (now) => ({
      ...statusFilter(NON_DEAD_STATUSES),
      last_updated: { kind: 'date', from: null, to: daysAgoDateKey(now, STALE_AFTER_DAYS) },
    }),
  },
  {
    id: 'dead_applications',
    label: 'Dead applications',
    icon: Archive,
    columns: ['company', 'role_title', 'lane', 'status', 'match_score', 'notes'],
    sort: { column: 'match_score', direction: 'desc' },
    filters: statusFilter(['Rejected', 'Withdrawn', 'Expired']),
  },
  {
    id: 'upcoming_actions',
    label: 'Upcoming actions',
    icon: CalendarClock,
    columns: [
      'company',
      'role_title',
      'lane',
      'status',
      'next_action_date',
      'next_action',
      'match_score',
    ],
    sort: { column: 'next_action_date', direction: 'asc' },
    // Applied through Offer (D-44's forward order, excluding Identified and the three end
    // states) with a next action actually set - the user's own narrowing of the original
    // "no filter" definition.
    filters: { ...statusFilter(['Applied', 'Screening', 'Interview', 'Offer']), ...HAS_NEXT_ACTION_DATE },
  },
  {
    id: 'processing_status',
    label: 'Processing status',
    icon: ListChecks,
    columns: [
      'company',
      'role_title',
      'lane',
      'status',
      'match_score',
      'listing_status',
      'details_status',
      'cv_status',
      'cover_letter_status',
      'analysis_status',
      'interview_prep_status',
    ],
    sort: null,
    filters: {},
  },
  {
    id: 'history_dates',
    label: 'History dates',
    icon: History,
    columns: [
      'company',
      'role_title',
      'lane',
      'status',
      'match_score',
      'identified_date',
      'applied_date',
      'screening_date',
      'interview_date',
      'offer_date',
      'rejected_date',
      'withdrawn_date',
      'expired_date',
    ],
    sort: null,
    filters: {},
  },
]

export const VIEW_BY_ID: Readonly<Record<ViewId, JobView>> = Object.fromEntries(
  JOB_VIEWS.map((view) => [view.id, view])
) as Record<ViewId, JobView>
