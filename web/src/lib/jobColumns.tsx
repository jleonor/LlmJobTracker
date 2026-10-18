import type { ReactNode } from 'react'

import { StatusBadge } from '@/components/app/StatusBadge'
import { TruncatedText } from '@/components/app/TruncatedText'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { STATUS_ORDER, type JobApplication } from '@/lib/types'

// D-227: the table's 27 selectable columns. Every column is reorderable, resizable (TanStack
// Table owns that structural state) and sortable/filterable (this module's own compare/filter
// logic, matching the table's pre-D-227 behavior rather than TanStack's own sorting/filtering
// state, since the checklist/date-range/score-range popovers this app already has don't map onto
// TanStack's filter model any more naturally than onto a plain array compare/filter pass).
export type ColumnId =
  | 'company'
  | 'role_title'
  | 'lane'
  | 'location'
  | 'status'
  | 'match_score'
  | 'last_updated'
  | 'portal'
  | 'contract_type'
  | 'work_mode'
  | 'listing_status'
  | 'details_status'
  | 'analysis_status'
  | 'cv_status'
  | 'cover_letter_status'
  | 'interview_prep_status'
  | 'identified_date'
  | 'applied_date'
  | 'screening_date'
  | 'interview_date'
  | 'offer_date'
  | 'rejected_date'
  | 'withdrawn_date'
  | 'expired_date'
  | 'next_action_date'
  | 'next_action'
  | 'notes'

// The checklist value standing in for a null value - no real lane/location/etc. can collide
// with this (D-159's original UNSET, generalized to every text/ordered column).
export const UNSET = '(none)'

export type FilterSpec =
  | { kind: 'text'; value: (app: JobApplication) => string | null }
  | { kind: 'ordered'; order: readonly string[]; value: (app: JobApplication) => string }
  | { kind: 'date'; value: (app: JobApplication) => string | null }
  | { kind: 'score' }

export type JobColumn = {
  id: ColumnId
  label: string
  defaultWidth: number
  cell: (app: JobApplication) => ReactNode
  compare: (a: JobApplication, b: JobApplication, direction: 1 | -1) => number
  filter?: FilterSpec
}

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

function compareOrdered(order: readonly string[], a: string, b: string, direction: 1 | -1): number {
  return direction * (order.indexOf(a) - order.indexOf(b))
}

function dateForStatus(app: JobApplication, status: string): string | null {
  const matches = app.status_history.filter((entry) => entry.status === status)
  return matches.length === 0 ? null : matches[matches.length - 1].changed_at
}

function dateCell(raw: string | null): ReactNode {
  if (raw === null) return <span className="text-muted-foreground">-</span>
  return <span className="font-mono text-xs">{raw.slice(0, 10)}</span>
}

function textColumn(
  id: ColumnId,
  label: string,
  defaultWidth: number,
  value: (app: JobApplication) => string | null
): JobColumn {
  return {
    id,
    label,
    defaultWidth,
    cell: (app) => <TruncatedText value={value(app)} />,
    compare: (a, b, direction) => compareNullableStrings(value(a), value(b), direction),
    filter: { kind: 'text', value },
  }
}

function dateColumn(
  id: ColumnId,
  label: string,
  defaultWidth: number,
  value: (app: JobApplication) => string | null
): JobColumn {
  return {
    id,
    label,
    defaultWidth,
    cell: (app) => dateCell(value(app)),
    compare: (a, b, direction) => compareNullableStrings(value(a), value(b), direction),
    filter: { kind: 'date', value },
  }
}

function statusDateColumn(id: ColumnId, label: string, status: string): JobColumn {
  return dateColumn(id, label, 120, (app) => dateForStatus(app, status))
}

function laneCell(app: JobApplication): ReactNode {
  if (!app.lane) return <span className="text-muted-foreground">-</span>
  return (
    <Tooltip>
      <TooltipTrigger render={<span />} className="block max-w-full cursor-default">
        <Badge
          variant="outline"
          className="max-w-full truncate rounded-sm font-mono text-[11px] font-normal"
        >
          {app.lane}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{app.lane}</TooltipContent>
    </Tooltip>
  )
}

function matchScoreCell(app: JobApplication): ReactNode {
  if (app.match_score === null) return <span className="text-muted-foreground">-</span>
  return <span className="font-mono text-xs">{Math.round(app.match_score)}%</span>
}

function portalCell(app: JobApplication): ReactNode {
  if (!app.portal_name) return <span className="text-muted-foreground">-</span>
  if (app.portal_url) {
    return (
      <a
        href={app.portal_url}
        target="_blank"
        rel="noreferrer"
        onClick={(event) => event.stopPropagation()}
        className="block max-w-full truncate text-primary underline-offset-2 hover:underline"
      >
        {app.portal_name}
      </a>
    )
  }
  return <TruncatedText value={app.portal_name} />
}

const DONE_ORDER = ['Done', 'Not done'] as const

function statusFlagColumn(
  id: ColumnId,
  label: string,
  value: (app: JobApplication) => boolean
): JobColumn {
  const toLabel = (app: JobApplication) => (value(app) ? 'Done' : 'Not done')
  return {
    id,
    label,
    defaultWidth: 110,
    cell: (app) =>
      value(app) ? (
        <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal">
          Done
        </Badge>
      ) : (
        <span className="text-muted-foreground">Not done</span>
      ),
    compare: (a, b, direction) => compareOrdered(DONE_ORDER, toLabel(a), toLabel(b), direction),
    filter: { kind: 'ordered', order: DONE_ORDER, value: toLabel },
  }
}

export const JOB_COLUMNS: readonly JobColumn[] = [
  textColumn('company', 'Company', 160, (app) => app.company),
  textColumn('role_title', 'Title', 200, (app) => app.role_title),
  { ...textColumn('lane', 'Lane', 140, (app) => app.lane), cell: laneCell },
  textColumn('location', 'Location', 130, (app) => app.location),
  {
    id: 'status',
    label: 'Status',
    defaultWidth: 120,
    cell: (app) => <StatusBadge status={app.status} />,
    compare: (a, b, direction) => compareOrdered(STATUS_ORDER, a.status, b.status, direction),
    filter: { kind: 'ordered', order: STATUS_ORDER, value: (app) => app.status },
  },
  {
    id: 'match_score',
    label: 'Match score',
    defaultWidth: 110,
    cell: matchScoreCell,
    compare: (a, b, direction) => compareNullableNumbers(a.match_score, b.match_score, direction),
    filter: { kind: 'score' },
  },
  dateColumn('last_updated', 'Last updated', 120, (app) => app.last_updated),
  { ...textColumn('portal', 'Job portal', 160, (app) => app.portal_name), cell: portalCell },
  textColumn('contract_type', 'Contract type', 130, (app) => app.contract_type),
  textColumn('work_mode', 'Work mode', 110, (app) => app.work_mode),
  statusFlagColumn('listing_status', 'Listing status', (app) => app.has_listing),
  statusFlagColumn('details_status', 'Details status', (app) => app.has_details),
  statusFlagColumn('analysis_status', 'Analysis status', (app) => app.has_analysis),
  statusFlagColumn('cv_status', 'CV status', (app) => app.has_tailored_cv),
  statusFlagColumn('cover_letter_status', 'Cover letter status', (app) => app.has_cover_letter),
  statusFlagColumn(
    'interview_prep_status',
    'Interview preparation status',
    (app) => app.has_interview_prep
  ),
  statusDateColumn('identified_date', 'Identified date', 'Identified'),
  statusDateColumn('applied_date', 'Applied date', 'Applied'),
  statusDateColumn('screening_date', 'Screening date', 'Screening'),
  statusDateColumn('interview_date', 'Interview date', 'Interview'),
  statusDateColumn('offer_date', 'Offer date', 'Offer'),
  statusDateColumn('rejected_date', 'Rejected date', 'Rejected'),
  statusDateColumn('withdrawn_date', 'Withdrawn date', 'Withdrawn'),
  statusDateColumn('expired_date', 'Expired date', 'Expired'),
  dateColumn('next_action_date', 'Next action date', 120, (app) => app.due_date),
  textColumn('next_action', 'Next action', 180, (app) => app.next_action),
  textColumn('notes', 'Notes', 220, (app) => app.notes),
]

export const COLUMN_BY_ID: Readonly<Record<ColumnId, JobColumn>> = Object.fromEntries(
  JOB_COLUMNS.map((column) => [column.id, column])
) as Record<ColumnId, JobColumn>

export const DEFAULT_COLUMN_IDS: readonly ColumnId[] = [
  'company',
  'role_title',
  'lane',
  'status',
  'match_score',
  'last_updated',
]
