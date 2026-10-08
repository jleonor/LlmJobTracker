import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'

import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { JobApplicationDetail, StatusHistoryEntry } from '@/lib/types'

// The statuses that count as forward progress (D-44). Rejected and Withdrawn are end states,
// reached from wherever the application was, not a further step in this sequence.
const MAIN_STATUSES = ['Identified', 'Applied', 'Screening', 'Interview', 'Offer'] as const
const END_STATUSES = ['Rejected', 'Withdrawn'] as const

// The Job Application page's layout (D-56, D-98, planning/product-model.md), Phase 3's slice:
// flags, header, job details, positioning analysis, application history, files. The tailored CV,
// cover letter and the positioning breakdown document stay "not done yet" (D-48) until Phase 5
// builds them; the fit/gap bullets and match score here are seed data too, not a real run.
export function JobApplicationDetailPage({
  application,
  onBack,
}: {
  application: JobApplicationDetail
  onBack: () => void
}) {
  return (
    <section aria-labelledby="job-detail-heading" className="flex flex-col gap-4">
      <Button variant="ghost" size="sm" onClick={onBack} className="self-start">
        <ArrowLeft className="size-4" aria-hidden="true" />
        Job Applications
      </Button>

      <Flags application={application} />

      <div className="flex flex-col gap-1">
        <p className="text-sm text-muted-foreground">{application.company}</p>
        <div className="flex flex-wrap items-center gap-2">
          <h1 id="job-detail-heading" className="text-xl font-semibold tracking-tight">
            {application.role_title}
          </h1>
          <StatusBadge status={application.status} />
          {application.lane && (
            <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal">
              {application.lane}
            </Badge>
          )}
          <QueueStatusBadge status={application.queue_status} />
        </div>
      </div>

      <JobDetails application={application} />
      <PositioningAnalysis application={application} />
      <ApplicationHistory application={application} />
      <Files files={application.files} />
    </section>
  )
}

// Clears once its output exists (D-48). Positioning analysis clears when match_score is set; the
// tailored CV and cover letter have no Phase 3 signal yet, so they always show.
function Flags({ application }: { application: JobApplicationDetail }) {
  const flags = [
    ...(application.match_score === null ? ['Positioning analysis'] : []),
    'Tailored CV',
    'Cover letter',
  ]
  return (
    <div className="flex flex-wrap gap-2" aria-label="Not done yet">
      {flags.map((flag) => (
        <Badge
          key={flag}
          variant="outline"
          className="rounded-sm font-mono text-[11px] font-normal text-muted-foreground"
        >
          {flag}: not done yet
        </Badge>
      ))}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <div className="text-sm">{children}</div>
    </div>
  )
}

const EMPTY = <span className="text-muted-foreground">Not set</span>

function JobDetails({ application }: { application: JobApplicationDetail }) {
  return (
    <Section title="Job details">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="URL">
          {application.portal_name ? (
            application.portal_url ? (
              <a
                href={application.portal_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline-offset-2 hover:underline"
              >
                {application.portal_name}
              </a>
            ) : (
              application.portal_name
            )
          ) : (
            EMPTY
          )}
        </Field>
        <Field label="Location">{application.location ?? EMPTY}</Field>
        <Field label="Work mode">{application.work_mode}</Field>
        <Field label="Contract type">{application.contract_type}</Field>
      </div>

      <Field label="Description">
        {application.description ?? <span className="text-muted-foreground">No description captured yet.</span>}
      </Field>

      <Field label="Requirements">
        {application.requirements.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5">
            {application.requirements.map((requirement) => (
              <li key={requirement}>{requirement}</li>
            ))}
          </ul>
        ) : (
          <span className="text-muted-foreground">No requirements captured yet.</span>
        )}
      </Field>
    </Section>
  )
}

// D-98: fit bullets, gap bullets and the match score only. The per-requirement weights, matches
// and reasoning behind the score are the breakdown document in Files, not shown here (D-99).
function PositioningAnalysis({ application }: { application: JobApplicationDetail }) {
  if (application.match_score === null) {
    return (
      <Section title="Positioning analysis">
        <p className="text-sm text-muted-foreground">Not run yet.</p>
      </Section>
    )
  }

  return (
    <Section title="Positioning analysis">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <div className="flex shrink-0 flex-col items-center gap-1 self-center sm:self-start">
          <MatchScoreRing score={application.match_score} />
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Match score
          </span>
        </div>
        <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Fit">
            {application.fit.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5">
                {application.fit.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : (
              <span className="text-muted-foreground">No fit points yet.</span>
            )}
          </Field>
          <Field label="Gaps">
            {application.gaps.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5">
                {application.gaps.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : (
              <span className="text-muted-foreground">No gaps noted.</span>
            )}
          </Field>
        </div>
      </div>
    </Section>
  )
}

function MatchScoreRing({ score }: { score: number }) {
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, score))
  const offset = circumference * (1 - clamped / 100)

  return (
    <svg viewBox="0 0 100 100" className="size-28" role="img" aria-label={`Match score ${Math.round(clamped)}%`}>
      <circle cx="50" cy="50" r={radius} fill="none" strokeWidth="8" stroke="currentColor" className="text-border" />
      <circle
        cx="50"
        cy="50"
        r={radius}
        fill="none"
        strokeWidth="8"
        strokeLinecap="round"
        stroke="currentColor"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 50 50)"
        className="text-primary"
      />
      <text
        x="50"
        y="50"
        textAnchor="middle"
        dominantBaseline="central"
        fill="currentColor"
        className="text-foreground font-mono text-[22px] font-semibold"
      >
        {Math.round(clamped)}%
      </text>
    </svg>
  )
}

function ApplicationHistory({ application }: { application: JobApplicationDetail }) {
  return (
    <Section title="Application history">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
        <StatusTimeline history={application.status_history} currentStatus={application.status} />

        <div className="flex flex-1 flex-col gap-4">
          <Field label="Notes">
            {application.notes ?? <span className="text-muted-foreground">No notes.</span>}
          </Field>
          <Field label="Next action">{application.next_action ?? EMPTY}</Field>
          <Field label="Due date">{application.due_date ?? EMPTY}</Field>
        </div>
      </div>
    </Section>
  )
}

// A connected stepper, not a badge list: the line and the dots are coloured for progress made
// (D-44) up to the current main stage, then red for whatever is left once the application ends
// in Rejected or Withdrawn, including the end-state node itself. Still grey when there is no end
// state yet, since the remaining stages are merely unreached, not ruled out.
function StatusTimeline({
  history,
  currentStatus,
}: {
  history: StatusHistoryEntry[]
  currentStatus: string
}) {
  const dateByStatus = new Map(history.map((entry) => [entry.status, entry.changed_at]))
  const ended = (END_STATUSES as readonly string[]).includes(currentStatus)
  const steps: readonly string[] = ended ? [...MAIN_STATUSES, currentStatus] : MAIN_STATUSES
  const lastProgressIndex = MAIN_STATUSES.reduce(
    (furthest, status, index) => (dateByStatus.has(status) ? index : furthest),
    -1,
  )
  const isProgress = (index: number) => index <= 4 && index <= lastProgressIndex

  return (
    <ol className="flex flex-col">
      {steps.map((status, index) => {
        const achievedAt = dateByStatus.get(status)
        const isLast = index === steps.length - 1
        const isEndNode = ended && isLast
        const dotTone = isEndNode
          ? 'border-destructive bg-destructive'
          : isProgress(index)
            ? 'border-primary bg-primary'
            : ended
              ? 'border-destructive bg-background'
              : 'border-border bg-background'
        const lineTone = isProgress(index + 1) ? 'bg-primary' : ended ? 'bg-destructive' : 'bg-border'
        const textTone = isEndNode
          ? 'font-medium text-destructive'
          : isProgress(index)
            ? 'font-medium text-foreground'
            : ended
              ? 'text-destructive/70'
              : 'text-muted-foreground'

        return (
          <li key={status} className="flex gap-3">
            <span className="w-20 shrink-0 text-right font-mono text-xs whitespace-nowrap text-muted-foreground">
              {achievedAt?.slice(0, 10)}
            </span>
            <div className="flex flex-col items-center">
              <span className={cn('size-[11px] shrink-0 rounded-full border-2', dotTone)} aria-hidden="true" />
              {!isLast && <span className={cn('w-0.5 flex-1', lineTone)} aria-hidden="true" />}
            </div>
            <span className={cn('text-sm whitespace-nowrap', textTone, !isLast && 'pb-4')}>{status}</span>
          </li>
        )
      })}
    </ol>
  )
}

// CV and cover letter files don't exist until Phase 5 writes them (D-57); their subsections just
// read "Not done yet.", matching the Flags wording above, until then.
const CV_KINDS = new Set(['master_cv', 'tailored_cv'])
const COVER_LETTER_KINDS = new Set(['cover_letter'])

function Files({ files }: { files: JobApplicationDetail['files'] }) {
  const listing = files.filter((file) => file.kind === 'listing')
  const cv = files.filter((file) => CV_KINDS.has(file.kind))
  const coverLetter = files.filter((file) => COVER_LETTER_KINDS.has(file.kind))
  const additional = files.filter(
    (file) =>
      file.kind !== 'listing' && !CV_KINDS.has(file.kind) && !COVER_LETTER_KINDS.has(file.kind),
  )

  return (
    <Section title="Files">
      <FileGroup title="Listing" files={listing} empty="No listing file yet." />
      <FileGroup title="CV" files={cv} empty="Not done yet." />
      <FileGroup title="Cover letter" files={coverLetter} empty="Not done yet." />
      <FileGroup title="Additional files" files={additional} empty="No additional files." showKind />
    </Section>
  )
}

function FileGroup({
  title,
  files,
  empty,
  showKind = false,
}: {
  title: string
  files: JobApplicationDetail['files']
  empty: string
  showKind?: boolean
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{title}</h3>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded border border-border">
          {files.map((file) => (
            <li key={file.name} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
              <span>{file.name}</span>
              {showKind && (
                <Badge
                  variant="outline"
                  className="rounded-sm font-mono text-[11px] font-normal text-muted-foreground"
                >
                  {file.kind}
                </Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
