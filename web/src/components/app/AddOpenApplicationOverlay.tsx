import { Plus, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { QueueStatusBadge } from '@/components/app/QueueStatusBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  createOpenApplication,
  extractOpenApplicationResearch,
  fetchOpenApplicationIdentityResult,
  fetchProfileFiles,
  startOpenApplicationIdentity,
} from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type {
  AddOpenApplicationResult,
  AddOpenApplicationWorkflow,
  OpenApplicationIdentityAnswer,
  OpenApplicationTargetType,
  ProfileFile,
  QueueStatus,
} from '@/lib/types'
import { TARGET_TYPE_LABELS as TARGET_TYPE_ITEMS } from '@/lib/openApplicationLabels'

const MAX_RESEARCH_ITEMS = 5
const NONE = 'none'

type Stage = 'workflow' | 'source' | 'review' | 'fields' | 'done'
type ResearchItemDraft = { sourceType: 'url' | 'text'; content: string }

// D-296: which of Sources/Relevance/CV & Cover letter/CV & Introduction message get staged
// right after the row is created - matches AddJobOverlay's own WORKFLOWS title/subtitle list,
// branching after CV instead of nesting, since Open Applications have two separate optional
// deliverables rather than one combined "full" chain.
const WORKFLOWS: { value: AddOpenApplicationWorkflow; title: string; subtitle: string }[] = [
  {
    value: 'sources',
    title: 'Sources',
    subtitle: 'Just clean up the research sources into their own files.',
  },
  {
    value: 'relevance',
    title: '+ Relevance',
    subtitle: 'Also fill in Industry, Company type, Summary and Relevance.',
  },
  {
    value: 'cv_cover_letter',
    title: '+ CV & Cover letter',
    subtitle: 'Also write a tailored CV and cover letter (needs a Master CV).',
  },
  {
    value: 'cv_introduction',
    title: '+ CV & Introduction message',
    subtitle: 'Also write a tailored CV and an introduction message (needs a Master CV).',
  },
]

function emptyItem(): ResearchItemDraft {
  return { sourceType: 'text', content: '' }
}

// "Add Open Application" (D-251, revised; D-296 adds the workflow stage): a staged wizard
// mirroring Add Job's own workflow/source/review/identity flow. 0) choose the workflow chain
// (and a Master CV for the two that need one). 1) only research sources are given - no manual
// fields yet. 2) each source is extracted (code-only) and merged into one combined, editable
// text box. 3) that reviewed text is run through Company details' own field-mapping prompt
// before any row exists; the result pre-fills the fields below, all still editable. 4) "Create"
// writes the row with the reviewed text as this application's research and the confirmed
// fields, then queues the chosen workflow chain (staged, D-286) - Company details' own fields
// are never queued at creation, since they're already resolved by step 3.
export function AddOpenApplicationOverlay({
  open,
  onOpenChange,
  onCreated,
  onOpenApplication,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
  onOpenApplication: (applicationId: number) => void
}) {
  const [stage, setStage] = useState<Stage>('workflow')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Stage: workflow
  const [workflow, setWorkflow] = useState<AddOpenApplicationWorkflow>('sources')
  const [masterCvOptions, setMasterCvOptions] = useState<ProfileFile[] | null>(null)
  const [masterCvId, setMasterCvId] = useState<number | null>(null)

  // Stage: source
  const [items, setItems] = useState<ResearchItemDraft[]>([emptyItem()])

  // Stage: review
  const [reviewText, setReviewText] = useState('')

  // Stage: fields
  const [identityJobId, setIdentityJobId] = useState<number | null>(null)
  const [fieldsLoading, setFieldsLoading] = useState(false)
  const [targetName, setTargetName] = useState('')
  const [targetType, setTargetType] = useState<OpenApplicationTargetType | ''>('')
  const [contactName, setContactName] = useState('')
  const [contactTitle, setContactTitle] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [contactUrl, setContactUrl] = useState('')
  const [angle, setAngle] = useState('')
  const [whyThisCompany, setWhyThisCompany] = useState('')
  const [otherNotes, setOtherNotes] = useState('')

  // Stage: done
  const [result, setResult] = useState<AddOpenApplicationResult | null>(null)

  const { jobs } = useClaudeJobs()
  const identityJob = identityJobId === null ? null : (jobs.find((job) => job.id === identityJobId) ?? null)
  const stagedJobs = result?.claude_job_ids.map((id) => jobs.find((job) => job.id === id) ?? null) ?? []

  function reset() {
    setStage('workflow')
    setBusy(false)
    setError(null)
    setWorkflow('sources')
    setMasterCvId(null)
    setItems([emptyItem()])
    setReviewText('')
    setIdentityJobId(null)
    setFieldsLoading(false)
    setTargetName('')
    setTargetType('')
    setContactName('')
    setContactTitle('')
    setContactEmail('')
    setContactUrl('')
    setAngle('')
    setWhyThisCompany('')
    setOtherNotes('')
    setResult(null)
  }

  // Reset to a clean wizard each time the overlay opens, so a cancelled attempt never leaks
  // into the next one (mirrors AddJobOverlay).
  useEffect(() => {
    if (open) reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    let cancelled = false
    fetchProfileFiles()
      .then((files) => {
        if (!cancelled) setMasterCvOptions(files.filter((file) => file.kind === 'master_cv'))
      })
      .catch(() => {
        if (!cancelled) setMasterCvOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  function updateItem(index: number, next: Partial<ResearchItemDraft>) {
    setItems((current) => current.map((item, i) => (i === index ? { ...item, ...next } : item)))
  }

  async function fetchAndReview() {
    const nonEmpty = items.filter((item) => item.content.trim() !== '')
    if (nonEmpty.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const results = await extractOpenApplicationResearch(
        nonEmpty.map((item) => ({ source_type: item.sourceType, content: item.content.trim() })),
      )
      const merged = results
        .map((result) => result.extracted_text)
        .filter((text): text is string => Boolean(text && text.trim()))
        .join('\n\n---\n\n')
      if (!merged) {
        setError('None of these produced any readable text. Try a different source.')
        return
      }
      setReviewText(merged)
      setStage('review')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'That could not be read.')
    } finally {
      setBusy(false)
    }
  }

  function startFields() {
    setStage('fields')
    setFieldsLoading(true)
    setError(null)
    startOpenApplicationIdentity(reviewText)
      .then((job) => setIdentityJobId(job.id))
      .catch((failure: unknown) => {
        setFieldsLoading(false)
        setError(
          failure instanceof ApiError ? failure.message : 'Could not start reading the text.',
        )
      })
  }

  // Once the identity job finishes, read its parsed answer back and pre-fill the fields form -
  // still fully editable afterward (mirrors AddJobOverlay's own identity-result effect).
  useEffect(() => {
    if (!identityJob || identityJobId === null) return
    if (identityJob.status === 'failed') {
      setFieldsLoading(false)
      setError(identityJob.error ?? 'Could not read the text. Fill in the fields by hand below.')
      return
    }
    if (identityJob.status !== 'done') return
    let cancelled = false
    fetchOpenApplicationIdentityResult(identityJobId)
      .then((answer: OpenApplicationIdentityAnswer) => {
        if (cancelled) return
        setTargetName(answer.target_name ?? '')
        setTargetType(answer.target_type ?? '')
        setContactName(answer.contact_name ?? '')
        setContactTitle(answer.contact_title ?? '')
        setContactEmail(answer.contact_email ?? '')
        setContactUrl(answer.contact_url ?? '')
        setWhyThisCompany(answer.why_this_company ?? '')
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setError(
          failure instanceof ApiError
            ? failure.message
            : 'Could not read the suggested fields. Fill them in by hand below.',
        )
      })
      .finally(() => {
        if (!cancelled) setFieldsLoading(false)
      })
    return () => {
      cancelled = true
    }
    // useClaudeJobs() polls every few seconds and hands back a brand new `jobs` array (and so a
    // new `identityJob` object) each time, even once the job is already "done" - depending on
    // the object itself re-ran this effect, and so re-fetched and overwrote the fields, on every
    // poll tick while this stage was open. identityJob.status is the real trigger; its own
    // string value only changes when the job's actual status changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityJob?.status, identityJobId])

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const created = await createOpenApplication({
        target_name: targetName.trim() || null,
        target_type: targetType || null,
        contact_name: contactName.trim() || null,
        contact_title: contactTitle.trim() || null,
        contact_email: contactEmail.trim() || null,
        contact_url: contactUrl.trim() || null,
        angle: angle.trim() || null,
        why_this_company: whyThisCompany.trim() || null,
        other_notes: otherNotes.trim() || null,
        research_items: reviewText.trim()
          ? [{ source_type: 'text', content: reviewText.trim() }]
          : [],
        workflow,
        master_cv_profile_file_id: masterCvId,
      })
      onCreated()
      setResult(created)
      setStage('done')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'This could not be created.')
    } finally {
      setBusy(false)
    }
  }

  function close(nextOpen: boolean) {
    if (!nextOpen) reset()
    onOpenChange(nextOpen)
  }

  const canFetch = items.some((item) => item.content.trim() !== '')
  const targetTypeItems: Record<string, string> = { [NONE]: 'Not set', ...TARGET_TYPE_ITEMS }
  const needsMasterCv = workflow === 'cv_cover_letter' || workflow === 'cv_introduction'
  const canUseWorkflow = !needsMasterCv || masterCvId !== null
  const masterCvItems: Record<string, string> = { [NONE]: 'Not selected' }
  for (const file of masterCvOptions ?? []) masterCvItems[String(file.id)] = file.original_name

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="flex h-[85vh] w-full max-w-3xl flex-col gap-3 sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Add Open Application</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
          {stage === 'workflow' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-muted-foreground">
                Choose how much to run automatically once this application is added.
              </p>
              <div className="flex flex-col gap-2">
                {WORKFLOWS.map((candidate) => (
                  <button
                    key={candidate.value}
                    type="button"
                    onClick={() => setWorkflow(candidate.value)}
                    className={
                      'flex flex-col gap-0.5 rounded border px-3 py-2 text-left transition-colors ' +
                      (workflow === candidate.value
                        ? 'border-primary bg-secondary'
                        : 'border-border hover:bg-muted')
                    }
                  >
                    <span className="text-sm font-semibold">{candidate.title}</span>
                    <span className="text-xs text-muted-foreground">{candidate.subtitle}</span>
                  </button>
                ))}
              </div>
              {needsMasterCv && (
                <div className="flex flex-col gap-2">
                  <Label>Master CV</Label>
                  <Select
                    items={masterCvItems}
                    value={masterCvId === null ? NONE : String(masterCvId)}
                    onValueChange={(next) =>
                      setMasterCvId(next === NONE || !next ? null : Number(next))
                    }
                    disabled={masterCvOptions === null}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Not selected" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>Not selected</SelectItem>
                      {masterCvOptions?.map((file) => (
                        <SelectItem key={file.id} value={String(file.id)}>
                          {file.original_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {masterCvId === null && (
                    <p className="text-xs text-muted-foreground">
                      The CV workflows need a Master CV selected.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {stage === 'source' && (
            <div className="flex flex-col gap-2">
              <Label>Research (up to {MAX_RESEARCH_ITEMS}) - a URL or pasted text each</Label>
              <p className="text-xs text-muted-foreground">
                Anything relevant: company news, their careers page, a product page, who you know
                there. Each source is fetched and merged into one reviewable text below, which
                Claude then maps into the fields - you don&apos;t need to label each item.
              </p>
              {items.map((item, index) => (
                <div key={index} className="flex gap-2">
                  <Select
                    items={{ text: 'Text', url: 'URL' }}
                    value={item.sourceType}
                    onValueChange={(value) =>
                      value && updateItem(index, { sourceType: value as 'url' | 'text' })
                    }
                  >
                    <SelectTrigger className="w-24 shrink-0">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="text">Text</SelectItem>
                      <SelectItem value="url">URL</SelectItem>
                    </SelectContent>
                  </Select>
                  {item.sourceType === 'url' ? (
                    <Input
                      placeholder="https://..."
                      value={item.content}
                      onChange={(event) => updateItem(index, { content: event.target.value })}
                    />
                  ) : (
                    <Textarea
                      rows={2}
                      placeholder="Paste anything relevant..."
                      value={item.content}
                      onChange={(event) => updateItem(index, { content: event.target.value })}
                      className="flex-1 resize-none"
                    />
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label="Remove this item"
                    onClick={() => setItems((current) => current.filter((_, i) => i !== index))}
                    disabled={items.length === 1}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              ))}
              {items.length < MAX_RESEARCH_ITEMS && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => setItems((current) => [...current, emptyItem()])}
                >
                  <Plus className="size-3.5" aria-hidden="true" />
                  Add another item
                </Button>
              )}
            </div>
          )}

          {stage === 'review' && (
            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <Label>Reviewed text - edit anything before continuing</Label>
              <Textarea
                value={reviewText}
                onChange={(event) => setReviewText(event.target.value)}
                className="min-h-0 flex-1 resize-none font-mono text-xs"
              />
            </div>
          )}

          {stage === 'fields' && (
            <div className="flex flex-col gap-4">
              {fieldsLoading && (
                <p className="text-sm text-muted-foreground">Reading the text...</p>
              )}
              {workflow !== 'sources' && (
                <p className="text-xs text-muted-foreground">
                  Industry, Company type, Summary and Relevance aren&apos;t shown here - your
                  chosen workflow generates them automatically once you click Create, after the
                  sources below are cleaned up.
                </p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label>Target name</Label>
                  <Input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Target type</Label>
                  <Select
                    items={targetTypeItems}
                    value={targetType === '' ? NONE : targetType}
                    onValueChange={(value) =>
                      setTargetType(
                        value === NONE || !value ? '' : (value as OpenApplicationTargetType),
                      )
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
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Contact name</Label>
                  <Input value={contactName} onChange={(event) => setContactName(event.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Contact title</Label>
                  <Input value={contactTitle} onChange={(event) => setContactTitle(event.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Contact email</Label>
                  <Input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Contact URL (e.g. LinkedIn)</Label>
                  <Input value={contactUrl} onChange={(event) => setContactUrl(event.target.value)} />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Angle - your own connection, e.g. a referral or someone you know there</Label>
                <Textarea
                  rows={2}
                  value={angle}
                  onChange={(event) => setAngle(event.target.value)}
                  className="resize-none"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Why this company</Label>
                <Textarea
                  rows={2}
                  value={whyThisCompany}
                  onChange={(event) => setWhyThisCompany(event.target.value)}
                  className="resize-none"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>Other</Label>
                <Textarea
                  rows={2}
                  value={otherNotes}
                  onChange={(event) => setOtherNotes(event.target.value)}
                  className="resize-none"
                />
              </div>
            </div>
          )}

          {stage === 'done' && result && (
            <div className="flex flex-col gap-2">
              {/* Read from live-polled job data (stagedJobs), not assumed from result alone -
                  mirrors AddJobOverlay's own staged summary (D-288). */}
              <p className="text-sm text-muted-foreground">
                {stagedJobs.length > 0 && stagedJobs.every((job) => job?.status === 'staged')
                  ? `${stagedJobs.length} step${stagedJobs.length === 1 ? '' : 's'} staged. They run once you click "Trigger workflows" in the header.`
                  : 'Added. Each step below runs on its own; its status updates live.'}
              </p>
              <ul className="flex flex-col gap-1">
                {result.claude_job_ids.map((id) => {
                  const job = stagedJobs.find((candidate) => candidate?.id === id) ?? null
                  return (
                    <li key={id} className="flex items-center gap-2 text-sm text-muted-foreground">
                      <span>{job?.label ?? `Job ${id}`}</span>
                      {job && <QueueStatusBadge status={job.status as QueueStatus} />}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          {stage === 'workflow' && (
            <>
              <Button variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button disabled={!canUseWorkflow} onClick={() => setStage('source')}>
                Next
              </Button>
            </>
          )}
          {stage === 'source' && (
            <>
              <Button variant="outline" onClick={() => setStage('workflow')}>
                Back
              </Button>
              <Button disabled={busy || !canFetch} onClick={() => void fetchAndReview()}>
                {busy ? 'Fetching...' : 'Fetch'}
              </Button>
            </>
          )}
          {stage === 'review' && (
            <>
              <Button variant="outline" onClick={() => setStage('source')}>
                Back
              </Button>
              <Button disabled={!reviewText.trim()} onClick={startFields}>
                Continue
              </Button>
            </>
          )}
          {stage === 'fields' && (
            <>
              <Button variant="outline" onClick={() => setStage('review')}>
                Back
              </Button>
              <Button disabled={busy || fieldsLoading} onClick={() => void create()}>
                {busy ? 'Creating...' : 'Create'}
              </Button>
            </>
          )}
          {stage === 'done' && result && (
            <>
              <Button variant="outline" onClick={reset}>
                Add another
              </Button>
              <Button
                onClick={() => {
                  const id = result.application_id
                  close(false)
                  onOpenApplication(id)
                }}
              >
                View application
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
