import { type ReactNode, useEffect, useState } from 'react'

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
    <div className="flex flex-col gap-3 rounded border border-border bg-background p-3">
      <h3 className="text-sm font-semibold">Questionnaire report</h3>
      <VersionLine output={output} />
      <ReportSection title="How the material reads">
        <p className="text-sm">{body.how_the_material_reads}</p>
      </ReportSection>
      <ReportSection title="Career narrative">
        <p className="text-sm">{body.career_narrative}</p>
      </ReportSection>
      <ReportSection title="Patterns">
        <ul className="flex flex-col gap-2 text-sm">
          {body.patterns.map((pattern) => (
            <li key={pattern.id}>
              <span className="font-semibold">{pattern.title}.</span> {pattern.text}{' '}
              <span className="font-mono text-xs text-muted-foreground">({pattern.questionnaire_ref})</span>
            </li>
          ))}
        </ul>
      </ReportSection>
      {body.independent_work.length > 0 && (
        <ReportSection title="Independent work">
          <ul className="flex flex-col gap-2 text-sm">
            {body.independent_work.map((item) => (
              <li key={item.title}>
                <span className="font-semibold">{item.title}.</span> {item.text}
              </li>
            ))}
          </ul>
        </ReportSection>
      )}
      {body.cv_support.length > 0 && (
        <ReportSection title="Support in the CV">
          <ul className="list-disc pl-5 text-sm">
            {body.cv_support.map((item) => (
              <li key={item.text}>{item.text}</li>
            ))}
          </ul>
        </ReportSection>
      )}
      {body.nuance.length > 0 && (
        <ReportSection title="Nuance a first reading misses">
          <ul className="flex flex-col gap-1 text-sm">
            {body.nuance.map((item) => (
              <li key={item.text}>
                {item.text}{' '}
                <span className="font-mono text-xs text-muted-foreground">({item.questionnaire_ref})</span>
              </li>
            ))}
          </ul>
        </ReportSection>
      )}
      {body.cv_implications.length > 0 && (
        <ReportSection title="Implications for the CV">
          <ul className="list-disc pl-5 text-sm">
            {body.cv_implications.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </ReportSection>
      )}
      {body.open_items.length > 0 && (
        <ReportSection title="Open items">
          <ul className="list-disc pl-5 text-sm">
            {body.open_items.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </ReportSection>
      )}
    </div>
  )
}

function ReportSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
      {children}
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

// The strategy by its sections (D-73). The user edits the differentiator, the lanes' roles and
// reasons, and the closing sections. Fits, fact links and the lists stay as Claude wrote them.
function StrategyForm({ output, onSaved }: { output: ProfileOutput; onSaved: () => void }) {
  const [body, setBody] = useState(() => structuredClone(output.body) as StrategyBody)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function changeLane(group: 'primary_lanes' | 'secondary_lanes', index: number, change: Partial<Lane>) {
    setBody((current) => {
      const lanes = current[group].map((lane, i) => (i === index ? { ...lane, ...change } : lane))
      return { ...current, [group]: lanes }
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
    <div className="flex flex-col gap-4 rounded border border-border bg-background p-3">
      <h3 className="text-sm font-semibold">Positioning strategy</h3>
      <VersionLine output={output} />

      <label className="flex flex-col gap-1 text-xs text-muted-foreground">
        Differentiator
        <textarea
          aria-label="Differentiator"
          className="rounded border border-border bg-card p-1 text-sm text-foreground"
          rows={3}
          value={body.differentiator}
          onChange={(event) => setBody({ ...body, differentiator: event.target.value })}
        />
      </label>

      {(['primary_lanes', 'secondary_lanes'] as const).map((group) => (
        <div key={group} className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {group === 'primary_lanes' ? 'Primary lanes' : 'Secondary lanes'}
          </h4>
          <ul className="flex flex-col gap-2">
            {body[group].map((lane, index) => (
              <li key={lane.id} className="flex flex-col gap-1 rounded border border-border p-2">
                <div className="flex items-baseline gap-2">
                  <input
                    aria-label={`Role of lane ${lane.id}`}
                    className="flex-1 rounded border border-border bg-card p-1 text-sm font-semibold text-foreground"
                    value={lane.role}
                    onChange={(event) => changeLane(group, index, { role: event.target.value })}
                  />
                  <span className="font-mono text-xs text-muted-foreground">fit {lane.fit} / 5</span>
                </div>
                <textarea
                  aria-label={`Why lane ${lane.id}`}
                  className="rounded border border-border bg-card p-1 text-sm text-foreground"
                  rows={2}
                  value={lane.why}
                  onChange={(event) => changeLane(group, index, { why: event.target.value })}
                />
                <p className="font-mono text-xs text-muted-foreground">
                  facts: {lane.fact_ids.join(', ')}
                </p>
              </li>
            ))}
            {body[group].length === 0 && <li className="text-xs text-muted-foreground">None.</li>}
          </ul>
        </div>
      ))}

      {body.avoid.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Avoid as primary targets
          </h4>
          <ul className="flex flex-col gap-1 text-sm">
            {body.avoid.map((item) => (
              <li key={item.role}>
                <span className="font-semibold">{item.role}.</span> {item.why}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(['geography', 'comp_anchor', 'effort_allocation'] as const).map((key) => (
        <label key={key} className="flex flex-col gap-1 text-xs text-muted-foreground">
          {key === 'geography' ? 'Geography' : key === 'comp_anchor' ? 'Comp anchor' : 'Effort allocation'}
          <textarea
            aria-label={key}
            className="rounded border border-border bg-card p-1 text-sm text-foreground"
            rows={2}
            value={body[key]}
            onChange={(event) => setBody({ ...body, [key]: event.target.value })}
          />
        </label>
      ))}

      {body.open_questions.length > 0 && (
        <div className="flex flex-col gap-1">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Open questions</h4>
          <ul className="list-disc pl-5 text-sm">
            {body.open_questions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

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
