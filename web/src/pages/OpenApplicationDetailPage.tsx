import { ArrowLeft } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { FilePreview, FilePreviewBody, useFilePreview } from '@/components/app/FilePreview'
import { GenerateSectionOverlay } from '@/components/app/GenerateSectionOverlay'
import { OpenApplicationReviseOverlay } from '@/components/app/OpenApplicationReviseOverlay'
import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { StatusBadge } from '@/components/app/StatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  deleteOpenApplication,
  deleteOpenApplicationFile,
  downloadOpenApplicationFile,
  fetchOpenApplicationResearchItems,
  fetchProfileFiles,
  fetchProfileOutputs,
  generateOpenApplicationCoverLetter,
  generateOpenApplicationCv,
  generateOpenApplicationIntroductionMessage,
  openOpenApplicationFile,
  patchOpenApplication,
  replaceOpenApplicationStatusHistory,
  setOpenApplicationMasterCv,
  uploadOpenApplicationFile,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import type {
  OpenApplicationDetail,
  OpenApplicationEdit,
  OpenApplicationFile,
  OpenApplicationResearchItem,
  OpenApplicationTargetType,
  ProfileFile,
  StatusHistoryEntry,
} from '@/lib/types'

const MAIN_STATUSES = ['Identified', 'Applied'] as const
const END_STATUSES = ['Rejected', 'Withdrawn', 'Expired'] as const
const ALL_STATUSES = [...MAIN_STATUSES, ...END_STATUSES]
const NONE = 'none'

const TARGET_TYPE_ITEMS: Record<string, string> = {
  talent_pool: 'Talent pool',
  unsolicited: 'Unsolicited CV drop',
  cold_outreach: 'Cold outreach',
}

function todayDateOnly(): string {
  return new Date().toISOString().slice(0, 10)
}
function dateOnly(changedAt: string): string {
  return changedAt.slice(0, 10)
}
function toChangedAt(dateValue: string): string {
  return `${dateValue}T00:00:00Z`
}

const EMPTY = <span className="text-muted-foreground">Not set</span>

function Section({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
      <div className="text-sm">{children}</div>
    </div>
  )
}

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

const llmLabel = (hasData: boolean) => (hasData ? 'Revise (LLM)' : 'Generate (LLM)')

export function OpenApplicationDetailPage({
  application,
  onBack,
  onChanged,
  onDeleted,
}: {
  application: OpenApplicationDetail
  onBack: () => void
  onChanged: () => void
  onDeleted: () => void
}) {
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    const ok = window.confirm(
      `Delete ${application.target_name ?? 'this Open Application'}? This removes its files, ` +
        'status history and LLM job history, and cannot be undone.',
    )
    if (!ok) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteOpenApplication(application.id)
      onDeleted()
    } catch (failure) {
      setDeleteError(failure instanceof ApiError ? failure.message : 'This could not be deleted.')
      setDeleting(false)
    }
  }

  return (
    <section aria-labelledby="open-application-detail-heading" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack} className="self-start">
          <ArrowLeft className="size-4" aria-hidden="true" />
          Open Applications
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

      <div className="flex flex-col gap-1">
        <p className="text-sm text-muted-foreground">
          {application.target_type ? TARGET_TYPE_ITEMS[application.target_type] : 'Open Application'}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <h1 id="open-application-detail-heading" className="text-xl font-semibold tracking-tight">
            {application.target_name ?? '(unnamed)'}
          </h1>
          <StatusBadge status={application.status} />
          <QueueStatusBadge status={application.queue_status} />
        </div>
      </div>

      <CompanyDetails application={application} onChanged={onChanged} />
      <ApplicationHistory application={application} onChanged={onChanged} />
      <Files application={application} onChanged={onChanged} />
    </section>
  )
}

// --- Company details ----------------------------------------------------------------------

function CompanyDetails({
  application,
  onChanged,
}: {
  application: OpenApplicationDetail
  onChanged: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  const [reviseOpen, setReviseOpen] = useState(false)
  const hasData = Boolean(application.target_name)
  // Read fresh each time the overlay opens, for the clickable research-item badges (D-260,
  // D-261) - this page otherwise never needs the saved research items themselves.
  const [researchItems, setResearchItems] = useState<OpenApplicationResearchItem[]>([])
  useEffect(() => {
    if (!reviseOpen) return
    let cancelled = false
    fetchOpenApplicationResearchItems(application.id)
      .then((items) => {
        if (!cancelled) setResearchItems(items)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [reviseOpen, application.id])

  return (
    <Section
      title="Company details"
      actions={
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
            Edit
          </Button>
          <Button variant="outline" size="sm" disabled={!hasData} onClick={() => setReviseOpen(true)}>
            Revise (LLM)
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Target name">{application.target_name ?? EMPTY}</Field>
        <Field label="Target type">
          {application.target_type ? TARGET_TYPE_ITEMS[application.target_type] : EMPTY}
        </Field>
        <Field label="Contact">
          <ContactValue application={application} />
        </Field>
        <Field label="Angle">{application.angle ?? EMPTY}</Field>
        <Field label="Why this company">{application.why_this_company ?? EMPTY}</Field>
        <Field label="Other">{application.other_notes ?? EMPTY}</Field>
      </div>

      <CompanyDetailsEditDialog
        application={application}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={onChanged}
      />
      <OpenApplicationReviseOverlay
        applicationId={application.id}
        sectionKind="company_details"
        title="Company details"
        leftPane={<CompanyDetailsPane application={application} />}
        contextItems={researchItems.map((item) => ({
          id: item.id,
          label: `Research ${item.position}: ${researchItemLabel(item)}`,
        }))}
        open={reviseOpen}
        onOpenChange={setReviseOpen}
        onChanged={onChanged}
      />
    </Section>
  )
}

// A short label for a research-item badge: the URL itself, or the first few words of pasted
// text, truncated so a long item doesn't blow out the Context row's layout.
function researchItemLabel(item: OpenApplicationResearchItem): string {
  const text = item.source_type === 'url' ? item.content : item.content.trim()
  return text.length > 28 ? `${text.slice(0, 28)}...` : text
}

// Contact as the user asked: an email renders as a clickable mailto: link, and a contact URL
// (e.g. a LinkedIn profile) renders as its own clickable link alongside the name/title.
function ContactValue({ application }: { application: OpenApplicationDetail }) {
  if (!application.contact_name && !application.contact_email && !application.contact_url) {
    return EMPTY
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {application.contact_name && <span>{application.contact_name}</span>}
      {application.contact_title && (
        <span className="text-muted-foreground">({application.contact_title})</span>
      )}
      {application.contact_email && (
        <a
          href={`mailto:${application.contact_email}`}
          className="text-primary underline underline-offset-2"
        >
          {application.contact_email}
        </a>
      )}
      {application.contact_url && (
        <a
          href={application.contact_url}
          target="_blank"
          rel="noreferrer"
          className="text-primary underline underline-offset-2"
        >
          {application.contact_url}
        </a>
      )}
    </span>
  )
}

function CompanyDetailsPane({ application }: { application: OpenApplicationDetail }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <Field label="Target name">{application.target_name ?? EMPTY}</Field>
      <Field label="Target type">
        {application.target_type ? TARGET_TYPE_ITEMS[application.target_type] : EMPTY}
      </Field>
      <Field label="Contact">{application.contact_name ?? EMPTY}</Field>
      <Field label="Why this company">{application.why_this_company ?? EMPTY}</Field>
      <Field label="Other">{application.other_notes ?? EMPTY}</Field>
    </div>
  )
}

function CompanyDetailsEditDialog({
  application,
  open,
  onOpenChange,
  onSaved,
}: {
  application: OpenApplicationDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [targetName, setTargetName] = useState('')
  const [targetType, setTargetType] = useState<OpenApplicationTargetType | ''>('')
  const [contactName, setContactName] = useState('')
  const [contactTitle, setContactTitle] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [contactUrl, setContactUrl] = useState('')
  const [angle, setAngle] = useState('')
  const [whyThisCompany, setWhyThisCompany] = useState('')
  const [otherNotes, setOtherNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setTargetName(application.target_name ?? '')
    setTargetType(application.target_type ?? '')
    setContactName(application.contact_name ?? '')
    setContactTitle(application.contact_title ?? '')
    setContactEmail(application.contact_email ?? '')
    setContactUrl(application.contact_url ?? '')
    setAngle(application.angle ?? '')
    setWhyThisCompany(application.why_this_company ?? '')
    setOtherNotes(application.other_notes ?? '')
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function save() {
    const edit: OpenApplicationEdit = {
      target_name: targetName.trim() || null,
      target_type: targetType || null,
      contact_name: contactName.trim() || null,
      contact_title: contactTitle.trim() || null,
      contact_email: contactEmail.trim() || null,
      contact_url: contactUrl.trim() || null,
      angle: angle.trim() || null,
      why_this_company: whyThisCompany.trim() || null,
      other_notes: otherNotes.trim() || null,
    }
    setBusy(true)
    setError(null)
    try {
      await patchOpenApplication(application.id, edit)
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
      <DialogContent className="flex h-[80vh] w-full max-w-lg flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit Company details</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <FormField label="Target name">
            <Input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
          </FormField>
          <FormField label="Target type">
            <Select
              items={{ [NONE]: 'Not set', ...TARGET_TYPE_ITEMS }}
              value={targetType === '' ? NONE : targetType}
              onValueChange={(value) =>
                setTargetType(value === NONE || !value ? '' : (value as OpenApplicationTargetType))
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Not set" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Not set</SelectItem>
                {Object.entries(TARGET_TYPE_ITEMS).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <FormField label="Contact name">
              <Input value={contactName} onChange={(event) => setContactName(event.target.value)} />
            </FormField>
            <FormField label="Contact title">
              <Input value={contactTitle} onChange={(event) => setContactTitle(event.target.value)} />
            </FormField>
          </div>
          <FormField label="Contact email">
            <Input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} />
          </FormField>
          <FormField label="Contact URL (e.g. LinkedIn)">
            <Input value={contactUrl} onChange={(event) => setContactUrl(event.target.value)} />
          </FormField>
          <FormField label="Angle - your own connection">
            <Textarea rows={2} value={angle} onChange={(event) => setAngle(event.target.value)} />
          </FormField>
          <FormField label="Why this company">
            <Textarea
              rows={2}
              value={whyThisCompany}
              onChange={(event) => setWhyThisCompany(event.target.value)}
            />
          </FormField>
          <FormField label="Other">
            <Textarea rows={2} value={otherNotes} onChange={(event) => setOtherNotes(event.target.value)} />
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

// --- Application history (manual only, D-253) -------------------------------------------------

function StatusTimeline({ history, currentStatus }: { history: StatusHistoryEntry[]; currentStatus: string }) {
  const dateByStatus = new Map(history.map((entry) => [entry.status, entry.changed_at]))
  const ended = (END_STATUSES as readonly string[]).includes(currentStatus)
  const steps: readonly string[] = ended ? [...MAIN_STATUSES, currentStatus] : MAIN_STATUSES
  const lastProgressIndex = MAIN_STATUSES.reduce(
    (furthest, status, index) => (dateByStatus.has(status) ? index : furthest),
    -1,
  )
  const isProgress = (index: number) => index <= 1 && index <= lastProgressIndex

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

function ApplicationHistory({
  application,
  onChanged,
}: {
  application: OpenApplicationDetail
  onChanged: () => void
}) {
  const [editOpen, setEditOpen] = useState(false)
  return (
    <Section
      title="Application history"
      actions={
        <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
          Edit
        </Button>
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
      </div>
      <ApplicationHistoryEditDialog
        application={application}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={onChanged}
      />
    </Section>
  )
}

function ApplicationHistoryEditDialog({
  application,
  open,
  onOpenChange,
  onSaved,
}: {
  application: OpenApplicationDetail
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [notes, setNotes] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [dueDate, setDueDate] = useState('')
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
    const entries = ALL_STATUSES.filter((status) => stageDates[status]).map((status) => ({
      status,
      changed_at: toChangedAt(stageDates[status]),
    }))
    if (entries.length === 0) {
      setError('At least one stage needs a date.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await patchOpenApplication(application.id, {
        notes: notes.trim() || null,
        next_action: nextAction.trim() || null,
        due_date: dueDate.trim() || null,
      })
      await replaceOpenApplicationStatusHistory(application.id, entries)
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
          <DialogTitle>Edit Application history</DialogTitle>
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

// --- Files ---------------------------------------------------------------------------------

function MasterCvField({
  application,
  onChanged,
}: {
  application: OpenApplicationDetail
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
      await setOpenApplicationMasterCv(application.id, value === NONE ? null : Number(value))
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The selection was not saved.')
    } finally {
      setBusy(false)
    }
  }

  const value =
    application.master_cv_profile_file_id === null ? NONE : String(application.master_cv_profile_file_id)
  const items: Record<string, string> = { [NONE]: 'Not selected' }
  for (const file of options ?? []) items[String(file.id)] = file.original_name

  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Master CV</h3>
      <Select items={items} value={value} onValueChange={(next) => next && void choose(next)} disabled={busy || options === null}>
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
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function FilePreviewPane({
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
  const state = useFilePreview({ table: 'open_application_file', applicationId, id: fileId }, open)
  return (
    <div className="min-h-0 flex-1 overflow-hidden rounded border border-border bg-background">
      <FilePreviewBody name={name} state={state} />
    </div>
  )
}

function OpenApplicationFileRow({
  applicationId,
  file,
  showKind,
  onChanged,
}: {
  applicationId: number
  file: OpenApplicationFile
  showKind: boolean
  onChanged: () => void
}) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function open() {
    setBusy(true)
    setError(null)
    try {
      await openOpenApplicationFile(applicationId, file.id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be opened.')
    } finally {
      setBusy(false)
    }
  }

  async function download() {
    setBusy(true)
    setError(null)
    try {
      await downloadOpenApplicationFile(applicationId, file.id, file.name)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be downloaded.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    const ok = window.confirm(`Remove "${file.name}"? Its copy in the app is deleted.`)
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await deleteOpenApplicationFile(applicationId, file.id)
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be removed.')
      setBusy(false)
    }
  }

  return (
    <li className="group/file flex flex-col gap-1 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-col">
          <span className="truncate">{file.name}</span>
          {file.subject && <span className="truncate text-xs text-muted-foreground">{file.subject}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {showKind && (
            <Badge variant="outline" className="rounded-sm font-mono text-[11px] font-normal text-muted-foreground">
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
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void download()}>
              Download
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => void remove()}>
              Remove
            </Button>
          </div>
        </div>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <FilePreview
        source={{ table: 'open_application_file', applicationId, id: file.id }}
        name={file.name}
        open={previewOpen}
        onOpenChange={setPreviewOpen}
      />
    </li>
  )
}

function FileGroup({
  applicationId,
  title,
  files,
  empty,
  showKind = false,
  onGenerateClick,
  generateDisabled,
  generateTitle,
  onUpload,
  onChanged,
}: {
  applicationId: number
  title: string
  files: OpenApplicationFile[]
  empty: string
  showKind?: boolean
  onGenerateClick?: () => void
  generateDisabled?: boolean
  generateTitle?: string
  onUpload?: (file: File) => void
  onChanged: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasData = files.length > 0

  async function handleChosen(chosen: FileList | null) {
    const file = chosen?.[0]
    if (!file || !onUpload) return
    setBusy(true)
    setError(null)
    try {
      onUpload(file)
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <div className="group/subsection flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{title}</h3>
        <div className="opacity-0 transition-opacity focus-within:opacity-100 group-hover/subsection:opacity-100">
          <div className="flex shrink-0 gap-2">
            {onGenerateClick && (
              <Button
                variant="outline"
                size="sm"
                disabled={generateDisabled}
                title={generateDisabled ? generateTitle : undefined}
                onClick={onGenerateClick}
              >
                {llmLabel(hasData)}
              </Button>
            )}
            {onUpload && (
              <>
                <input
                  ref={input}
                  type="file"
                  className="sr-only"
                  aria-label={`Choose a file for ${title}`}
                  onChange={(event) => void handleChosen(event.target.files)}
                />
                <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
                  {busy ? 'Uploading...' : 'Upload'}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border rounded border border-border">
          {files.map((file) => (
            <OpenApplicationFileRow
              key={file.id}
              applicationId={applicationId}
              file={file}
              showKind={showKind}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

function Files({ application, onChanged }: { application: OpenApplicationDetail; onChanged: () => void }) {
  const files = application.files
  const cv = files.filter((file) => file.kind === 'tailored_cv')
  const coverLetter = files.filter((file) => file.kind === 'cover_letter')
  const introMessage = files.filter((file) => file.kind === 'introduction_message')
  const additional = files.filter((file) => file.kind === 'other')

  const [cvOverlayOpen, setCvOverlayOpen] = useState(false)
  const [letterOverlayOpen, setLetterOverlayOpen] = useState(false)
  const [introOverlayOpen, setIntroOverlayOpen] = useState(false)
  const [profileDocsReady, setProfileDocsReady] = useState<boolean | null>(null)
  const [hasCoverLetterTemplate, setHasCoverLetterTemplate] = useState<boolean | null>(null)

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
              (file) => file.kind === 'cover_letter_template' && file.original_name.toLowerCase().endsWith('.docx'),
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

  const hasCompanyDetails = Boolean(application.target_name)
  const hasDocxMasterCv =
    application.master_cv_profile_file_id !== null &&
    (application.master_cv_name ?? '').toLowerCase().endsWith('.docx')
  const cvReady = profileDocsReady === true && hasDocxMasterCv && hasCompanyDetails
  const coverLetterReady = cv.length > 0 && hasCompanyDetails && hasCoverLetterTemplate === true
  const introReady = profileDocsReady === true && hasCompanyDetails

  async function uploadAdditional(file: File) {
    try {
      await uploadOpenApplicationFile(application.id, file)
      onChanged()
    } catch {
      // surfaced by FileGroup's own error state would need plumbing through; kept minimal here.
    }
  }

  return (
    <Section title="Files">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <MasterCvField application={application} onChanged={onChanged} />
        <FileGroup
          applicationId={application.id}
          title="Tailored CV"
          files={cv}
          empty="Not done yet."
          onGenerateClick={() => setCvOverlayOpen(true)}
          generateDisabled={!cvReady}
          generateTitle="Needs Company details filled in, a .docx Master CV selected, and the three LLM profile documents first."
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Cover letter"
          files={coverLetter}
          empty="Not done yet."
          onGenerateClick={() => setLetterOverlayOpen(true)}
          generateDisabled={!coverLetterReady}
          generateTitle="Needs a Tailored CV, Company details filled in, and a cover letter template uploaded in .docx format first."
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Introduction message"
          files={introMessage}
          empty="Not done yet."
          onGenerateClick={() => setIntroOverlayOpen(true)}
          generateDisabled={!introReady}
          generateTitle="Needs Company details filled in and the three LLM profile documents first."
          onChanged={onChanged}
        />
        <FileGroup
          applicationId={application.id}
          title="Additional files"
          files={additional}
          empty="No additional files."
          showKind
          onUpload={(file) => void uploadAdditional(file)}
          onChanged={onChanged}
        />
      </div>

      {cv.length > 0 ? (
        <OpenApplicationReviseOverlay
          applicationId={application.id}
          sectionKind="tailored_cv"
          title="Tailored CV"
          leftPane={
            <FilePreviewPane
              applicationId={application.id}
              fileId={cv[0].id}
              name={cv[0].name}
              open={cvOverlayOpen}
            />
          }
          open={cvOverlayOpen}
          onOpenChange={setCvOverlayOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Tailored CV"
          hasData={false}
          open={cvOverlayOpen}
          onOpenChange={setCvOverlayOpen}
          onSubmit={() => generateOpenApplicationCv(application.id)}
          onChanged={onChanged}
        />
      )}

      {coverLetter.length > 0 ? (
        <OpenApplicationReviseOverlay
          applicationId={application.id}
          sectionKind="cover_letter"
          title="Cover letter"
          leftPane={
            <FilePreviewPane
              applicationId={application.id}
              fileId={coverLetter[0].id}
              name={coverLetter[0].name}
              open={letterOverlayOpen}
            />
          }
          open={letterOverlayOpen}
          onOpenChange={setLetterOverlayOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Cover letter"
          hasData={false}
          open={letterOverlayOpen}
          onOpenChange={setLetterOverlayOpen}
          onSubmit={() => generateOpenApplicationCoverLetter(application.id)}
          onChanged={onChanged}
        />
      )}

      {introMessage.length > 0 ? (
        <OpenApplicationReviseOverlay
          applicationId={application.id}
          sectionKind="introduction_message"
          title="Introduction message"
          leftPane={
            <FilePreviewPane
              applicationId={application.id}
              fileId={introMessage[0].id}
              name={introMessage[0].name}
              open={introOverlayOpen}
            />
          }
          open={introOverlayOpen}
          onOpenChange={setIntroOverlayOpen}
          onChanged={onChanged}
        />
      ) : (
        <GenerateSectionOverlay
          title="Introduction message"
          hasData={false}
          open={introOverlayOpen}
          onOpenChange={setIntroOverlayOpen}
          onSubmit={() => generateOpenApplicationIntroductionMessage(application.id)}
          onChanged={onChanged}
        />
      )}
    </Section>
  )
}
