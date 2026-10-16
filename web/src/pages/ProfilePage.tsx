import { Download, FolderOpen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { FilePreview } from '@/components/app/FilePreview'
import { ProfileOutputs } from '@/components/app/ProfileOutputs'
import { ReviseOverlay } from '@/components/app/ReviseOverlay'
import { RunTrace } from '@/components/app/RunTrace'
import {
  ApiError,
  createLane,
  deleteLane,
  deleteProfileFile,
  downloadProfileFile,
  fetchLanes,
  fetchProfileFiles,
  openProfileFile,
  revealProfileFile,
  saveSettings,
  syncLanesFromStrategy,
  updateLane,
  uploadProfileFile,
} from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { Lane, ProfileFile, ProfileFileKind } from '@/lib/types'

// The upload sections, in the order of the Profile page (D-58). Labels are the user's words.
// collapsible is for sections that can hold many files (D-91); the single-file kinds (D-88,
// D-92, D-84) never need a Show/Hide toggle for the one file they can ever have.
const SECTIONS: { kind: ProfileFileKind; title: string; hint: string; collapsible: boolean }[] = [
  {
    kind: 'master_cv',
    title: 'Master CVs',
    hint: 'English and French. Layout and wording templates.',
    collapsible: true,
  },
  {
    kind: 'older_cv',
    title: 'Older CVs',
    hint: 'Evidence for the career history. Older ones may be out of date.',
    collapsible: true,
  },
  {
    kind: 'older_letter',
    title: 'Older cover letters',
    hint: 'Evidence for the career history.',
    collapsible: true,
  },
  {
    kind: 'questionnaire',
    title: 'Questionnaire',
    hint: 'Your answers, used for the analysis.',
    collapsible: false,
  },
  {
    kind: 'writing_rules',
    title: 'Your writing rules',
    hint: 'Overrides the default rules in Agent/rules/.',
    collapsible: false,
  },
  {
    kind: 'cover_letter_template',
    title: 'Cover letter template',
    hint: 'Your template for cover letters. Used when the letters are written. The analysis does not need it.',
    collapsible: false,
  },
  {
    kind: 'own_full_cv_history',
    title: 'Your career history',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
    collapsible: false,
  },
  {
    kind: 'own_questionnaire_analysis',
    title: 'Your questionnaire analysis',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
    collapsible: false,
  },
  {
    kind: 'own_strategy',
    title: 'Your positioning strategy',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
    collapsible: false,
  },
]

// Your files Claude cannot make, and the optional versions Claude can make (D-68, D-70).
const REQUIRED_SECTIONS = SECTIONS.filter((section) => !section.kind.startsWith('own_'))
const OPTIONAL_SECTIONS = SECTIONS.filter((section) => section.kind.startsWith('own_'))

const ACCEPT = '.pdf,.docx,.txt,.md'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; files: ProfileFile[] }

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function ProfilePage({
  userName,
  onNameChanged,
}: {
  userName: string
  onNameChanged: () => void
}) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  // When the latest analysis finishes, the outputs are read again.
  const queue = useClaudeJobs()
  const analysis = [...queue.jobs].reverse().find((job) => job.kind === 'profile_analysis')
  const finishedAnalysis =
    analysis && (analysis.status === 'done' || analysis.status === 'failed') ? analysis.id : null
  // Same pattern, for the Lanes section's Sync from strategy action (D-214).
  const laneSync = [...queue.jobs].reverse().find((job) => job.kind === 'extract_lanes')
  const finishedLaneSync =
    laneSync && (laneSync.status === 'done' || laneSync.status === 'failed') ? laneSync.id : null

  useEffect(() => {
    let cancelled = false
    fetchProfileFiles()
      .then((files) => {
        if (!cancelled) setState({ kind: 'ready', files })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'Could not load your files.'
        setState({ kind: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

  function reload() {
    fetchProfileFiles()
      .then((files) => setState({ kind: 'ready', files }))
      .catch(() => undefined)
  }

  return (
    <section aria-labelledby="profile-heading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 id="profile-heading" className="text-xl font-semibold tracking-tight">
          Profile
        </h1>
        <p className="text-sm text-muted-foreground">
          Upload your files here. The app keeps its own copy, and your originals are not changed.
        </p>
      </div>

      <NameSection userName={userName} onSaved={onNameChanged} />

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading your files...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' && (
        <>
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold">Your files</h2>
          </div>
          <div className="flex flex-col divide-y divide-border rounded border border-border bg-card">
            {REQUIRED_SECTIONS.map((section) => (
              <UploadSection
                key={section.kind}
                kind={section.kind}
                title={section.title}
                hint={section.hint}
                collapsible={section.collapsible}
                files={state.files.filter((file) => file.kind === section.kind)}
                onUploaded={reload}
              />
            ))}
          </div>

          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold">LLM Files</h2>
            <p className="text-xs text-muted-foreground">
              Leave these out and the analysis makes them. Upload one to use yours instead.
            </p>
          </div>
          <div className="flex flex-col divide-y divide-border rounded border border-border bg-card">
            <ProfileOutputs onChanged={reload} refreshKey={finishedAnalysis} analysis={analysis ?? null} />
            {OPTIONAL_SECTIONS.map((section) => (
              <UploadSection
                key={section.kind}
                kind={section.kind}
                title={section.title}
                hint={section.hint}
                collapsible={section.collapsible}
                files={state.files.filter((file) => file.kind === section.kind)}
                onUploaded={reload}
              />
            ))}
          </div>

          <LanesSection refreshKey={finishedLaneSync} />
        </>
      )}
    </section>
  )
}

// Shown in the sidebar as "{name}'s Job Tracker" (D-94). Saving reloads the shared settings
// state (App.tsx), so the sidebar picks up the change right away.
function NameSection({ userName, onSaved }: { userName: string; onSaved: () => void }) {
  const [name, setName] = useState(userName)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const saved = await saveSettings(name)
      setName(saved.user_name)
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The name was not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="name-heading" className="flex flex-col gap-2 rounded border border-border bg-card p-4">
      <h2 id="name-heading" className="text-sm font-semibold">
        Name
      </h2>
      <div className="flex items-center gap-2">
        <input
          aria-label="Your name"
          className="w-64 rounded border border-border bg-background px-2 py-1 text-sm text-foreground"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Button disabled={busy || name === userName} onClick={() => void save()}>
          Save
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Shown in the sidebar, as "{name || 'YourName'}'s Job Tracker".
      </p>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </section>
  )
}

type SectionProps = {
  kind: ProfileFileKind
  title: string
  hint: string
  collapsible: boolean
  files: ProfileFile[]
  onUploaded: () => void
}

// own_* upload kind -> the document kind it mirrors (profile_pipeline.py's OWN_KINDS, reversed).
const OUTPUT_KIND_FOR_OWN: Partial<Record<ProfileFileKind, string>> = {
  own_full_cv_history: 'full_cv_history',
  own_questionnaire_analysis: 'questionnaire_analysis',
  own_strategy: 'strategy',
}

function UploadSection({ kind, title, hint, collapsible, files, onUploaded }: SectionProps) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [collapsed, setCollapsed] = useState(collapsible)
  const [reviseOpen, setReviseOpen] = useState(false)
  const outputKind = OUTPUT_KIND_FOR_OWN[kind]

  async function handleChosen(chosen: FileList | null) {
    if (!chosen || chosen.length === 0) return
    setBusy(true)
    setErrors([])
    const failures: string[] = []
    for (const file of Array.from(chosen)) {
      try {
        await uploadProfileFile(kind, file)
      } catch (error) {
        const message = error instanceof ApiError ? error.message : 'The upload failed.'
        failures.push(`${file.name}: ${message}`)
      }
    }
    setErrors(failures)
    setBusy(false)
    if (input.current) input.current.value = ''
    onUploaded()
  }

  const headingId = `${kind}-heading`
  // A multi-file kind (collapsible, D-91) can always take another upload; a single-file kind
  // (D-88, D-92, D-84) only needs the button until it has its one file — uploading a second
  // would just replace it, so the button would have nothing left to do.
  const showUpload = collapsible || files.length === 0
  // Revise (LLM) only makes sense once there is something to revise, generated or uploaded
  // alike (D-102) — not applicable to the plain uploads above the LLM Generated Profile kinds.
  const showRevise = outputKind !== undefined && files.length > 0

  return (
    <section
      aria-labelledby={headingId}
      className="group/section flex flex-col gap-3 p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id={headingId} className="text-sm font-semibold">
            {title}
          </h2>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
        <div className="flex items-center gap-2 opacity-0 transition-opacity focus-within:opacity-100 group-hover/section:opacity-100">
          {/* Revise (LLM) lets the user give extra input to redo this generated document; it only
              applies to the LLM Generated Profile kinds (own_*), not the plain uploads above
              (D-102). The Job Application page's matching buttons aren't wired yet (D-103). */}
          {showRevise && (
            <Button variant="outline" onClick={() => setReviseOpen(true)}>
              Revise (LLM)
            </Button>
          )}
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            id={`${kind}-input`}
            aria-label={`Choose files for ${title}`}
            onChange={(event) => void handleChosen(event.target.files)}
          />
          {showUpload && (
            <Button variant="outline" disabled={busy} onClick={() => input.current?.click()}>
              {busy ? 'Uploading...' : 'Upload'}
            </Button>
          )}
        </div>
      </div>

      {files.length === 0 ? (
        <p className="text-xs text-muted-foreground">No files yet.</p>
      ) : (
        <>
          {collapsible && (
            <button
              type="button"
              onClick={() => setCollapsed((current) => !current)}
              className="self-start text-left text-xs text-muted-foreground underline-offset-2 hover:underline"
            >
              {collapsed ? 'Show' : 'Hide'} {files.length} {files.length === 1 ? 'file' : 'files'}
            </button>
          )}
          {!collapsed && (
            <ul className="flex flex-col divide-y divide-border rounded border border-border">
              {files.map((file) => (
                <FileRow key={file.id} file={file} onChanged={onUploaded} />
              ))}
            </ul>
          )}
        </>
      )}

      {errors.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 text-sm text-destructive">
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      {outputKind && (
        <ReviseOverlay
          outputKind={outputKind}
          open={reviseOpen}
          onOpenChange={setReviseOpen}
          onChanged={onUploaded}
        />
      )}
    </section>
  )
}

// One uploaded file: its size and date, Open (the default app for it), and × to remove it (D-82).
function FileRow({ file, onChanged }: { file: ProfileFile; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  async function open() {
    setBusy(true)
    setError(null)
    try {
      await openProfileFile(file.id)
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
      await revealProfileFile(file.id)
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
      await downloadProfileFile(file.id, file.original_name)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be downloaded.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    const ok = window.confirm(`Remove "${file.original_name}"? Its copy in the app is deleted.`)
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      await deleteProfileFile(file.id)
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The file could not be removed.')
      setBusy(false)
    }
  }

  return (
    <li className="group/file flex flex-col gap-1 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-4">
        <span className="truncate">
          {file.original_name}
          {file.generated && (
            <span className="ml-2 text-xs text-muted-foreground">(generated)</span>
          )}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-xs text-muted-foreground">
            {formatSize(file.size_bytes)} · {file.uploaded_at.slice(0, 10)}
          </span>
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
              aria-label={`Download ${file.original_name}`}
              onClick={() => void download()}
            >
              <Download className="size-3.5" aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              disabled={busy}
              title="Show in folder"
              aria-label={`Show ${file.original_name} in folder`}
              onClick={() => void reveal()}
            >
              <FolderOpen className="size-3.5" aria-hidden="true" />
            </Button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={`Remove ${file.original_name}`}
            onClick={() => void remove()}
          >
            ×
          </Button>
        </div>
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      <FilePreview
        source={{ table: 'profile_file', id: file.id }}
        name={file.original_name}
        open={previewOpen}
        onOpenChange={setPreviewOpen}
      />
    </li>
  )
}

// The approved lane catalog (D-182, D-214): edited inline here, and (re)populated in bulk from
// the positioning strategy document by Sync from strategy. refreshKey is the latest extract_lanes
// Claude Job's id once it finishes (ProfilePage's own queue poll), the same pattern ProfileOutputs
// already uses for profile_analysis.
function LanesSection({ refreshKey }: { refreshKey: number | null }) {
  const [state, setState] = useState<'loading' | 'error' | 'ready'>('loading')
  const [lanes, setLanes] = useState<Lane[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Lane | 'new' | null>(null)
  const [syncOpen, setSyncOpen] = useState(false)
  const [syncRunning, setSyncRunning] = useState(false)
  const [syncJobId, setSyncJobId] = useState<number | null>(null)
  const [syncBusy, setSyncBusy] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)

  // Self-contained poll for the sync job's own trace (D-220) - the same pattern
  // GenerateSectionOverlay already uses, independent of ProfilePage's own poll for refreshKey.
  const { jobs } = useClaudeJobs()
  const syncJob = syncJobId === null ? null : (jobs.find((job) => job.id === syncJobId) ?? null)

  function reload() {
    fetchLanes()
      .then((rows) => {
        setLanes(rows)
        setState('ready')
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not load lanes.')
        setState('error')
      })
  }

  useEffect(reload, [])

  // When a Sync from strategy job finishes, the list is read again without a click.
  useEffect(() => {
    if (refreshKey !== null) reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  // Reset the dialog's own run state each time it opens, so a previous run never leaks into
  // the next one (the same pattern GenerateSectionOverlay uses for `open`).
  useEffect(() => {
    if (!syncOpen) return
    setSyncRunning(false)
    setSyncJobId(null)
    setSyncBusy(false)
    setSyncError(null)
  }, [syncOpen])

  async function remove(lane: Lane) {
    if (!window.confirm(`Remove the "${lane.name}" lane?`)) return
    try {
      await deleteLane(lane.id)
      reload()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not remove the lane.')
    }
  }

  async function startSync() {
    setSyncBusy(true)
    setSyncError(null)
    try {
      const job = await syncLanesFromStrategy()
      setSyncJobId(job.id)
      setSyncRunning(true)
    } catch (failure) {
      setSyncError(failure instanceof ApiError ? failure.message : 'The sync did not start.')
    } finally {
      setSyncBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="lanes-heading"
      className="flex flex-col gap-3 rounded border border-border bg-card p-4"
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="lanes-heading" className="text-sm font-semibold">
            Lanes
          </h2>
          <p className="text-xs text-muted-foreground">
            The approved list Add Job and Job details pick a lane from.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={() => setEditing('new')}>
            Add lane
          </Button>
          <Button variant="outline" onClick={() => setSyncOpen(true)}>
            Sync from strategy
          </Button>
        </div>
      </div>

      {state === 'loading' && <p className="text-xs text-muted-foreground">Loading lanes...</p>}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}

      {state === 'ready' && lanes.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No lanes yet. Add one by hand, or Sync from strategy once a positioning strategy exists.
        </p>
      )}

      {state === 'ready' && lanes.length > 0 && (
        <ul className="flex flex-col divide-y divide-border">
          {lanes.map((lane) => (
            <li
              key={lane.id}
              className="group/lane flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0"
            >
              <div className="flex flex-col gap-1">
                <span className="text-sm font-medium">{lane.name}</span>
                {lane.description && (
                  <p className="text-xs text-muted-foreground">{lane.description}</p>
                )}
                {lane.reasoning && (
                  <p className="text-xs italic text-muted-foreground">{lane.reasoning}</p>
                )}
              </div>
              <div className="flex items-center gap-2 opacity-0 transition-opacity focus-within:opacity-100 group-hover/lane:opacity-100">
                <Button variant="ghost" size="sm" onClick={() => setEditing(lane)}>
                  Edit
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void remove(lane)}>
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <LaneEditDialog
        lane={editing === 'new' ? null : editing}
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        onSaved={() => {
          setEditing(null)
          reload()
        }}
      />

      {/* Confirm-then-trace, the same shape as GenerateSectionOverlay's Generate/Revise dialogs
          and ProfileOutputs' own Run profile analysis (D-220) - not a plain confirm dialog. */}
      <Dialog open={syncOpen} onOpenChange={setSyncOpen}>
        <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>Sync lanes from strategy</DialogTitle>
          </DialogHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
            {!syncRunning && (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  This replaces every lane above with a fresh reading of your positioning
                  strategy document. Any manual edits to the current list will be lost.
                </p>
                {syncError && <p className="text-sm text-destructive">{syncError}</p>}
                <Button disabled={syncBusy} onClick={() => void startSync()} className="self-start">
                  {syncBusy ? 'Starting...' : 'Sync'}
                </Button>
              </div>
            )}
            {syncRunning && <RunTrace job={syncJob} />}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSyncOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function LaneEditDialog({
  lane,
  open,
  onOpenChange,
  onSaved,
}: {
  lane: Lane | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [reasoning, setReasoning] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset the form from the current lane each time the dialog opens (or opens fresh for a new
  // one), the same pattern JobDetailsEditDialog uses.
  useEffect(() => {
    if (!open) return
    setName(lane?.name ?? '')
    setDescription(lane?.description ?? '')
    setReasoning(lane?.reasoning ?? '')
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function save() {
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('A lane needs a name.')
      return
    }
    setBusy(true)
    setError(null)
    const fields = {
      name: trimmedName,
      description: description.trim() || null,
      reasoning: reasoning.trim() || null,
    }
    try {
      if (lane) {
        await updateLane(lane.id, fields)
      } else {
        await createLane(fields)
      }
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The save failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] w-full max-w-lg flex-col gap-3 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{lane ? 'Edit lane' : 'Add lane'}</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
          <div className="flex flex-col gap-1">
            <Label htmlFor="lane-name" className="text-xs">
              Name
            </Label>
            <Input id="lane-name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="lane-description" className="text-xs">
              Description
            </Label>
            <Textarea
              id="lane-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="lane-reasoning" className="text-xs">
              Reasoning
            </Label>
            <Textarea
              id="lane-reasoning"
              value={reasoning}
              onChange={(event) => setReasoning(event.target.value)}
            />
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
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
