import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'

import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { JobApplicationDetail, JobApplicationFile, StatusHistoryEntry } from '@/lib/types'

// The statuses that count as forward progress (D-44). Rejected and Withdrawn are end states,
// reached from wherever the application was, not a further step in this sequence.
const MAIN_STATUSES = ['Identified', 'Applied', 'Screening', 'Interview', 'Offer'] as const
const END_STATUSES = ['Rejected', 'Withdrawn'] as const

// The Job Application page's layout (D-56, D-98, planning/product-model.md), Phase 3's slice:
// flags, header, job details, positioning analysis, application history, files. Job details,
// application history and files read real stored data (D-113); the tailored CV, cover letter
// and the positioning breakdown document stay "not done yet" (D-48), and the fit/gap bullets and
// match score stay empty, until Phase 5 actually runs positioning.
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

function Section({
  title,
  actions,
  children,
}: {
  title: string
  actions?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="group/section flex flex-col gap-3 rounded border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold">{title}</h2>
        {actions && (
          <div className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/section:opacity-100">
            {actions}
          </div>
        )}
      </div>
      {children}
    </section>
  )
}

// None of these buttons are wired to anything yet: they all need real backend support (inline
// editing, a Claude Job, a file upload endpoint) that comes later. They're here so the page's
// button inventory is right (D-103, revised by D-114).
const EDIT_TITLE = 'Editing comes in a later phase'
const UPLOAD_TITLE = 'Uploading comes in a later phase'
const llmTitle = (hasData: boolean) =>
  hasData ? 'Revising with the LLM comes in a later phase' : 'Generating with the LLM comes in a later phase'
const llmLabel = (hasData: boolean) => (hasData ? 'Revise (LLM)' : 'Generate (LLM)')

function LlmButton({ hasData }: { hasData: boolean }) {
  return (
    <Button variant="outline" size="sm" disabled title={llmTitle(hasData)}>
      {llmLabel(hasData)}
    </Button>
  )
}

function UploadButton() {
  return (
    <Button variant="outline" size="sm" disabled title={UPLOAD_TITLE}>
      Upload
    </Button>
  )
}

// A section's header actions (Job details, Positioning analysis, Application history): Edit,
// then Revise or Generate depending on whether the section has anything to revise yet. No Upload
// here - that's a Files thing only (D-114).
function SectionActions({ hasData }: { hasData: boolean }) {
  return (
    <div className="flex shrink-0 gap-2">
      <Button variant="outline" size="sm" disabled title={EDIT_TITLE}>
        Edit
      </Button>
      <LlmButton hasData={hasData} />
    </div>
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
  const hasData = application.description !== null || application.requirements.length > 0
  return (
    <Section title="Job details" actions={<SectionActions hasData={hasData} />}>
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
// Unclear (D-102) surfaces what the LLM would want answered to sharpen the score.
function PositioningAnalysis({ application }: { application: JobApplicationDetail }) {
  if (application.match_score === null) {
    return (
      <Section title="Positioning analysis" actions={<SectionActions hasData={false} />}>
        <p className="text-sm text-muted-foreground">Not run yet.</p>
      </Section>
    )
  }

  return (
    <Section title="Positioning analysis" actions={<SectionActions hasData={true} />}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[auto_1fr_1fr]">
        <div className="row-span-2 flex shrink-0 flex-col items-center gap-1 self-center sm:self-start">
          <MatchScoreRing score={application.match_score} />
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Match score
          </span>
          <Button
            variant="link"
            size="sm"
            disabled
            title="Opens the positioning breakdown document once file opening is wired up"
            className="h-auto p-0 text-xs"
          >
            Check reasoning
          </Button>
        </div>

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

        <div className="sm:col-span-2">
          <Field label="Unclear">
            {application.unclear.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5">
                {application.unclear.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : (
              <span className="text-muted-foreground">Nothing unclear.</span>
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
  // Always true in practice: every application starts with an Identified row (DEFAULT_STATUS), so
  // this section never actually shows "Generate (LLM)" today — the check is here for consistency.
  const hasData = application.status_history.length > 0
  return (
    <Section title="Application history" actions={<SectionActions hasData={hasData} />}>
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <StatusTimeline history={application.status_history} currentStatus={application.status} />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Field label="Notes">
            {application.notes ?? <span className="text-muted-foreground">No notes.</span>}
          </Field>
          <Field label="Next action">{application.next_action ?? EMPTY}</Field>
          <Field label="Due date">{application.due_date ?? EMPTY}</Field>
        </div>

        <EmailsColumn files={application.files.filter((file) => EMAIL_KINDS.has(file.kind))} />
      </div>
    </Section>
  )
}

// Email history (D-57, D-111): the same `files` array Additional files reads, filtered to the
// eml/msg kinds and sorted newest first — not a second list, so an email can only show here if
// it is also filed there (D-112). Preview is disabled for the same reason Files' Open is
// (D-109): there is no job-file table yet for FilePreview's second case to read from.
function EmailsColumn({ files }: { files: JobApplicationFile[] }) {
  const sorted = [...files].sort((a, b) => (b.date ?? '').localeCompare(a.date ?? ''))

  return (
    <div className="flex w-full flex-col gap-2 lg:w-72 lg:shrink-0">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Emails
      </span>
      {sorted.length === 0 ? (
        <p className="text-sm text-muted-foreground">No emails yet.</p>
      ) : (
        <ul className="flex max-h-48 flex-col divide-y divide-border overflow-y-auto rounded border border-border">
          {sorted.map((file) => (
            <li
              key={file.name}
              className="group/file flex items-center justify-between gap-2 px-3 py-2 text-sm"
            >
              <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
                <span className="truncate">{file.name.replace(/\.(eml|msg)$/i, '')}</span>
                {file.date && (
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                    {file.date.slice(0, 10)}
                  </span>
                )}
              </div>
              <div className="shrink-0 opacity-0 transition-opacity focus-within:opacity-100 group-hover/file:opacity-100">
                <Button
                  variant="outline"
                  size="sm"
                  disabled
                  title="Previewing emails comes once the job's own files are wired up"
                >
                  Preview
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
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
// The Emails column (D-111) is this same set read out of `files`, not a second list, so an
// email can only show there if it is also a file in Additional files (D-112).
const EMAIL_KINDS = new Set(['eml', 'msg'])

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
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FileGroup title="Listing" files={listing} empty="No listing file yet." />
        <FileGroup title="CV" files={cv} empty="Not done yet." />
        <FileGroup title="Cover letter" files={coverLetter} empty="Not done yet." />
        <FileGroup
          title="Additional files"
          files={additional}
          empty="No additional files."
          showKind
          generatable={false}
        />
      </div>
    </Section>
  )
}

// Listing, CV and Cover letter can be written by the LLM or uploaded, so they get Revise/Generate
// (LLM) plus Upload when empty (D-114). Additional files is never LLM-written — just a place for
// whatever else the user files against the application — so it skips the LLM button and always
// offers Upload, data or not (D-114).
function FileGroup({
  title,
  files,
  empty,
  showKind = false,
  generatable = true,
}: {
  title: string
  files: JobApplicationDetail['files']
  empty: string
  showKind?: boolean
  generatable?: boolean
}) {
  const hasData = files.length > 0
  return (
    <div className="group/subsection flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        <div className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/subsection:opacity-100">
          <div className="flex shrink-0 gap-2">
            {generatable && <LlmButton hasData={hasData} />}
            {(!generatable || !hasData) && <UploadButton />}
          </div>
        </div>
      </div>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded border border-border">
          {files.map((file) => (
            <li
              key={file.name}
              className="group/file flex items-center justify-between gap-4 px-3 py-2 text-sm"
            >
              <span>{file.name}</span>
              <div className="flex shrink-0 items-center gap-2">
                {showKind && (
                  <Badge
                    variant="outline"
                    className="rounded-sm font-mono text-[11px] font-normal text-muted-foreground"
                  >
                    {file.kind}
                  </Badge>
                )}
                <div className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/file:opacity-100">
                  <Button variant="outline" size="sm" disabled title="Opening files comes in a later phase">
                    Open
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
