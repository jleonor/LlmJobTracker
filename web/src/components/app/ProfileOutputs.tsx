import { useEffect, useState } from 'react'

import { AnalysisTerminal } from '@/components/app/AnalysisTerminal'
import { Button } from '@/components/ui/button'
import { ApiError, fetchProfileOutputs, saveProfileOutput, startProfileAnalysis } from '@/lib/api'
import type { ProfileOutput } from '@/lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; outputs: ProfileOutput[] }

const TITLES: Record<ProfileOutput['kind'], string> = {
  full_cv_history: 'Career history',
  questionnaire_analysis: 'Questionnaire analysis',
  strategy: 'Positioning strategy',
}

function latest(outputs: ProfileOutput[], kind: ProfileOutput['kind']): ProfileOutput | undefined {
  return outputs.find((output) => output.kind === kind)
}

// The analysis outputs on the Profile page (D-58). Edits are saved as new versions (D-66, D-85, O-12).
// refreshKey changes when an analysis finishes, so the outputs are read again without a click.
export function ProfileOutputs({ onChanged, refreshKey }: { onChanged: () => void; refreshKey: number | null }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  function load() {
    onChanged()
    fetchProfileOutputs()
      .then((outputs) => setState({ kind: 'ready', outputs }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load the outputs.'
        setState({ kind: 'error', message })
      })
  }

  useEffect(() => {
    fetchProfileOutputs()
      .then((outputs) => setState({ kind: 'ready', outputs }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load the outputs.'
        setState({ kind: 'error', message })
      })
  }, [refreshKey])

  async function handleStart() {
    setStarting(true)
    setNotice(null)
    try {
      const job = await startProfileAnalysis()
      setNotice(`Started "${job.label}". It runs in the background; refresh to see the outputs.`)
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : 'The analysis did not start.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <section aria-labelledby="outputs-heading" className="flex flex-col gap-4 rounded border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="outputs-heading" className="text-sm font-semibold">
            Profile analysis
          </h2>
          <p className="text-xs text-muted-foreground">
            Run the analysis to make what is missing. Anything you uploaded is used as-is, and
            anything you edit is saved as a new version.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load}>
            Refresh
          </Button>
          <Button disabled={starting} onClick={() => void handleStart()}>
            {starting ? 'Starting...' : 'Run profile analysis'}
          </Button>
        </div>
      </div>

      {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

      <AnalysisTerminal />

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading the outputs...</p>}
      {state.kind === 'error' && (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      )}

      {state.kind === 'ready' && state.outputs.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No outputs yet. Upload your files, then run the analysis.
        </p>
      )}

      {state.kind === 'ready' && (
        <>
          {/* The career history has its own viewer: the file in "Your career history" above
              (D-84), openable the same way as an upload. No separate card here. */}
          <DocumentCard output={latest(state.outputs, 'questionnaire_analysis')} onSaved={load} />
          <DocumentCard output={latest(state.outputs, 'strategy')} onSaved={load} />
        </>
      )}
    </section>
  )
}

// One document: the career history, the questionnaire analysis or the strategy. Read as Markdown
// prose, edited as plain text (D-85, D-86): there is nothing left to check field by field.
function DocumentCard({ output, onSaved }: { output: ProfileOutput | undefined; onSaved: () => void }) {
  if (!output) return null
  return <DocumentForm key={output.id} output={output} onSaved={onSaved} />
}

function DocumentForm({ output, onSaved }: { output: ProfileOutput; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(output.document)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await saveProfileOutput(output.kind, text)
      setEditing(false)
      onSaved()
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : 'The change was not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-background p-3">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold">{TITLES[output.kind]}</h3>
        <p className="font-mono text-xs text-muted-foreground">
          version {output.version} · {output.created_at.slice(0, 10)}
          {output.claude_job_id === null ? ' · edited by you' : ' · from Claude'}
        </p>
      </div>

      {editing ? (
        <textarea
          aria-label={`Edit ${TITLES[output.kind]}`}
          className="min-h-48 rounded border border-border bg-card p-2 font-mono text-sm text-foreground"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      ) : (
        <pre className="whitespace-pre-wrap font-sans text-sm text-foreground">{output.document}</pre>
      )}

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        {editing ? (
          <>
            <Button disabled={busy} onClick={() => void save()}>
              Save as new version
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setText(output.document)
                setEditing(false)
                setError(null)
              }}
            >
              Cancel
            </Button>
          </>
        ) : (
          <Button variant="outline" onClick={() => setEditing(true)}>
            Edit
          </Button>
        )}
      </div>
    </div>
  )
}
