import { Activity, Archive, CalendarClock, History, Home, ListChecks, Send, type LucideIcon } from 'lucide-react'

import type { Filters, SortState } from '@/components/app/JobsTableFilters'
import { DEFAULT_COLUMN_IDS, type ColumnId } from '@/lib/jobColumns'

// D-227/D-230: Default plus six predefined views. Each one's columns/sort/filter apply
// atomically when selected (JobApplicationsPage.switchView); resizing, reordering or using
// "Select columns" afterward forks into an implicit Custom view instead of changing the
// predefined one's own definition.
export type ViewId =
  | 'default'
  | 'to_apply_to'
  | 'active_applications'
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
  filters: Filters
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
    columns: ['company', 'role_title', 'lane', 'status', 'location', 'match_score'],
    sort: { column: 'match_score', direction: 'desc' },
    filters: statusFilter(['Applied', 'Screening', 'Interview', 'Offer']),
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
