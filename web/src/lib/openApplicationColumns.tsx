import { Check, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { StatusBadge } from '@/components/app/StatusBadge'
import { TruncatedText } from '@/components/app/TruncatedText'
import { TARGET_TYPE_LABELS } from '@/lib/openApplicationLabels'
import { OPEN_APPLICATION_STATUS_ORDER, type OpenApplication } from '@/lib/types'

// D-298 (Phase 17): the Open Applications table's own column registry, mirroring jobApplicationColumns.tsx's
// shape and resize/reorder/sort/filter machinery - trimmed to this entity's own fields (no Lane
// or Match score, D-249; a 5-status set instead of 7; 5 processing flags instead of 6).
export type ColumnId =
  | 'company_name'
  | 'target_type'
  | 'industry'
  | 'company_type'
  | 'contact'
  | 'status'
  | 'last_updated'
  | 'next_action_date'
  | 'next_action'
  | 'notes'
  | 'sources_status'
  | 'company_details_status'
  | 'cv_status'
  | 'cover_letter_status'
  | 'introduction_message_status'
  | 'identified_date'
  | 'applied_date'
  | 'rejected_date'
  | 'withdrawn_date'
  | 'expired_date'

// The checklist value standing in for a null value - matches jobApplicationColumns.ts's own UNSET.
export const UNSET = '(none)'

export type FilterSpec =
  | { kind: 'text'; value: (app: OpenApplication) => string | null }
  | { kind: 'ordered'; order: readonly string[]; value: (app: OpenApplication) => string }
  | { kind: 'date'; value: (app: OpenApplication) => string | null }

export type OpenApplicationColumn = {
  id: ColumnId
  label: string
  defaultWidth: number
  cell: (app: OpenApplication) => ReactNode
  compare: (a: OpenApplication, b: OpenApplication, direction: 1 | -1) => number
  filter?: FilterSpec
}

function compareNullableStrings(a: string | null, b: string | null, direction: 1 | -1): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return direction * a.localeCompare(b)
}

function compareOrdered(order: readonly string[], a: string, b: string, direction: 1 | -1): number {
  return direction * (order.indexOf(a) - order.indexOf(b))
}

function dateForStatus(app: OpenApplication, status: string): string | null {
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
  value: (app: OpenApplication) => string | null
): OpenApplicationColumn {
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
  value: (app: OpenApplication) => string | null
): OpenApplicationColumn {
  return {
    id,
    label,
    defaultWidth,
    cell: (app) => dateCell(value(app)),
    compare: (a, b, direction) => compareNullableStrings(value(a), value(b), direction),
    filter: { kind: 'date', value },
  }
}

function statusDateColumn(id: ColumnId, label: string, status: string): OpenApplicationColumn {
  return dateColumn(id, label, 120, (app) => dateForStatus(app, status))
}

const DONE_ORDER = ['Done', 'Not done'] as const

function statusFlagColumn(
  id: ColumnId,
  label: string,
  value: (app: OpenApplication) => boolean
): OpenApplicationColumn {
  const toLabel = (app: OpenApplication) => (value(app) ? 'Done' : 'Not done')
  return {
    id,
    label,
    defaultWidth: 110,
    cell: (app) =>
      value(app) ? (
        <Check className="size-4 text-[#84e7b0]" aria-label="Done" />
      ) : (
        <X className="size-4 text-muted-foreground" aria-label="Not done" />
      ),
    compare: (a, b, direction) => compareOrdered(DONE_ORDER, toLabel(a), toLabel(b), direction),
    filter: { kind: 'ordered', order: DONE_ORDER, value: toLabel },
  }
}

function targetTypeLabel(targetType: OpenApplication['target_type']): string | null {
  return targetType ? TARGET_TYPE_LABELS[targetType] : null
}

export const OPEN_APPLICATION_COLUMNS: readonly OpenApplicationColumn[] = [
  textColumn('company_name', 'Company', 180, (app) => app.company_name),
  {
    id: 'target_type',
    label: 'Target type',
    defaultWidth: 150,
    cell: (app) => (
      <span className="text-sm text-muted-foreground">
        {app.target_type ? TARGET_TYPE_LABELS[app.target_type] : '-'}
      </span>
    ),
    // 'text', not 'ordered' (D-298 fix): target_type is nullable, unlike Status - 'ordered'
    // only ever lists its fixed order's own values, so a null row could never be selected by
    // any filter choice. 'text' options are data-driven and include the UNSET option, the same
    // way jobApplicationColumns.ts's own nullable text columns (Lane, Location) already handle this.
    compare: (a, b, direction) =>
      compareNullableStrings(targetTypeLabel(a.target_type), targetTypeLabel(b.target_type), direction),
    filter: { kind: 'text', value: (app) => targetTypeLabel(app.target_type) },
  },
  textColumn('industry', 'Industry', 130, (app) => app.industry),
  textColumn('company_type', 'Company type', 150, (app) => app.company_type),
  textColumn('contact', 'Contact', 150, (app) => app.contact_name),
  {
    id: 'status',
    label: 'Status',
    defaultWidth: 120,
    cell: (app) => <StatusBadge status={app.status} />,
    compare: (a, b, direction) =>
      compareOrdered(OPEN_APPLICATION_STATUS_ORDER, a.status, b.status, direction),
    filter: { kind: 'ordered', order: OPEN_APPLICATION_STATUS_ORDER, value: (app) => app.status },
  },
  dateColumn('last_updated', 'Last updated', 120, (app) => app.last_updated),
  dateColumn('next_action_date', 'Next action date', 130, (app) => app.due_date),
  textColumn('next_action', 'Next action', 180, (app) => app.next_action),
  textColumn('notes', 'Notes', 220, (app) => app.notes),
  statusFlagColumn('sources_status', 'Sources status', (app) => app.has_sources),
  statusFlagColumn('company_details_status', 'Company details status', (app) => app.has_company_details),
  statusFlagColumn('cv_status', 'CV status', (app) => app.has_tailored_cv),
  statusFlagColumn('cover_letter_status', 'Cover letter status', (app) => app.has_cover_letter),
  statusFlagColumn(
    'introduction_message_status',
    'Introduction message status',
    (app) => app.has_introduction_message
  ),
  statusDateColumn('identified_date', 'Identified date', 'Identified'),
  statusDateColumn('applied_date', 'Applied date', 'Applied'),
  statusDateColumn('rejected_date', 'Rejected date', 'Rejected'),
  statusDateColumn('withdrawn_date', 'Withdrawn date', 'Withdrawn'),
  statusDateColumn('expired_date', 'Expired date', 'Expired'),
]

export const COLUMN_BY_ID: Readonly<Record<ColumnId, OpenApplicationColumn>> = Object.fromEntries(
  OPEN_APPLICATION_COLUMNS.map((column) => [column.id, column])
) as Record<ColumnId, OpenApplicationColumn>

export const DEFAULT_COLUMN_IDS: readonly ColumnId[] = [
  'company_name',
  'target_type',
  'status',
  'last_updated',
]
