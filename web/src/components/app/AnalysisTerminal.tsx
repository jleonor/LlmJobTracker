import { useEffect, useState } from 'react'

import { ApiError, fetchPromptExchange } from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { ClaudeJob, PromptExchange } from '@/lib/types'

const PROMPT_LABELS: Record<string, string> = {
  full_cv_history: 'Career history',
  questionnaire_analysis: 'Questionnaire report',
  strategy: 'Strategy',
}

type Line = { time: string | null; text: string; tone: 'info' | 'ok' | 'warn' | 'error' }

const TONE: Record<Line['tone'], string> = {
  info: 'text-zinc-300',
  ok: 'text-emerald-400',
  warn: 'text-amber-300',
  error: 'text-red-400',
}

function clock(iso: string | null): string | null {
  if (!iso) return null
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleTimeString([], { hour12: false })
}

// The lines for the latest profile analysis, built from its prompts (the same records the
// LLM history screen shows). Nothing is sent by the model here; this only reads the queue.
export function analysisLines(job: ClaudeJob, now: number = Date.now()): Line[] {
  const lines: Line[] = [{ time: clock(job.created_at), text: `${job.label} queued`, tone: 'info' }]
  for (const prompt of job.prompts) {
    const name = PROMPT_LABELS[prompt.prompt_kind] ?? prompt.prompt_kind
    if (prompt.skipped) {
      // The backend's own reason (e.g. "Skipped: using your own file."), not a generic message.
      const reason = (prompt.skip_reason ?? 'Skipped: already in place.').replace(/^Skipped:\s*/, '')
      lines.push({ time: null, text: `${name}: ${reason}`, tone: 'info' })
      continue
    }
    const model = prompt.model ? ` (${prompt.model})` : ''
    if (prompt.started_at) {
      lines.push({ time: clock(prompt.started_at), text: `${name}: started${model}`, tone: 'info' })
    }
    if (prompt.status === 'running' && prompt.started_at) {
      // A prompt can take several minutes. The elapsed time shows that the run is still going.
      const elapsed = Math.max(0, Math.round((now - new Date(prompt.started_at).getTime()) / 1000))
      const minutes = Math.floor(elapsed / 60)
      const seconds = String(elapsed % 60).padStart(2, '0')
      lines.push({ time: null, text: `${name}: still running, ${minutes}:${seconds} so far`, tone: 'info' })
    }
    // The answer is kept as soon as it arrives, so its arrival is logged before any check on it.
    if ((prompt.status === 'done' || prompt.status === 'failed') && prompt.answer_chars !== null) {
      lines.push({
        time: clock(prompt.finished_at),
        text: `${name}: answer received, ${prompt.answer_chars.toLocaleString()} characters`,
        tone: 'info',
      })
    }
    if (prompt.status === 'done') {
      const seconds = prompt.duration_ms === null ? '' : ` in ${(prompt.duration_ms / 1000).toFixed(1)} s`
      const cost = prompt.cost_usd === null ? '' : `, $${prompt.cost_usd.toFixed(4)}`
      lines.push({ time: clock(prompt.finished_at), text: `${name}: done${seconds}${cost}`, tone: 'ok' })
    } else if (prompt.status === 'failed') {
      lines.push({ time: clock(prompt.finished_at), text: `${name}: failed. ${prompt.error ?? ''}`, tone: 'error' })
    } else if (prompt.status === 'cancelled') {
      lines.push({ time: null, text: `${name}: cancelled`, tone: 'warn' })
    }
  }
  if (job.status === 'paused') {
    lines.push({ time: null, text: job.error ?? 'Paused.', tone: 'warn' })
  } else if (job.status === 'done') {
    lines.push({ time: null, text: 'Analysis finished. Refresh to see the outputs.', tone: 'ok' })
  } else if (job.status === 'failed') {
    lines.push({ time: null, text: `Analysis stopped. ${job.error ?? ''}`, tone: 'error' })
  } else if (job.status === 'queued') {
    lines.push({ time: null, text: 'Waiting for the worker.', tone: 'info' })
  }
  return lines
}

// A small terminal on the Profile page that shows what the analysis is doing, line by line.
// clearSignal comes from the "Clear" button beside it (ProfileOutputs); each change hides the
// lines shown so far, the same way clearing a real terminal does: new lines still appear below.
export function AnalysisTerminal({ clearSignal }: { clearSignal: number }) {
  const { jobs, error } = useClaudeJobs()
  const latest = [...jobs].reverse().find((job) => job.kind === 'profile_analysis')
  const [showExchange, setShowExchange] = useState(false)
  const [cleared, setCleared] = useState<{ jobId: number; count: number } | null>(null)

  const lines = latest ? analysisLines(latest) : []
  const visible = cleared && latest && cleared.jobId === latest.id ? lines.slice(cleared.count) : lines

  useEffect(() => {
    if (clearSignal === 0) return // the initial render, not an actual click
    if (latest) setCleared({ jobId: latest.id, count: lines.length })
    // Only clearSignal should trigger this; lines/latest are read at click time, not watched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clearSignal])

  return (
    <section aria-label="Analysis log" className="flex flex-col gap-2 rounded border border-border bg-zinc-950 p-3">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wider text-zinc-400">Analysis log</h3>
        {latest && <span className="font-mono text-xs text-zinc-500">{latest.status}</span>}
      </div>
      <div aria-live="polite" className="max-h-64 overflow-y-auto font-mono text-xs leading-relaxed">
        {error && <p className="text-red-400">{error}</p>}
        {!error && !latest && <p className="text-zinc-500">No analysis has run yet.</p>}
        {!error && latest && visible.length === 0 && <p className="text-zinc-500">Cleared.</p>}
        {latest &&
          visible.map((line, index) => (
            <p key={index} className={TONE[line.tone]}>
              {line.time && <span className="mr-2 text-zinc-500">[{line.time}]</span>}
              {line.text}
            </p>
          ))}
      </div>
      {latest && (
        <div className="border-t border-zinc-800 pt-2">
          <button
            type="button"
            onClick={() => setShowExchange((current) => !current)}
            className="font-mono text-xs text-zinc-300 underline-offset-2 hover:underline"
          >
            {showExchange ? 'Hide' : 'Show'} the exchange with Claude
          </button>
          {showExchange && <Exchanges jobId={latest.id} prompts={latest.prompts} />}
        </div>
      )}
    </section>
  )
}

// What was sent to Claude and what came back, for each prompt that has finished (D-77).
// Opening one reads it from the API. Nothing is sent to Claude by opening it.
function Exchanges({ jobId, prompts }: { jobId: number; prompts: ClaudeJob['prompts'] }) {
  // -1 means the user closed it. null means "the failed one, if there is one".
  const [chosen, setChosen] = useState<number | null>(null)
  const [loaded, setLoaded] = useState<{ position: number; exchange: PromptExchange } | null>(null)
  const [loadError, setLoadError] = useState<{ position: number; message: string } | null>(null)

  // A skipped prompt sent nothing, so it has no exchange to show.
  const finished = prompts.filter(
    (prompt) => !prompt.skipped && (prompt.status === 'done' || prompt.status === 'failed'),
  )
  const failed = [...finished].reverse().find((prompt) => prompt.status === 'failed')
  const open = chosen === -1 ? null : (chosen ?? failed?.position ?? null)

  useEffect(() => {
    if (open === null) return
    let cancelled = false
    fetchPromptExchange(jobId, open)
      .then((exchange) => {
        if (!cancelled) setLoaded({ position: open, exchange })
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        const message = failure instanceof ApiError ? failure.message : 'Could not read the exchange.'
        setLoadError({ position: open, message })
      })
    return () => {
      cancelled = true
    }
  }, [jobId, open])

  if (finished.length === 0) return null

  const shown = open !== null && loaded?.position === open ? loaded.exchange : null
  const shownError = open !== null && loadError?.position === open ? loadError.message : null

  return (
    <div className="flex flex-col gap-2 border-t border-zinc-800 pt-2 font-mono text-xs">
      {finished.map((prompt) => (
        <div key={prompt.position} className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => setChosen(open === prompt.position ? -1 : prompt.position)}
            className="self-start text-left text-zinc-300 underline-offset-2 hover:underline"
          >
            {open === prompt.position ? 'Hide' : 'Show'} what was sent and returned:{' '}
            {PROMPT_LABELS[prompt.prompt_kind] ?? prompt.prompt_kind}
            {prompt.status === 'failed' && ' (check failed)'}
          </button>
          {open === prompt.position && (
            <div className="flex flex-col gap-2">
              {shownError && <p className="text-red-400">{shownError}</p>}
              {!shownError && !shown && <p className="text-zinc-500">Reading...</p>}
              {shown && (
                <>
                  <ExchangeBlock
                    title={`Sent to Claude (${shown.prompt_text.length.toLocaleString()} characters)`}
                    text={shown.prompt_text}
                  />
                  <ExchangeBlock title="Claude answered" text={shown.result_text ?? '(no answer was kept)'} />
                  {shown.error && <p className="text-red-400">Check failed: {shown.error}</p>}
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function ExchangeBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-zinc-400">{title}</p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-black p-2 text-zinc-200">{text}</pre>
    </div>
  )
}
