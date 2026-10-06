import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { ApiError, fetchProfileOutputs, saveProfileOutput, startProfileAnalysis } from '@/lib/api'
import type {
  FullCvHistoryBody,
  Lane,
  ProfileOutput,
  QuestionnaireBody,
  StrategyBody,
} from '@/lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; outputs: ProfileOutput[] }

function latest(outputs: ProfileOutput[], kind: ProfileOutput['kind']): ProfileOutput | undefined {
  return outputs.find((output) => output.kind === kind)
}

// The analysis outputs on the Profile page (D-58). Edits are saved as new versions (D-66, O-12).
export function ProfileOutputs({ onChanged }: { onChanged: () => void }) {
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
  }, [])

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
            Run the analysis to make what is missing. Anything you uploaded is converted, and
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
          <QuestionnaireReport output={latest(state.outputs, 'questionnaire_analysis')} />
          <HistoryEditor output={latest(state.outputs, 'full_cv_history')} onSaved={load} />
          <StrategyEditor output={latest(state.outputs, 'strategy')} onSaved={load} />
        </>
      )}
    </section>
  )
}

function VersionLine({ output }: { output: ProfileOutput }) {
  return (
    <p className="font-mono text-xs text-muted-foreground">
      version {output.version} · {output.created_at.slice(0, 10)}
      {output.claude_job_id === null ? ' · edited by you' : ' · from Claude'}
    </p>
  )
}

function QuestionnaireReport({ output }: { output: ProfileOutput | undefined }) {
  if (!output) return null
  const body = output.body as QuestionnaireBody
  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-background p-3">
      <h3 className="text-sm font-semibold">Questionnaire report</h3>
      <VersionLine output={output} />
      <ul className="flex flex-col gap-1 text-sm">
        {body.themes.map((theme) => (
          <li key={theme.id}>
            <span className="font-mono text-xs text-muted-foreground">
              {theme.questionnaire_ref}:
            </span>{' '}
            {theme.text}
          </li>
        ))}
      </ul>
      {body.gaps.length > 0 && (
        <div className="text-sm">
          <p className="text-xs font-semibold text-muted-foreground">Left open by the questionnaire</p>
          <ul className="list-disc pl-5">
            {body.gaps.map((gap) => (
              <li key={gap.text}>{gap.text}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// Each editor is keyed by the output id in the parent, so a new version starts a fresh editor.
function HistoryEditor({ output, onSaved }: { output: ProfileOutput | undefined; onSaved: () => void }) {
  if (!output) return null
  return <HistoryForm key={output.id} output={output} onSaved={onSaved} />
}

function HistoryForm({ output, onSaved }: { output: ProfileOutput; onSaved: () => void }) {
  const [body, setBody] = useState(() => structuredClone(output.body) as FullCvHistoryBody)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function setText(index: number, text: string) {
    setBody((current) => {
      if (!current) return current
      const items = current.items.map((item, i) => (i === index ? { ...item, text } : item))
      return { ...current, items }
    })
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await saveProfileOutput('full_cv_history', body as unknown as Record<string, unknown>)
      onSaved()
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : 'The change was not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-background p-3">
      <h3 className="text-sm font-semibold">Career history</h3>
      <VersionLine output={output} />
      <ul className="flex flex-col gap-2">
        {body.items.map((item, index) => (
          <li key={item.id} className="flex flex-col gap-1">
            <div className="flex items-baseline gap-2 font-mono text-xs text-muted-foreground">
              <span>{item.id}</span>
              <span>{item.kind}</span>
              <span>{item.date}</span>
              <span>{item.source.location}</span>
              {item.conflicts.length > 0 && <span className="text-[#ffca85]">conflict</span>}
            </div>
            <input
              aria-label={`Text of ${item.id}`}
              className="rounded border border-border bg-card p-1 text-sm text-foreground"
              value={item.text}
              onChange={(event) => setText(index, event.target.value)}
            />
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div>
        <Button disabled={busy} onClick={() => void save()}>
          Save as new version
        </Button>
      </div>
    </div>
  )
}

function StrategyEditor({ output, onSaved }: { output: ProfileOutput | undefined; onSaved: () => void }) {
  if (!output) return null
  return <StrategyForm key={output.id} output={output} onSaved={onSaved} />
}

function StrategyForm({ output, onSaved }: { output: ProfileOutput; onSaved: () => void }) {
  const [body, setBody] = useState(() => structuredClone(output.body) as StrategyBody)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function changeLane(index: number, change: Partial<Pick<Lane, 'name' | 'description'>>) {
    setBody((current) => {
      if (!current) return current
      const lanes = current.lanes.map((lane, i) => (i === index ? { ...lane, ...change } : lane))
      return { ...current, lanes }
    })
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await saveProfileOutput('strategy', body as unknown as Record<string, unknown>)
      onSaved()
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : 'The change was not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded border border-border bg-background p-3">
      <h3 className="text-sm font-semibold">Strategy and lanes</h3>
      <VersionLine output={output} />
      <p className="text-sm">{body.overview}</p>
      <ul className="flex flex-col gap-3">
        {body.lanes.map((lane, index) => (
          <li key={lane.id} className="flex flex-col gap-1 rounded border border-border p-2">
            <input
              aria-label={`Name of lane ${lane.id}`}
              className="rounded border border-border bg-card p-1 text-sm font-semibold text-foreground"
              value={lane.name}
              onChange={(event) => changeLane(index, { name: event.target.value })}
            />
            <textarea
              aria-label={`Description of lane ${lane.id}`}
              className="rounded border border-border bg-card p-1 text-sm text-foreground"
              rows={2}
              value={lane.description}
              onChange={(event) => changeLane(index, { description: event.target.value })}
            />
            <p className="font-mono text-xs text-muted-foreground">
              facts: {lane.fact_ids.join(', ')}
            </p>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div>
        <Button disabled={busy} onClick={() => void save()}>
          Save as new version
        </Button>
      </div>
    </div>
  )
}
