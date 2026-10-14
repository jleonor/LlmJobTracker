import { useEffect, useState } from 'react'

import { ApiError, fetchPromptExchange } from '@/lib/api'
import { PROFILE_DOCUMENT_TITLES } from '@/lib/profileDocuments'
import type { ClaudeJob, ClaudeJobPrompt, PromptExchange } from '@/lib/types'

// A revise prompt's kind is `revise_own_<document kind>` (D-106); the document it is about
// reads the same label a generating prompt for it would.
function labelFor(promptKind: string): string {
  const key = promptKind.startsWith('revise_own_') ? promptKind.slice('revise_own_'.length) : promptKind
  return PROFILE_DOCUMENT_TITLES[key] ?? promptKind
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

// The lines for one Claude Job, built from its prompts (the same records the LLM history
// screen shows). Nothing is sent by the model here; this only reads the queue. Used for a
// profile analysis (three prompts) and a Revise (LLM) turn (one prompt) alike.
export function traceLines(job: ClaudeJob, now: number = Date.now()): Line[] {
  const lines: Line[] = [{ time: clock(job.created_at), text: `${job.label} queued`, tone: 'info' }]
  for (const prompt of job.prompts) {
    const name = labelFor(prompt.prompt_kind)
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
    if (prompt.status === 'running' && prompt.started_at && !prompt.live_text) {
      // No streamed text yet (D-105 is unverified against a real run) — the elapsed time is
      // the only sign the run is still going. Once text streams in, that replaces this line
      // (see the "currently writing" block in RunTrace below).
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
      const tokens =
        prompt.input_tokens === null && prompt.output_tokens === null
          ? ''
          : `, ${(prompt.input_tokens ?? 0).toLocaleString()} in / ${(prompt.output_tokens ?? 0).toLocaleString()} out tokens`
      lines.push({
        time: clock(prompt.finished_at),
        text: `${name}: done${seconds}${cost}${tokens}`,
        tone: 'ok',
      })
    } else if (prompt.status === 'failed') {
      lines.push({ time: clock(prompt.finished_at), text: `${name}: failed. ${prompt.error ?? ''}`, tone: 'error' })
    } else if (prompt.status === 'cancelled') {
      lines.push({ time: null, text: `${name}: cancelled`, tone: 'warn' })
    }
  }
  if (job.status === 'paused') {
    lines.push({ time: null, text: job.error ?? 'Paused.', tone: 'warn' })
  } else if (job.status === 'done') {
    lines.push({ time: null, text: 'Finished.', tone: 'ok' })
  } else if (job.status === 'failed') {
    lines.push({ time: null, text: `Stopped. ${job.error ?? ''}`, tone: 'error' })
  } else if (job.status === 'queued') {
    lines.push({ time: null, text: 'Waiting for the worker.', tone: 'info' })
  }
  return lines
}

// A small terminal that shows what a Claude Job is doing, line by line, plus the answer
// streaming in live while a prompt runs (D-105). Used inline on the Profile page today, and
// meant to work the same way inside the analysis overlay and a Revise (LLM) chat turn.
// clearSignal, when it changes, hides the lines shown so far, the same way clearing a real
// terminal does: new lines still appear below. 0 means "never cleared" (the initial render).
export function RunTrace({ job, clearSignal = 0 }: { job: ClaudeJob | null; clearSignal?: number }) {
  const [showExchange, setShowExchange] = useState(false)
  const [cleared, setCleared] = useState<{ jobId: number; count: number } | null>(null)

  const lines = job ? traceLines(job) : []
  const visible = cleared && job && cleared.jobId === job.id ? lines.slice(cleared.count) : lines
  const running = job?.prompts.find((prompt) => prompt.status === 'running') ?? null

  useEffect(() => {
    if (clearSignal === 0) return // the initial render, not an actual click
    if (job) setCleared({ jobId: job.id, count: lines.length })
    // Only clearSignal should trigger this; lines/job are read at click time, not watched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clearSignal])

  return (
    <section aria-label="Run trace" className="flex flex-col gap-2 rounded border border-border bg-zinc-950 p-3">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wider text-zinc-400">Trace</h3>
        {job && <span className="font-mono text-xs text-zinc-500">{job.status}</span>}
      </div>
      <div aria-live="polite" className="max-h-64 overflow-y-auto font-mono text-xs leading-relaxed">
        {!job && <p className="text-zinc-500">Nothing has run yet.</p>}
        {job && visible.length === 0 && <p className="text-zinc-500">Cleared.</p>}
        {job &&
          visible.map((line, index) => (
            <p key={index} className={TONE[line.tone]}>
              {line.time && <span className="mr-2 text-zinc-500">[{line.time}]</span>}
              {line.text}
            </p>
          ))}
      </div>
      {running?.live_text && (
        <div className="flex flex-col gap-1 border-t border-zinc-800 pt-2">
          <p className="font-mono text-xs text-zinc-500">{labelFor(running.prompt_kind)}: writing...</p>
          <pre className="max-h-48 overflow-y-auto rounded bg-black p-2 font-mono text-xs whitespace-pre-wrap text-zinc-200">
            {running.live_text}
          </pre>
        </div>
      )}
      {job && (
        <div className="border-t border-zinc-800 pt-2">
          <button
            type="button"
            onClick={() => setShowExchange((current) => !current)}
            className="font-mono text-xs text-zinc-300 underline-offset-2 hover:underline"
          >
            {showExchange ? 'Hide' : 'Show'} the exchange with Claude
          </button>
          {showExchange && <Exchanges jobId={job.id} prompts={job.prompts} />}
        </div>
      )}
    </section>
  )
}

// What was sent to Claude and what came back, for each prompt that has finished (D-77).
// Opening one reads it from the API. Nothing is sent to Claude by opening it.
function Exchanges({ jobId, prompts }: { jobId: number; prompts: ClaudeJobPrompt[] }) {
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
            {labelFor(prompt.prompt_kind)}
            {prompt.status === 'failed' && ' (check failed)'}
          </button>
          {open === prompt.position && (
            <div className="flex flex-col gap-2">
              {shownError && <p className="text-red-400">{shownError}</p>}
              {!shownError && !shown && <p className="text-zinc-500">Reading...</p>}
              {shown && (
                <>
                  <PromptSentBlock text={shown.prompt_text} />
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

type PromptSegment = { kind: 'text'; text: string } | { kind: 'block'; header: string; body: string }

// A profile or revise prompt is built from `=== HEADER ===\nbody\n=== END ... ===` blocks (one
// per input file, plus one per document it reads), joined by plain instruction text
// (profile_pipeline.py's files_block/document_block). Split them apart so each block can be
// collapsed — the brainstorm's "make the bulky parts, like the input files, collapsible" — while
// the instructions around them stay visible as plain text.
export function splitPromptBlocks(text: string): PromptSegment[] {
  const pattern = /=== (.+?) ===\n([\s\S]*?)\n=== END .+? ===\n?/g
  const segments: PromptSegment[] = []
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const start = match.index
    if (start > cursor) {
      const before = text.slice(cursor, start)
      if (before.trim()) segments.push({ kind: 'text', text: before })
    }
    segments.push({ kind: 'block', header: match[1], body: match[2] })
    cursor = start + match[0].length
  }
  const rest = text.slice(cursor)
  if (rest.trim()) segments.push({ kind: 'text', text: rest })
  return segments
}

// What was sent to Claude for one prompt, shown as a labelled block with its bulky parts
// (file and document blocks) collapsed — reused by the analysis overlay's read-only prompt
// threads, not only this component's own "show the exchange" toggle.
export function PromptSentBlock({ text }: { text: string }) {
  const segments = splitPromptBlocks(text)
  return (
    <div className="flex flex-col gap-1">
      <p className="text-zinc-400">Sent to Claude ({text.length.toLocaleString()} characters)</p>
      <div className="flex max-h-96 flex-col gap-1 overflow-auto rounded bg-black p-2 text-zinc-200">
        {segments.map((segment, index) =>
          segment.kind === 'text' ? (
            <pre key={index} className="whitespace-pre-wrap">
              {segment.text}
            </pre>
          ) : (
            <details key={index} className="rounded border border-zinc-800">
              <summary className="cursor-pointer px-2 py-1 text-zinc-400 select-none">
                {segment.header} ({segment.body.length.toLocaleString()} characters)
              </summary>
              <pre className="border-t border-zinc-800 p-2 whitespace-pre-wrap">{segment.body}</pre>
            </details>
          ),
        )}
      </div>
    </div>
  )
}
