import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  createJobApplication,
  fetchIntakeIdentityResult,
  fetchLanes,
  fetchProfileFiles,
  fetchPromptExchange,
  intakeCheckListingText,
  intakeDuplicateCheck,
  intakeExtractFromPaste,
  intakeExtractFromUpload,
  intakeExtractFromUrl,
  intakeExtractIdentity,
} from '@/lib/api'
import { type CheckAnswer, parseCheckAnswer } from '@/lib/parseCheckAnswer'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type {
  AddJobResult,
  AddJobWorkflow,
  DuplicateListingMatch,
  JobIdentityAnswer,
  Lane,
  ListingExtraction,
  ProfileFile,
} from '@/lib/types'

type Method = ListingExtraction['method']
type Stage = 'workflow' | 'source' | 'review' | 'identity' | 'created'

const NONE = 'none' // sentinel distinct from any real profile_files id

const WORKFLOWS: { value: AddJobWorkflow; title: string; subtitle: string }[] = [
  {
    value: 'basic',
    title: 'Listing & job details',
    subtitle: 'Create the listing file, then fill in job details.',
  },
  {
    value: 'positioning',
    title: '+ Positioning analysis',
    subtitle: 'Also run positioning against your profile (needs a Master CV).',
  },
  {
    value: 'full',
    title: '+ Tailored CV & cover letter',
    subtitle: 'Also write a tailored CV and cover letter.',
  },
]

// D-150: when the listing came from a URL, that URL is known for certain - no need to ask the
// model to infer it, and inferring it again is a source of avoidable error. www. is stripped so
// "www.linkedin.com" reads as "linkedin.com", not as two different portals depending on the link.
function portalNameFromUrl(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

// Add Job (Agent/specs/intake-steps.md, D-143 to D-146): workflow + Master CV, then the same
// source-picker/review wizard Listing's own Generate (LLM) uses, then confirming the identity
// fields extract_job_identity suggests, then creating the row. The chosen chain is queued staged,
// not queued (D-286/D-287, Phase 16) - it does not run until the header's Trigger workflows
// button (D-288) starts it, so this overlay shows a staged summary instead of live progress.
export function AddJobOverlay({
  open,
  onOpenChange,
  onCreated,
  onOpenApplication,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  // Fired once the row exists, so the table can refetch and show it even before any Claude Job
  // finishes.
  onCreated: (applicationId: number) => void
  // "View job", and the duplicate-match banner's link to the application it matched.
  onOpenApplication: (applicationId: number) => void
}) {
  const [stage, setStage] = useState<Stage>('workflow')

  // Stage: workflow
  const [workflow, setWorkflow] = useState<AddJobWorkflow>('basic')
  const [masterCvOptions, setMasterCvOptions] = useState<ProfileFile[] | null>(null)
  const [masterCvId, setMasterCvId] = useState<number | null>(null)
  // The approved lane catalog (D-182, D-215) - loaded once, the same way masterCvOptions is.
  const [laneOptions, setLaneOptions] = useState<Lane[] | null>(null)

  // Stage: source / review
  const [method, setMethod] = useState<Method>('paste')
  const [pasteValue, setPasteValue] = useState('')
  const [urlValue, setUrlValue] = useState('')
  const [extraction, setExtraction] = useState<ListingExtraction | null>(null)
  const [reviewText, setReviewText] = useState('')
  const [checkJobId, setCheckJobId] = useState<number | null>(null)
  const [checkAnswer, setCheckAnswer] = useState<CheckAnswer | null>(null)
  const [duplicateMatch, setDuplicateMatch] = useState<DuplicateListingMatch | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // Stage: identity
  const [identityJobId, setIdentityJobId] = useState<number | null>(null)
  const [identityError, setIdentityError] = useState<string | null>(null)
  const [company, setCompany] = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [lane, setLane] = useState('')
  const [location, setLocation] = useState('')
  const [portalName, setPortalName] = useState('')
  const [portalUrl, setPortalUrl] = useState('')

  // Stage: created
  const [result, setResult] = useState<AddJobResult | null>(null)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { jobs } = useClaudeJobs()
  const checkJob = jobs.find((job) => job.id === checkJobId) ?? null
  const identityJob = jobs.find((job) => job.id === identityJobId) ?? null
  const stagedJobs = result?.claude_job_ids.map((id) => jobs.find((job) => job.id === id) ?? null) ?? []

  function resetWizard() {
    setStage('workflow')
    setWorkflow('basic')
    setMasterCvId(null)
    setMethod('paste')
    setPasteValue('')
    setUrlValue('')
    setExtraction(null)
    setReviewText('')
    setCheckJobId(null)
    setCheckAnswer(null)
    setDuplicateMatch(null)
    setIdentityJobId(null)
    setIdentityError(null)
    setCompany('')
    setRoleTitle('')
    setLane('')
    setLocation('')
    setPortalName('')
    setPortalUrl('')
    setResult(null)
    setBusy(false)
    setError(null)
  }

  // Reset to a clean wizard each time the overlay opens, so a cancelled attempt never leaks
  // into the next one.
  useEffect(() => {
    if (open) resetWizard()
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

  useEffect(() => {
    let cancelled = false
    fetchLanes()
      .then((lanes) => {
        if (!cancelled) setLaneOptions(lanes)
      })
      .catch(() => {
        if (!cancelled) setLaneOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Once the check job finishes, read its answer back and parse it (informational only).
  useEffect(() => {
    if (!checkJob || checkJob.status !== 'done') return
    let cancelled = false
    fetchPromptExchange(checkJob.id, 0)
      .then((exchange) => {
        if (!cancelled && exchange.result_text) setCheckAnswer(parseCheckAnswer(exchange.result_text))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
    // checkJob.status is the real trigger - see the identity effect's own comment below for why
    // the object itself isn't a safe dependency (useClaudeJobs() polling gives a new reference
    // every tick, which would re-fetch this repeatedly for no reason once already done).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [checkJob?.status])

  // Once the identity job finishes, read its parsed answer back and pre-fill the confirm form.
  // A rejected answer (no identifiable company/role) falls back to manual entry (D-145) - so
  // does a runner-level failure (a rate limit, a crash), which never reaches the parsed-answer
  // endpoint at all.
  useEffect(() => {
    if (!identityJob || identityJobId === null) return
    if (identityJob.status === 'failed') {
      setIdentityError(
        identityJob.error ?? 'Could not read the listing. Type the details in by hand below.',
      )
      return
    }
    if (identityJob.status !== 'done') return
    let cancelled = false
    fetchIntakeIdentityResult(identityJobId)
      .then((answer: JobIdentityAnswer) => {
        if (cancelled) return
        setCompany(answer.company)
        setRoleTitle(answer.role_title)
        setLane(answer.lane ?? '')
        setLocation(answer.location ?? '')
        // D-150: a URL-sourced listing already got its Portal/Portal URL set, for certain, as
        // soon as this stage opened (below) - the model's own guess for these two fields is
        // only used when there was no URL to derive them from.
        if (extraction?.method !== 'url') {
          setPortalName(answer.portal_name ?? '')
          setPortalUrl(answer.portal_url ?? '')
        }
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setIdentityError(
          failure instanceof ApiError
            ? failure.message
            : 'Could not read the suggested details. Type them in by hand below.',
        )
      })
    return () => {
      cancelled = true
    }
    // useClaudeJobs() polls every few seconds and hands back a brand new `jobs` array (and so a
    // new `identityJob` object) each time, even once the job is already "done" - depending on
    // the object itself re-ran this effect, and so re-fetched and overwrote company/role/lane/
    // location/portal on every poll tick while this stage was open, undoing whatever the user
    // had just typed. identityJob.status is the real trigger; its own string value only changes
    // when the job's actual status changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identityJob?.status, identityJobId, extraction])

  function startReview(extracted: ListingExtraction) {
    setExtraction(extracted)
    if (extracted.status !== 'ok') {
      setError(extracted.message ?? 'That did not produce any readable text.')
      return
    }
    setError(null)
    setReviewText(extracted.text)
    setStage('review')
    intakeCheckListingText(extracted.text)
      .then((job) => setCheckJobId(job.id))
      .catch(() => undefined) // informational only
    intakeDuplicateCheck(extracted.text, extracted.method === 'url' ? extracted.source : null)
      .then(setDuplicateMatch)
      .catch(() => undefined) // informational only
  }

  async function runExtraction(run: () => Promise<ListingExtraction>) {
    setBusy(true)
    setError(null)
    try {
      startReview(await run())
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'That could not be read.')
    } finally {
      setBusy(false)
    }
  }

  async function chooseFile(chosen: FileList | null) {
    const file = chosen?.[0]
    if (!file) return
    await runExtraction(() => intakeExtractFromUpload(file))
    if (fileInput.current) fileInput.current.value = ''
  }

  function startIdentity() {
    setStage('identity')
    setIdentityError(null)
    // D-150: known for certain as soon as the listing came from a URL - set it now rather than
    // waiting on (or trusting) the model's own guess.
    if (extraction?.method === 'url' && extraction.source) {
      setPortalUrl(extraction.source)
      setPortalName(portalNameFromUrl(extraction.source))
    }
    intakeExtractIdentity(reviewText)
      .then((job) => setIdentityJobId(job.id))
      .catch((failure: unknown) => {
        setIdentityError(
          failure instanceof ApiError ? failure.message : 'Could not start reading the listing.',
        )
      })
  }

  async function create() {
    if (!extraction || !company.trim() || !roleTitle.trim()) return
    setBusy(true)
    setError(null)
    try {
      const created = await createJobApplication({
        company: company.trim(),
        role_title: roleTitle.trim(),
        lane: lane.trim() || null,
        location: location.trim() || null,
        portal_name: portalName.trim() || null,
        portal_url: portalUrl.trim() || null,
        listing_method: extraction.method,
        listing_text: reviewText,
        listing_source_url: extraction.method === 'url' ? extraction.source : null,
        workflow,
        master_cv_profile_file_id: masterCvId,
      })
      setResult(created)
      setStage('created')
      onCreated(created.application_id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'This could not be created.')
    } finally {
      setBusy(false)
    }
  }

  const canUseWorkflow = workflow === 'basic' || masterCvId !== null
  const masterCvItems: Record<string, string> = { [NONE]: 'Not selected' }
  for (const file of masterCvOptions ?? []) masterCvItems[String(file.id)] = file.original_name
  // The approved lane catalog (D-215) - a value the identity step suggested that isn't (or is no
  // longer) in the catalog is kept as its own item, so a suggestion is never silently dropped.
  const laneItems: Record<string, string> = { [NONE]: 'Not selected' }
  for (const option of laneOptions ?? []) laneItems[option.name] = option.name
  if (lane.trim() && !(lane in laneItems)) laneItems[lane] = lane

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Add Job</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          {stage === 'workflow' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-muted-foreground">
                Choose how much to run automatically once the listing is added.
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
              {workflow !== 'basic' && (
                <div className="flex flex-col gap-2">
                  <Label>Master CV</Label>
                  <Select
                    items={masterCvItems}
                    value={masterCvId === null ? NONE : String(masterCvId)}
                    onValueChange={(next) => setMasterCvId(next === NONE || !next ? null : Number(next))}
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
                      Positioning analysis needs a Master CV selected.
                    </p>
                  )}
                </div>
              )}
              <Button disabled={!canUseWorkflow} className="self-start" onClick={() => setStage('source')}>
                Next
              </Button>
            </div>
          )}

          {stage === 'source' && (
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                {(['paste', 'url', 'upload'] as const).map((candidate) => (
                  <Button
                    key={candidate}
                    type="button"
                    size="sm"
                    variant={method === candidate ? 'default' : 'outline'}
                    onClick={() => {
                      setMethod(candidate)
                      setError(null)
                    }}
                  >
                    {candidate === 'paste' ? 'Paste text' : candidate === 'url' ? 'URL' : 'Upload a file'}
                  </Button>
                ))}
              </div>
              {method === 'paste' && (
                <div className="flex flex-col gap-2">
                  <Textarea
                    rows={10}
                    placeholder="Paste the job listing text here..."
                    value={pasteValue}
                    onChange={(event) => setPasteValue(event.target.value)}
                  />
                  <Button
                    disabled={busy || !pasteValue.trim()}
                    onClick={() => void runExtraction(() => intakeExtractFromPaste(pasteValue))}
                    className="self-start"
                  >
                    {busy ? 'Reading...' : 'Use this text'}
                  </Button>
                </div>
              )}
              {method === 'url' && (
                <div className="flex flex-col gap-2">
                  <Input
                    type="url"
                    placeholder="https://..."
                    value={urlValue}
                    onChange={(event) => setUrlValue(event.target.value)}
                  />
                  <Button
                    disabled={busy || !urlValue.trim()}
                    onClick={() => void runExtraction(() => intakeExtractFromUrl(urlValue))}
                    className="self-start"
                  >
                    {busy ? 'Fetching...' : 'Fetch'}
                  </Button>
                </div>
              )}
              {method === 'upload' && (
                <div className="flex flex-col gap-2">
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".pdf,.docx,.txt,.md,.html,.htm"
                    className="sr-only"
                    aria-label="Choose a listing file"
                    onChange={(event) => void chooseFile(event.target.files)}
                  />
                  <Button disabled={busy} onClick={() => fileInput.current?.click()} className="self-start">
                    {busy ? 'Reading...' : 'Choose a file'}
                  </Button>
                </div>
              )}
              {error && (
                <div className="flex flex-col gap-1">
                  <p role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                  {method !== 'paste' && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="self-start"
                      onClick={() => {
                        setMethod('paste')
                        setError(null)
                      }}
                    >
                      Try pasting the text instead
                    </Button>
                  )}
                </div>
              )}
              <Button variant="outline" size="sm" className="self-start" onClick={() => setStage('workflow')}>
                Back
              </Button>
            </div>
          )}

          {stage === 'review' && (
            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <p className="text-xs text-muted-foreground">
                Review the extracted text below - edit anything that looks wrong before
                continuing.
              </p>
              <Textarea
                rows={14}
                className="flex-1"
                value={reviewText}
                onChange={(event) => setReviewText(event.target.value)}
              />
              {!checkAnswer && checkJobId !== null && (
                <p className="text-xs text-muted-foreground">Checking this looks like a job posting...</p>
              )}
              {checkAnswer && !checkAnswer.looksLikePosting && (
                <p role="alert" className="text-xs text-amber-600 dark:text-amber-400">
                  This might not be a job posting{checkAnswer.reason ? `: ${checkAnswer.reason}` : '.'} You
                  can still continue, or go back and try a different source.
                </p>
              )}
              {duplicateMatch && (
                <p role="alert" className="text-xs text-amber-600 dark:text-amber-400">
                  This looks like a repeat of {duplicateMatch.company} - {duplicateMatch.role_title}
                  {duplicateMatch.matched_by === 'url' ? ' (same source URL)' : ' (same text)'}.{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => onOpenApplication(duplicateMatch.application_id)}
                  >
                    Open it instead
                  </button>
                  , or continue anyway.
                </p>
              )}
              {error && (
                <p role="alert" className="text-xs text-destructive">
                  {error}
                </p>
              )}
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setStage('source')}>
                  Back
                </Button>
                <Button disabled={!reviewText.trim()} onClick={startIdentity}>
                  Continue
                </Button>
              </div>
            </div>
          )}

          {stage === 'identity' && (
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
              {identityJobId !== null && identityJob?.status !== 'done' && !identityError && (
                <p className="text-xs text-muted-foreground">Reading company, role and lane...</p>
              )}
              {identityError && (
                <p role="alert" className="text-xs text-amber-600 dark:text-amber-400">
                  {identityError}
                </p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-company">Company</Label>
                  <Input
                    id="add-job-company"
                    value={company}
                    onChange={(event) => setCompany(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-role">Role title</Label>
                  <Input
                    id="add-job-role"
                    value={roleTitle}
                    onChange={(event) => setRoleTitle(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-lane">Lane</Label>
                  <Select
                    items={laneItems}
                    value={lane.trim() === '' ? NONE : lane}
                    onValueChange={(next) => setLane(next === NONE || !next ? '' : next)}
                    disabled={laneOptions === null}
                  >
                    <SelectTrigger id="add-job-lane" className="w-full">
                      <SelectValue placeholder="Not selected" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>Not selected</SelectItem>
                      {Object.keys(laneItems)
                        .filter((key) => key !== NONE)
                        .map((name) => (
                          <SelectItem key={name} value={name}>
                            {name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-location">Location</Label>
                  <Input
                    id="add-job-location"
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-portal-name">Portal</Label>
                  <Input
                    id="add-job-portal-name"
                    value={portalName}
                    onChange={(event) => setPortalName(event.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="add-job-portal-url">Portal URL</Label>
                  <Input
                    id="add-job-portal-url"
                    value={portalUrl}
                    onChange={(event) => setPortalUrl(event.target.value)}
                  />
                </div>
              </div>
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setStage('review')}>
                  Back
                </Button>
                <Button disabled={busy || !company.trim() || !roleTitle.trim()} onClick={() => void create()}>
                  {busy ? 'Creating...' : 'Create'}
                </Button>
              </div>
            </div>
          )}

          {stage === 'created' && result && (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted-foreground">
                {stagedJobs.length} step{stagedJobs.length === 1 ? '' : 's'} staged. They run once
                you click "Trigger workflows" in the header.
              </p>
              <ul className="flex flex-col gap-1">
                {result.claude_job_ids.map((id) => {
                  const job = stagedJobs.find((candidate) => candidate?.id === id) ?? null
                  return (
                    <li key={id} className="text-sm text-muted-foreground">
                      {job?.label ?? `Job ${id}`}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </div>
        <DialogFooter>
          {stage === 'created' && result ? (
            <>
              <Button
                variant="outline"
                onClick={() => {
                  resetWizard()
                }}
              >
                Add another job
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  onOpenApplication(result.application_id)
                  onOpenChange(false)
                }}
              >
                View job
              </Button>
              <Button onClick={() => onOpenChange(false)}>Close</Button>
            </>
          ) : (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
