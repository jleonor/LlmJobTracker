import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ProfileOutputs } from '@/components/app/ProfileOutputs'
import {
  ApiError,
  deleteProfileFile,
  fetchProfileFiles,
  openProfileFile,
  uploadProfileFile,
} from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { ProfileFile, ProfileFileKind } from '@/lib/types'

// The upload sections, in the order of the Profile page (D-58). Labels are the user's words.
const SECTIONS: { kind: ProfileFileKind; title: string; hint: string }[] = [
  { kind: 'master_cv', title: 'Master CVs', hint: 'English and French. Layout and wording templates.' },
  { kind: 'older_cv', title: 'Older CVs', hint: 'Evidence for the career history. Older ones may be out of date.' },
  { kind: 'older_letter', title: 'Older cover letters', hint: 'Evidence for the career history.' },
  { kind: 'questionnaire', title: 'Questionnaire', hint: 'Your answers, used for the analysis.' },
  { kind: 'writing_rules', title: 'Your writing rules', hint: 'Overrides the default rules in Agent/rules/.' },
  {
    kind: 'cover_letter_template',
    title: 'Cover letter template',
    hint: 'Your template for cover letters. Used when the letters are written. The analysis does not need it.',
  },
  {
    kind: 'own_full_cv_history',
    title: 'Your career history',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
  },
  {
    kind: 'own_questionnaire_analysis',
    title: 'Your questionnaire analysis',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
  },
  {
    kind: 'own_strategy',
    title: 'Your positioning strategy',
    hint: 'Optional. If you have one, upload it. The analysis uses yours instead of writing a new one.',
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

export function ProfilePage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  // When the latest analysis finishes, the outputs are read again.
  const queue = useClaudeJobs()
  const analysis = [...queue.jobs].reverse().find((job) => job.kind === 'profile_analysis')
  const finishedAnalysis =
    analysis && (analysis.status === 'done' || analysis.status === 'failed') ? analysis.id : null

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

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading your files...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' && (
        <>
          <h2 className="text-sm font-semibold">Your files</h2>
          {REQUIRED_SECTIONS.map((section) => (
            <UploadSection
              key={section.kind}
              kind={section.kind}
              title={section.title}
              hint={section.hint}
              files={state.files.filter((file) => file.kind === section.kind)}
              onUploaded={reload}
            />
          ))}

          <div className="flex flex-col gap-1 border-t border-border pt-4">
            <h2 className="text-sm font-semibold">LLM Generated Profile</h2>
            <p className="text-xs text-muted-foreground">
              Leave these out and the analysis makes them. Upload one to use yours instead.
            </p>
          </div>
          {OPTIONAL_SECTIONS.map((section) => (
            <UploadSection
              key={section.kind}
              kind={section.kind}
              title={section.title}
              hint={section.hint}
              files={state.files.filter((file) => file.kind === section.kind)}
              onUploaded={reload}
            />
          ))}
        </>
      )}

      <ProfileOutputs onChanged={reload} refreshKey={finishedAnalysis} />
    </section>
  )
}

type SectionProps = {
  kind: ProfileFileKind
  title: string
  hint: string
  files: ProfileFile[]
  onUploaded: () => void
}

function UploadSection({ kind, title, hint, files, onUploaded }: SectionProps) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [collapsed, setCollapsed] = useState(true)

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

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id={headingId} className="text-sm font-semibold">
            {title}
          </h2>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
        <div>
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
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            {busy ? 'Uploading...' : 'Upload'}
          </Button>
        </div>
      </div>

      {files.length === 0 ? (
        <p className="text-xs text-muted-foreground">No files yet.</p>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setCollapsed((current) => !current)}
            className="self-start text-left text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {collapsed ? 'Show' : 'Hide'} {files.length} {files.length === 1 ? 'file' : 'files'}
          </button>
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
    </section>
  )
}

// One uploaded file: its size and date, Open (the default app for it), and × to remove it (D-82).
function FileRow({ file, onChanged }: { file: ProfileFile; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
    <li className="flex flex-col gap-1 px-3 py-2 text-sm">
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
          <Button variant="outline" size="sm" disabled={busy} onClick={() => void open()}>
            Open
          </Button>
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
    </li>
  )
}
