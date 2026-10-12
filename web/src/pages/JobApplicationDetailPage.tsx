import { ArrowLeft, Download, FolderOpen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { FilePreview, FilePreviewBody, useFilePreview } from '@/components/app/FilePreview'
import { GenerateListingOverlay } from '@/components/app/GenerateListingOverlay'
import { GenerateSectionOverlay } from '@/components/app/GenerateSectionOverlay'
import { JobReviseOverlay } from '@/components/app/JobReviseOverlay'
import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  deleteJobApplication,
  downloadJobFile,
  fetchProfileFiles,
  fetchProfileOutputs,
  generateApplicationHistory,
  generateCoverLetter,
  generateJobDetails,
  generatePositioning,
  generateTailoredCv,
  openJobFile,
  patchJobApplication,
  replaceStatusHistory,
  revealJobFile,
  setMasterCv,
  uploadJobFile,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  JobApplicationDetail,
  JobApplicationEdit,
  JobApplicationFile,
  ProfileFile,
  StatusHistoryEntry,
} from '@/lib/types'

// The statuses that count as forward progress (D-44). Rejected and Withdrawn are end states,
// reached from wherever the application was, not a further step in this sequence.
const MAIN_STATUSES = ['Identified', 'Applied', 'Screening', 'Interview', 'Offer'] as const
const END_STATUSES = ['Rejected', 'Withdrawn'] as const
// D-117: every stage the Edit dialog's date editor offers, main statuses first.
const ALL_STATUSES = [...MAIN_STATUSES, ...END_STATUSES]

function todayDateOnly(): string {
  return new Date().toISOString().slice(0, 10)
}

// status_history.changed_at is stored as a full ISO timestamp (e.g. "2026-10-01T09:00:00Z");
// <input type="date"> only works in "YYYY-MM-DD", so the editor converts both ways.
function dateOnly(changedAt: string): string {
  return changedAt.slice(0, 10)
}

function toChangedAt(dateValue: string): string {
  return `${dateValue}T00:00:00Z`
}
const WORK_MODES = ['Onsite', 'Hybrid', 'Remote', 'Unknown'] as const
const CONTRACT_TYPES = ['Full-Time', 'Part-Time', 'Contract/Short Term', 'Other', 'Unknown'] as const
// Select.Value resolves labels from this map even while the popup is closed (see MasterCvField's
// comment on the same pattern) - an identity map here since each value is already its own label.
const WORK_MODE_ITEMS = Object.fromEntries(WORK_MODES.map((mode) => [mode, mode]))
const CONTRACT_TYPE_ITEMS = Object.fromEntries(CONTRACT_TYPES.map((type) => [type, type]))

function linesToList(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function listToLines(list: string[]): string {
  return list.join('\n')
}

// The Job Application page's layout (D-56, D-98, planning/product-model.md). Job details,
// Positioning analysis and Application history are edited manually through Edit (D-116); the
// tailored CV, cover letter and the positioning breakdown document stay "not done yet" (D-48),
// and Revise/Generate (LLM) stay unwired everywhere they appear.
export function JobApplicationDetailPage({
  application,
  onBack,
  onChanged,
  onDeleted,
}: {
  application: JobApplicationDetail
  onBack: () => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    const ok = window.confirm(
      `Delete ${application.company} - ${application.role_title}? This removes its listing, ` +
        'files, status history and LLM job history, and cannot be undone.',
    )
    if (!ok) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteJobApplication(application.id)
      onDeleted()
    } catch (failure) {
      setDeleteError(failure instanceof ApiError ? failure.message : 'This could not be deleted.')
      setDeleting(false)
    }
  }

  return (
    <section aria-labelledby="job-detail-heading" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack} className="self-start">
          <ArrowLeft className="size-4" aria-hidden="true" />
          Job Applications
        </Button>
        <Button variant="destructive" size="sm" disabled={deleting} onClick={() => void handleDelete()}>
          {deleting ? 'Deleting...' : 'Delete'}
        </Button>
      </div>
      {deleteError && (
        <p role="alert" className="text-sm text-destructive">
          {deleteError}
        </p>
      )}

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

      <JobDetails application={application} onChanged={onChanged} />
      <PositioningAnalysis application={application} onChanged={onChanged} />
      <ApplicationHistory application={application} onChanged={onChanged} />
      <Files application={application} onChanged={onChanged} />
    </section>
  )
}

// Clears once its output exists (D-48). Positioning analysis clears when match_score is set; the
// tailored CV and cover letter have no Phase 3 signal yet, so they always show.
// Whether Positioning analysis has anything to show (D-116): not just match_score, which stays
// null until Phase 5 actually runs it, but also the manually-editable fit/gaps/strategy/unclear.
function hasPositioningData(application: JobApplicationDetail): boolean {
  return (
    application.match_score !== null ||
    application.fit.length > 0 ||
    application.gaps.length > 0 ||
    application.strategy !== null ||
    application.unclear.length > 0
  )
}

function Flags({ application }: { application: JobApplicationDetail }) {
  const hasTailoredCv = application.files.some((file) => file.kind === TAILORED_CV_KIND)
  const hasCoverLetter = application.files.some((file) => COVER_LETTER_KINDS.has(file.kind))
  const flags = [
    ...(hasPositioningData(application) ? [] : ['Positioning analysis']),
    ...(hasTailoredCv ? [] : ['Tailored CV']),
    ...(hasCoverLetter ? [] : ['Cover letter']),
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

// Revise/Generate (LLM) stay unwired (D-103, D-114): they need a Claude Job this round doesn't
// touch. Edit, Preview, Open, Upload and the Master CV selector are real (D-116).
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

function UploadButton({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" disabled={busy} title={UPLOAD_TITLE} onClick={onClick}>
      {busy ? 'Uploading...' : 'Upload'}
    </Button>
  )
}

// A section's header actions (Job details, Positioning analysis, Application history): Edit,
// then Revise or Generate depending on whether the section has anything to revise yet (D-114).
// All three are real (steps 30-33) - generateDisabled/generateTitle mirror the backend's own
// gate (D-128), so a greyed-out button explains what's missing, the same pattern LlmButton's
// always-disabled title already used. No Upload here - that's a Files thing only (D-114).
function SectionActions({
  hasData,
  onEdit,
  onGenerate,
  generateDisabled,
  generateTitle,
}: {
  hasData: boolean
  onEdit: () => void
  onGenerate: () => void
  generateDisabled?: boolean
  generateTitle?: string
}) {
  return (
    <div className="flex shrink-0 gap-2">
      <Button variant="outline" size="sm" onClick={onEdit}>
        Edit
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={generateDisabled}
        title={generateDisabled ? generateTitle : undefined}
        onClick={onGenerate}
      >
        {llmLabel(hasData)}
      </Button>
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

// A labelled form control for an Edit dialog (D-116) - same idea as Field, but for an input
// instead of display text.
function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

const EMPTY = <span className="text-muted-foreground">Not set</span>

function JobDetails({
  application,
  onChanged,
}: {
  application: JobApplicationDetail
  onChanged: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const hasData = application.description !== null || application.requirements.length > 0
  const hasListing = application.files.some(
    (file) => file.kind === 'listing' && file.extraction_status === 'ok',
  )
  return (
    <Section
      title="Job details"
      actions={
        <SectionActions
          hasData={hasData}
          onEdit={() => setEditOpen(true)}
          onGenerate={() => setGenerateOpen(true)}
          generateDisabled={!hasListing}
          generateTitle="Add a listing file with readable text first."
        />
      }
    >
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

      <JobDetailsEditDialog
        application={application}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={onChanged}
      />
      {hasData ? (
        <JobReviseOverlay
          applicationId={application.id}
          sectionKind="job_details"
          title="Job details"
          leftPane={
            <CurrentJobDetailsPane
              description={application.description}
              requirements={application.requirements}
            />
          }
          open={generateOpen}
          onOpenChange={setGenerateOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Job details"
          hasData={hasData}
          open={generateOpen}
          onOpenChange={setGenerateOpen}
          onSubmit={() => generateJobDetails(application.id)}
          onChanged={onChanged}
        />
      )}
    </Section>
  )
}

// JobReviseOverlay's left pane for Job details (D-136): the description and numbered
// requirements exactly as the chat prompt itself presents them, so a message like "remove #3"
// refers to what's on screen.
function CurrentJobDetailsPane({
  description,
  requirements,
}: {
  description: string | null
  requirements: string[]
}) {
  if (!description && requirements.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to revise yet.</p>
  }
  return (
    <div className="flex flex-col gap-3 text-sm">
      {description && <p className="whitespace-pre-wrap">{description}</p>}
      {requirements.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5">
          {requirements.map((requirement) => (
            <li key={requirement}>{requirement}</li>
          ))}
        </ol>
      )}
    </div>
  )
}

function JobDetailsEditDialog({
  application,
  open,
  onOpenChange,
  onSaved,
}: {
  application: JobApplicationDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [portalName, setPortalName] = useState('')
  const [portalUrl, setPortalUrl] = useState('')
  const [location, setLocation] = useState('')
  const [workMode, setWorkMode] = useState<string>(application.work_mode)
  const [contractType, setContractType] = useState<string>(application.contract_type)
  const [description, setDescription] = useState('')
  const [requirements, setRequirements] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form from the current application each time the dialog opens, so a cancelled edit
  // never leaks into the next one.
  useEffect(() => {
    if (!open) return
    setPortalName(application.portal_name ?? '')
    setPortalUrl(application.portal_url ?? '')
    setLocation(application.location ?? '')
    setWorkMode(application.work_mode)
    setContractType(application.contract_type)
    setDescription(application.description ?? '')
    setRequirements(listToLines(application.requirements))
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function save() {
    setBusy(true)
    setError(null)
    const edit: JobApplicationEdit = {
      portal_name: portalName.trim() || null,
      portal_url: portalUrl.trim() || null,
      location: location.trim() || null,
      work_mode: workMode,
      contract_type: contractType,
      description: description.trim() || null,
      requirements: linesToList(requirements),
    }
    try {
      await patchJobApplication(application.id, edit)
      onOpenChange(false)
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[70vh] w-full max-w-lg flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit job details</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField label="Portal name">
              <Input value={portalName} onChange={(event) => setPortalName(event.target.value)} />
            </FormField>
            <FormField label="Portal URL">
              <Input
                type="url"
                value={portalUrl}
                onChange={(event) => setPortalUrl(event.target.value)}
              />
            </FormField>
          </div>
          <FormField label="Location">
            <Input value={location} onChange={(event) => setLocation(event.target.value)} />
          </FormField>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField label="Work mode">
              <Select
                items={WORK_MODE_ITEMS}
                value={workMode}
                onValueChange={(value) => value && setWorkMode(value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WORK_MODES.map((mode) => (
                    <SelectItem key={mode} value={mode}>
                      {mode}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Contract type">
              <Select
                items={CONTRACT_TYPE_ITEMS}
                value={contractType}
                onValueChange={(value) => value && setContractType(value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CONTRACT_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <FormField label="Description">
            <Textarea
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </FormField>
          <FormField label="Requirements (one per line)">
            <Textarea
              rows={4}
              value={requirements}
              onChange={(event) => setRequirements(event.target.value)}
            />
          </FormField>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// D-98: fit bullets, gap bullets and the match score only. The per-requirement weights, matches
// and reasoning behind the score are the breakdown document in Files, not shown here (D-99).
// Strategy (D-116) and Unclear (D-102) are manually editable until Phase 5 computes them for
// real; match_score stays code-computed (D-47) and is not part of the Edit form.
function PositioningAnalysis({
  application,
  onChanged,
}: {
  application: JobApplicationDetail
  onChanged: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  const [breakdownPreviewOpen, setBreakdownPreviewOpen] = useState(false)
  const [profileDocsReady, setProfileDocsReady] = useState<boolean | null>(null)
  const hasData = hasPositioningData(application)

  // Positioning analysis's own gate (job-llm-steps.md §3, D-128): the three LLM profile
  // documents, a Master CV selected, Job details filled, and the listing file's text readable.
  // The first of these needs its own fetch - everything else is already on `application`.
  useEffect(() => {
    let cancelled = false
    fetchProfileOutputs()
      .then((outputs) => {
        if (!cancelled) setProfileDocsReady(outputs.length === 3)
      })
      .catch(() => {
        if (!cancelled) setProfileDocsReady(false)
      })
    return () => {
      cancelled = true
    }
  }, [])
  const hasListing = application.files.some(
    (file) => file.kind === 'listing' && file.extraction_status === 'ok',
  )
  const hasJobDetails = application.description !== null && application.requirements.length > 0
  const ready =
    profileDocsReady === true &&
    application.master_cv_profile_file_id !== null &&
    hasJobDetails &&
    hasListing

  const breakdownFile = application.files.find((file) => file.kind === 'positioning_breakdown')

  const actions = (
    <SectionActions
      hasData={hasData}
      onEdit={() => setEditOpen(true)}
      onGenerate={() => setGenerateOpen(true)}
      generateDisabled={!ready}
      generateTitle="Positioning analysis needs the career history, questionnaire analysis and strategy, a selected Master CV, and Job details filled in first."
    />
  )
  const dialog = (
    <PositioningEditDialog
      application={application}
      open={editOpen}
      onOpenChange={setEditOpen}
      onSaved={onChanged}
    />
  )
  const generateOverlay = hasData ? (
    <JobReviseOverlay
      applicationId={application.id}
      sectionKind="positioning"
      title="Positioning analysis"
      leftPane={
        <CurrentPositioningPane
          matchScore={application.match_score}
          fit={application.fit}
          gaps={application.gaps}
          strategy={application.strategy}
          unclear={application.unclear}
        />
      }
      open={generateOpen}
      onOpenChange={setGenerateOpen}
      onChanged={onChanged}
    />
  ) : (
    <GenerateSectionOverlay
      title="Positioning analysis"
      hasData={hasData}
      open={generateOpen}
      onOpenChange={setGenerateOpen}
      onSubmit={() => generatePositioning(application.id)}
      onChanged={onChanged}
    />
  )

  if (!hasData) {
    return (
      <Section title="Positioning analysis" actions={actions}>
        <p className="text-sm text-muted-foreground">Not run yet.</p>
        {dialog}
        {generateOverlay}
      </Section>
    )
  }

  return (
    <Section title="Positioning analysis" actions={actions}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[auto_1fr_1fr]">
          <div className="row-span-2 flex shrink-0 flex-col items-center gap-1 self-center sm:self-start">
            {application.match_score === null ? (
              <div
                className="flex size-28 items-center justify-center rounded-full border-8 border-border font-mono text-xs text-muted-foreground"
                role="img"
                aria-label="Match score not computed yet"
              >
                Not scored
              </div>
            ) : (
              <MatchScoreRing score={application.match_score} />
            )}
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Match score
            </span>
            <Button
              variant="link"
              size="sm"
              disabled={!breakdownFile}
              title={breakdownFile ? undefined : 'No positioning breakdown document yet.'}
              onClick={() => setBreakdownPreviewOpen(true)}
              className="h-auto p-0 text-xs"
            >
              Check reasoning
            </Button>
            {breakdownFile && (
              <FilePreview
                source={{ table: 'job_file', applicationId: application.id, id: breakdownFile.id }}
                name={breakdownFile.name}
                open={breakdownPreviewOpen}
                onOpenChange={setBreakdownPreviewOpen}
              />
            )}
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
        </div>

        <Field label="Strategy">
          {application.strategy ?? <span className="text-muted-foreground">No strategy yet.</span>}
        </Field>

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
      {dialog}
      {generateOverlay}
    </Section>
  )
}

// JobReviseOverlay's left pane for Positioning analysis (D-139): the same fields the page body
// itself shows. The per-requirement breakdown (weight/match/reasoning) stays out of this pane -
// it's already one click away via "Check reasoning", and the chat resolves which stored
// requirement a message means on its own, the same way Job details' chat does without the user
// needing to know a requirement's number either.
function CurrentPositioningPane({
  matchScore,
  fit,
  gaps,
  strategy,
  unclear,
}: {
  matchScore: number | null
  fit: string[]
  gaps: string[]
  strategy: string | null
  unclear: string[]
}) {
  if (matchScore === null && fit.length === 0 && gaps.length === 0 && !strategy && unclear.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to revise yet.</p>
  }
  return (
    <div className="flex flex-col gap-3 text-sm">
      <Field label="Match score">{matchScore === null ? EMPTY : `${matchScore}%`}</Field>
      <Field label="Fit">
        {fit.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5">
            {fit.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        ) : (
          EMPTY
        )}
      </Field>
      <Field label="Gaps">
        {gaps.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5">
            {gaps.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        ) : (
          EMPTY
        )}
      </Field>
      <Field label="Strategy">{strategy ?? EMPTY}</Field>
      <Field label="Unclear">
        {unclear.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5">
            {unclear.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        ) : (
          EMPTY
        )}
      </Field>
    </div>
  )
}

function PositioningEditDialog({
  application,
  open,
  onOpenChange,
  onSaved,
}: {
  application: JobApplicationDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [fit, setFit] = useState('')
  const [gaps, setGaps] = useState('')
  const [strategy, setStrategy] = useState('')
  const [unclear, setUnclear] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setFit(listToLines(application.fit))
    setGaps(listToLines(application.gaps))
    setStrategy(application.strategy ?? '')
    setUnclear(listToLines(application.unclear))
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await patchJobApplication(application.id, {
        fit: linesToList(fit),
        gaps: linesToList(gaps),
        strategy: strategy.trim() || null,
        unclear: linesToList(unclear),
      })
      onOpenChange(false)
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[70vh] w-full max-w-lg flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit positioning analysis</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <p className="text-xs text-muted-foreground">
            Match score is computed from the positioning breakdown document (D-47), not edited here.
          </p>
          <FormField label="Fit (one point per line)">
            <Textarea rows={3} value={fit} onChange={(event) => setFit(event.target.value)} />
          </FormField>
          <FormField label="Gaps (one point per line)">
            <Textarea rows={3} value={gaps} onChange={(event) => setGaps(event.target.value)} />
          </FormField>
          <FormField label="Strategy">
            <Textarea
              rows={3}
              value={strategy}
              onChange={(event) => setStrategy(event.target.value)}
            />
          </FormField>
          <FormField label="Unclear (one point per line)">
            <Textarea
              rows={3}
              value={unclear}
              onChange={(event) => setUnclear(event.target.value)}
            />
          </FormField>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
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

function ApplicationHistory({
  application,
  onChanged,
}: {
  application: JobApplicationDetail
  onChanged: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  const [generateOpen, setGenerateOpen] = useState(false)
  // Generate (LLM) never touches notes (D-127) or status_history directly - next_action/due_date
  // are the fields it actually writes, so whether either has a value is what "has data" means
  // here, the same way Job details' own hasData tracks description/requirements.
  const hasData = application.next_action !== null || application.due_date !== null
  const ready = application.description !== null && application.requirements.length > 0
  return (
    <Section
      title="Application history"
      actions={
        <SectionActions
          hasData={hasData}
          onEdit={() => setEditOpen(true)}
          onGenerate={() => setGenerateOpen(true)}
          generateDisabled={!ready}
          generateTitle="Fill in Job details first."
        />
      }
    >
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <StatusTimeline history={application.status_history} currentStatus={application.status} />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <Field label="Notes">
            {application.notes ?? <span className="text-muted-foreground">No notes.</span>}
          </Field>
          <Field label="Next action">{application.next_action ?? EMPTY}</Field>
          <Field label="Due date">{application.due_date ?? EMPTY}</Field>
        </div>

        <EmailsColumn
          applicationId={application.id}
          files={application.files.filter((file) => EMAIL_KINDS.has(file.kind))}
        />
      </div>

      <ApplicationHistoryEditDialog
        application={application}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={onChanged}
      />
      {hasData ? (
        <JobReviseOverlay
          applicationId={application.id}
          sectionKind="application_history"
          title="Application history"
          leftPane={
            <CurrentApplicationHistoryPane
              nextAction={application.next_action}
              dueDate={application.due_date}
            />
          }
          allowAttachment
          open={generateOpen}
          onOpenChange={setGenerateOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Application history"
          hasData={hasData}
          open={generateOpen}
          onOpenChange={setGenerateOpen}
          onSubmit={() => generateApplicationHistory(application.id)}
          onChanged={onChanged}
        />
      )}
    </Section>
  )
}

// JobReviseOverlay's left pane for Application history (D-138): next_action and due_date exactly
// as the chat prompt presents them. notes is left out - the chat never reads or writes it
// (D-127), so showing it here would suggest otherwise.
function CurrentApplicationHistoryPane({
  nextAction,
  dueDate,
}: {
  nextAction: string | null
  dueDate: string | null
}) {
  if (!nextAction && !dueDate) {
    return <p className="text-sm text-muted-foreground">Nothing to revise yet.</p>
  }
  return (
    <div className="flex flex-col gap-3 text-sm">
      <Field label="Next action">{nextAction ?? EMPTY}</Field>
      <Field label="Due date">{dueDate ?? EMPTY}</Field>
    </div>
  )
}

function ApplicationHistoryEditDialog({
  application,
  open,
  onOpenChange,
  onSaved,
}: {
  application: JobApplicationDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [notes, setNotes] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [dueDate, setDueDate] = useState('')
  // One optional date-only string per status (D-117), keyed by status name. A blank value means
  // that stage has no date - unreached, or cleared.
  const [stageDates, setStageDates] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setNotes(application.notes ?? '')
    setNextAction(application.next_action ?? '')
    setDueDate(application.due_date ?? '')
    const dates: Record<string, string> = {}
    for (const entry of application.status_history) dates[entry.status] = dateOnly(entry.changed_at)
    setStageDates(dates)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function setStageDate(status: string, value: string) {
    setStageDates((current) => ({ ...current, [status]: value }))
  }

  async function save() {
    const entries = ALL_STATUSES.filter((status) => stageDates[status])
      .map((status) => ({ status, changed_at: toChangedAt(stageDates[status]) }))
    if (entries.length === 0) {
      setError('At least one stage needs a date.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await patchJobApplication(application.id, {
        notes: notes.trim() || null,
        next_action: nextAction.trim() || null,
        due_date: dueDate.trim() || null,
      })
      await replaceStatusHistory(application.id, entries)
      onOpenChange(false)
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[70vh] w-full max-w-lg flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit application history</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <FormField label="Notes">
            <Textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} />
          </FormField>
          <FormField label="Next action">
            <Input value={nextAction} onChange={(event) => setNextAction(event.target.value)} />
          </FormField>
          <FormField label="Due date">
            <Input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
          </FormField>
          <FormField label="Stages">
            <div className="flex flex-col gap-2">
              {ALL_STATUSES.map((status) => (
                <div key={status} className="flex items-center gap-2">
                  <span className="w-24 shrink-0 text-xs text-foreground">{status}</span>
                  <Input
                    type="date"
                    className="flex-1"
                    value={stageDates[status] ?? ''}
                    onChange={(event) => setStageDate(status, event.target.value)}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setStageDate(status, todayDateOnly())}
                  >
                    Today
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={!stageDates[status]}
                    aria-label={`Clear the ${status} date`}
                    onClick={() => setStageDate(status, '')}
                  >
                    ×
                  </Button>
                </div>
              ))}
            </div>
          </FormField>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// Email history (D-57, D-111): the same `files` array Additional files reads, filtered to the
// eml/msg kinds and sorted newest first — not a second list, so an email can only show here if
// it is also filed there (D-112). Preview reuses the same overlay Files' file rows use (D-116).
function EmailsColumn({
  applicationId,
  files,
}: {
  applicationId: number
  files: JobApplicationFile[]
}) {
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
            <EmailRow key={file.id} applicationId={applicationId} file={file} />
          ))}
        </ul>
      )}
    </div>
  )
}

function EmailRow({ applicationId, file }: { applicationId: number; file: JobApplicationFile }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  return (
    <li className="group/file flex items-center justify-between gap-2 px-3 py-2 text-sm">
      <div className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
        <span className="truncate">{file.name.replace(/\.(eml|msg)$/i, '')}</span>
        {file.date && (
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
            {file.date.slice(0, 10)}
          </span>
        )}
      </div>
      <div className="shrink-0 opacity-0 transition-opacity focus-within:opacity-100 group-hover/file:opacity-100">
        <Button variant="outline" size="sm" onClick={() => setPreviewOpen(true)}>
          Preview
        </Button>
      </div>
      <FilePreview
        source={{ table: 'job_file', applicationId, id: file.id }}
        name={file.name}
        open={previewOpen}
        onOpenChange={setPreviewOpen}
      />
    </li>
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

// Tailored CV and cover letter files don't exist until Phase 5 writes them (D-57); their
// subsections just read "Not done yet.", matching the Flags wording above, until then.
const TAILORED_CV_KIND = 'tailored_cv'
const COVER_LETTER_KINDS = new Set(['cover_letter'])
// The Emails column in Application history (D-111) and the Emails subsection here read the same
// set out of the same `files` array, not a second list, so an email can only show in either place
// because it is also a filed, listed email (D-112, extended by D-115).
const EMAIL_KINDS = new Set(['eml', 'msg'])

// JobReviseOverlay's left pane for Tailored CV and Cover letter (D-141): a live preview of the
// current file, reusing FilePreview's own loading/rendering rather than a second viewer - the
// same pane GenerateSectionOverlay's preview mode showed before these two sections had a real
// chat. `open` gates the fetch the same way FilePreview's own Dialog `open` does, and since a
// successful turn replaces the file (a new job_files row, D-115), the new `fileId` that flows
// down once the page refetches triggers its own refetch automatically.
function JobFileRevisePreview({
  applicationId,
  fileId,
  name,
  open,
}: {
  applicationId: number
  fileId: number
  name: string
  open: boolean
}) {
  const state = useFilePreview({ table: 'job_file', applicationId, id: fileId }, open)
  return <FilePreviewBody name={name} state={state} />
}

function Files({
  application,
  onChanged,
}: {
  application: JobApplicationDetail
  onChanged: () => void
}) {
  const files = application.files
  const listing = files.filter((file) => file.kind === 'listing')
  const tailoredCv = files.filter((file) => file.kind === TAILORED_CV_KIND)
  const coverLetter = files.filter((file) => COVER_LETTER_KINDS.has(file.kind))
  const emails = files.filter((file) => EMAIL_KINDS.has(file.kind))
  const additional = files.filter(
    (file) =>
      file.kind !== 'listing' &&
      file.kind !== 'master_cv' &&
      file.kind !== TAILORED_CV_KIND &&
      // The positioning breakdown document has its own access point (Positioning analysis's
      // "Check reasoning" link, D-102) - it isn't a loose file to also list here.
      file.kind !== 'positioning_breakdown' &&
      !COVER_LETTER_KINDS.has(file.kind) &&
      !EMAIL_KINDS.has(file.kind),
  )
  const [listingOverlayOpen, setListingOverlayOpen] = useState(false)
  const [tailoredCvOverlayOpen, setTailoredCvOverlayOpen] = useState(false)
  const [coverLetterOverlayOpen, setCoverLetterOverlayOpen] = useState(false)
  const [profileDocsReady, setProfileDocsReady] = useState<boolean | null>(null)
  const [hasCoverLetterTemplate, setHasCoverLetterTemplate] = useState<boolean | null>(null)

  // Tailored CV's and Cover letter's gates (job-llm-steps.md §5-6, D-128): the pieces not
  // already on `application` need their own fetch, the same way Positioning analysis's gate does.
  useEffect(() => {
    let cancelled = false
    fetchProfileOutputs()
      .then((outputs) => {
        if (!cancelled) setProfileDocsReady(outputs.length === 3)
      })
      .catch(() => {
        if (!cancelled) setProfileDocsReady(false)
      })
    fetchProfileFiles()
      .then((profileFiles) => {
        if (!cancelled) {
          setHasCoverLetterTemplate(
            profileFiles.some(
              (file) =>
                file.kind === 'cover_letter_template' &&
                file.original_name.toLowerCase().endsWith('.docx'),
            ),
          )
        }
      })
      .catch(() => {
        if (!cancelled) setHasCoverLetterTemplate(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const hasBreakdown = files.some((file) => file.kind === 'positioning_breakdown')
  const hasJobDetails = application.description !== null && application.requirements.length > 0
  // A Master CV may legitimately be a PDF/TXT/MD upload (D-54's ALLOWED_EXTENSIONS) - only a
  // real .docx can be read and edited by docx_editor.py (D-130), so the gate checks the name,
  // not just that something is selected.
  const hasDocxMasterCv =
    application.master_cv_profile_file_id !== null &&
    (application.master_cv_name ?? '').toLowerCase().endsWith('.docx')
  const tailoredCvReady = profileDocsReady === true && hasDocxMasterCv && hasJobDetails && hasBreakdown
  const coverLetterReady = tailoredCvReady && tailoredCv.length > 0 && hasCoverLetterTemplate === true

  return (
    <Section title="Files">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <MasterCvField application={application} onChanged={onChanged} />
        <FileGroup
          applicationId={application.id}
          title="Listing"
          files={listing}
          empty="No listing file yet."
          uploadKind={() => 'listing'}
          onGenerateClick={() => setListingOverlayOpen(true)}
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Tailored CV"
          files={tailoredCv}
          empty="Not done yet."
          uploadKind={() => 'tailored_cv'}
          onGenerateClick={() => setTailoredCvOverlayOpen(true)}
          generateDisabled={!tailoredCvReady}
          generateTitle="Needs a selected Master CV in .docx format, the three LLM profile documents, Job details filled in, and a positioning breakdown document first."
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Cover letter"
          files={coverLetter}
          empty="Not done yet."
          uploadKind={() => 'cover_letter'}
          onGenerateClick={() => setCoverLetterOverlayOpen(true)}
          generateDisabled={!coverLetterReady}
          generateTitle="Needs a Tailored CV, Job details filled in, the three LLM profile documents, a positioning breakdown document, and a cover letter template uploaded in .docx format first."
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Emails"
          files={emails}
          empty="No emails yet."
          generatable={false}
          uploadKind={(file) => (file.name.toLowerCase().endsWith('.msg') ? 'msg' : 'eml')}
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Additional files"
          files={additional}
          empty="No additional files."
          showKind
          generatable={false}
          uploadKind={() => 'other'}
          onChanged={onChanged}
        />
      </div>
      <GenerateListingOverlay
        applicationId={application.id}
        currentListing={listing[0] ?? null}
        open={listingOverlayOpen}
        onOpenChange={setListingOverlayOpen}
        onChanged={onChanged}
      />
      {tailoredCv.length > 0 ? (
        <JobReviseOverlay
          applicationId={application.id}
          sectionKind="tailored_cv"
          title="Tailored CV"
          leftPane={
            <JobFileRevisePreview
              applicationId={application.id}
              fileId={tailoredCv[0].id}
              name={tailoredCv[0].name}
              open={tailoredCvOverlayOpen}
            />
          }
          open={tailoredCvOverlayOpen}
          onOpenChange={setTailoredCvOverlayOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Tailored CV"
          hasData={false}
          open={tailoredCvOverlayOpen}
          onOpenChange={setTailoredCvOverlayOpen}
          onSubmit={() => generateTailoredCv(application.id)}
          onChanged={onChanged}
        />
      )}
      {coverLetter.length > 0 ? (
        <JobReviseOverlay
          applicationId={application.id}
          sectionKind="cover_letter"
          title="Cover letter"
          leftPane={
            <JobFileRevisePreview
              applicationId={application.id}
              fileId={coverLetter[0].id}
              name={coverLetter[0].name}
              open={coverLetterOverlayOpen}
            />
          }
          open={coverLetterOverlayOpen}
          onOpenChange={setCoverLetterOverlayOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Cover letter"
          hasData={false}
          open={coverLetterOverlayOpen}
          onOpenChange={setCoverLetterOverlayOpen}
          onSubmit={() => generateCoverLetter(application.id)}
          onChanged={onChanged}
        />
      )}
    </Section>
  )
}

// D-57/D-116: which uploaded master CV this application uses, proposed by Claude when the
// listing is added and changeable by the user — a reference to one of the Profile page's master
// CVs (profile_files.id), not a document of its own, so it's a selector rather than a FileGroup
// with Revise/Upload, and it has no Preview/Open: the Profile page is where the file lives.
function MasterCvField({
  application,
  onChanged,
}: {
  application: JobApplicationDetail
  onChanged: () => void
}) {
  const [options, setOptions] = useState<ProfileFile[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchProfileFiles()
      .then((files) => {
        if (!cancelled) setOptions(files.filter((file) => file.kind === 'master_cv'))
      })
      .catch(() => {
        if (!cancelled) setOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function choose(value: string) {
    setBusy(true)
    setError(null)
    try {
      await setMasterCv(application.id, value === NONE ? null : Number(value))
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The selection was not saved.')
    } finally {
      setBusy(false)
    }
  }

  const value =
    application.master_cv_profile_file_id === null
      ? NONE
      : String(application.master_cv_profile_file_id)
  // Select.Value resolves a label from this map even while the popup is closed and its
  // SelectItems aren't mounted - without it, a closed trigger shows the raw value (e.g. "none"
  // or a bare numeric id) instead of its label.
  const items: Record<string, string> = { [NONE]: 'Not selected' }
  for (const file of options ?? []) items[String(file.id)] = file.original_name

  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Master CV
      </h3>
      <Select
        items={items}
        value={value}
        onValueChange={(next) => next && void choose(next)}
        disabled={busy || options === null}
      >
        <SelectTrigger className="w-full">
          <SelectValue placeholder="Not selected" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>Not selected</SelectItem>
          {options?.map((file) => (
            <SelectItem key={file.id} value={String(file.id)}>
              {file.original_name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

// A sentinel distinct from any real profile_files id, for the Select's "nothing chosen" item.
const NONE = 'none'

// Listing, Tailored CV and Cover letter can be written by the LLM or uploaded, so they get
// Revise/Generate (LLM) plus Upload when empty (D-114). Emails and Additional files are never
// LLM-written — Emails are filed from the user's inbox (Phase 6), Additional files is a catch-all
// — so both skip the LLM button and always offer Upload, data or not (D-114, D-115).
function FileGroup({
  applicationId,
  title,
  files,
  empty,
  showKind = false,
  generatable = true,
  onGenerateClick,
  generateDisabled,
  generateTitle,
  uploadKind,
  onChanged,
}: {
  applicationId: number
  title: string
  files: JobApplicationFile[]
  empty: string
  showKind?: boolean
  generatable?: boolean
  // When given, the LLM button is real (Listing, Tailored CV, Cover letter) instead of the
  // disabled stub a generatable subsection would otherwise show.
  onGenerateClick?: () => void
  generateDisabled?: boolean
  generateTitle?: string
  uploadKind: (file: File) => string
  onChanged: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasData = files.length > 0

  async function handleChosen(chosen: FileList | null) {
    const file = chosen?.[0]
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await uploadJobFile(applicationId, uploadKind(file), file)
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The upload failed.')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="group/subsection flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {title}
        </h3>
        <div className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/subsection:opacity-100">
          <div className="flex shrink-0 gap-2">
            {generatable &&
              (onGenerateClick ? (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={generateDisabled}
                  title={generateDisabled ? generateTitle : undefined}
                  onClick={onGenerateClick}
                >
                  {llmLabel(hasData)}
                </Button>
              ) : (
                <LlmButton hasData={hasData} />
              ))}
            <input
              ref={input}
              type="file"
              className="sr-only"
              aria-label={`Choose a file for ${title}`}
              onChange={(event) => void handleChosen(event.target.files)}
            />
            {(!generatable || !hasData) && (
              <UploadButton busy={busy} onClick={() => input.current?.click()} />
            )}
          </div>
        </div>
      </div>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded border border-border">
          {files.map((file) => (
            <JobFileRow
              key={file.id}
              applicationId={applicationId}
              file={file}
              showKind={showKind}
            />
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

// One job file's row: its name, Preview (the shared overlay, D-107) and Open (the system's
// default app, D-116, the same way the Profile page's FileRow works).
function JobFileRow({
  applicationId,
  file,
  showKind,
}: {
  applicationId: number
  file: JobApplicationFile
  showKind: boolean
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function open() {
    setBusy(true)
    setError(null)
    try {
      await openJobFile(applicationId, file.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be opened.')
    } finally {
      setBusy(false)
    }
  }

  async function reveal() {
    setBusy(true)
    setError(null)
    try {
      await revealJobFile(applicationId, file.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The folder could not be opened.')
    } finally {
      setBusy(false)
    }
  }

  async function download() {
    setBusy(true)
    setError(null)
    try {
      await downloadJobFile(applicationId, file.id, file.name)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be downloaded.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="group/file flex flex-col gap-1 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-4">
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
          <div className="flex items-center gap-2 opacity-0 transition-opacity focus-within:opacity-100 group-hover/file:opacity-100">
            <Button variant="outline" size="sm" onClick={() => setPreviewOpen(true)}>
              Preview
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void open()}>
              Open
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={busy}
              title="Download"
              aria-label={`Download ${file.name}`}
              onClick={() => void download()}
            >
              <Download className="size-3.5" aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={busy}
              title="Show in folder"
              aria-label={`Show ${file.name} in folder`}
              onClick={() => void reveal()}
            >
              <FolderOpen className="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      <FilePreview
        source={{ table: 'job_file', applicationId, id: file.id }}
        name={file.name}
        open={previewOpen}
        onOpenChange={setPreviewOpen}
      />
    </li>
  )
}
