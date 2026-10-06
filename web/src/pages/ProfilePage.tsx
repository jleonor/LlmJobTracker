import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { FactSheetReview } from '@/components/app/FactSheetReview'
import { ProfileOutputs } from '@/components/app/ProfileOutputs'
import { ApiError, fetchProfileFiles, uploadProfileFile } from '@/lib/api'
import type { ProfileFile, ProfileFileKind } from '@/lib/types'

// The upload sections, in the order of the Profile page (D-58). Labels are the user's words.
const SECTIONS: { kind: ProfileFileKind; title: string; hint: string }[] = [
  { kind: 'master_cv', title: 'Master CVs', hint: 'English and French. Layout and wording templates.' },
  { kind: 'older_cv', title: 'Older CVs', hint: 'Evidence for the Fact Sheet. Older ones may be out of date.' },
  { kind: 'older_letter', title: 'Older cover letters', hint: 'Evidence for the Fact Sheet.' },
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
    hint: 'Optional. If you have one, upload it. The analysis converts yours instead of writing a new one.',
  },
  {
    kind: 'own_questionnaire_analysis',
    title: 'Your questionnaire analysis',
    hint: 'Optional. If you have one, upload it. The analysis converts yours instead of writing a new one.',
  },
  {
    kind: 'own_fact_sheet',
    title: 'Your Fact Sheet',
    hint: 'Optional. Your facts with their sources. The analysis converts yours, and you still verify each fact below.',
  },
  {
    kind: 'own_strategy',
    title: 'Your positioning strategy',
    hint: 'Optional. If you have one, upload it. The analysis converts yours instead of writing a new one.',
  },
]

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
  // Bumped when the outputs are read again, so the Fact Sheet review reloads with them.
  const [revision, setRevision] = useState(0)

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

      <ProfileOutputs onChanged={() => setRevision((current) => current + 1)} />

      <FactSheetReview key={revision} />

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading your files...</p>}

      {state.kind === 'error' && (
        <div role="alert" className="rounded border border-destructive/50 p-4 text-sm text-destructive">
          {state.message}
        </div>
      )}

      {state.kind === 'ready' &&
        SECTIONS.map((section) => (
          <UploadSection
            key={section.kind}
            kind={section.kind}
            title={section.title}
            hint={section.hint}
            files={state.files.filter((file) => file.kind === section.kind)}
            onUploaded={reload}
          />
        ))}
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
        <ul className="flex flex-col divide-y divide-border rounded border border-border">
          {files.map((file) => (
            <li key={file.id} className="flex items-center justify-between gap-4 px-3 py-2 text-sm">
              <span className="truncate">{file.original_name}</span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                {formatSize(file.size_bytes)} · {file.uploaded_at.slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
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
