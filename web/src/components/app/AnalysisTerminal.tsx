import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { ClaudeJob } from '@/lib/types'

const PROMPT_LABELS: Record<string, string> = {
  full_cv_history: 'Career history',
  fact_sheet: 'Fact Sheet',
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
// Claude Jobs screen shows). Nothing is sent by the model here; this only reads the queue.
export function analysisLines(job: ClaudeJob, now: number = Date.now()): Line[] {
  const lines: Line[] = [{ time: clock(job.created_at), text: `${job.label} queued`, tone: 'info' }]
  for (const prompt of job.prompts) {
    const name = PROMPT_LABELS[prompt.prompt_kind] ?? prompt.prompt_kind
    if (prompt.skipped) {
      lines.push({ time: null, text: `${name}: already in place, skipped`, tone: 'info' })
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
export function AnalysisTerminal() {
  const { jobs, error } = useClaudeJobs()
  const latest = [...jobs].reverse().find((job) => job.kind === 'profile_analysis')

  return (
    <section aria-label="Analysis log" className="flex flex-col gap-2 rounded border border-border bg-zinc-950 p-3">
      <div className="flex items-baseline justify-between gap-4">
        <h3 className="font-mono text-xs uppercase tracking-wider text-zinc-400">Analysis log</h3>
        {latest && <span className="font-mono text-xs text-zinc-500">{latest.status}</span>}
      </div>
      <div aria-live="polite" className="max-h-64 overflow-y-auto font-mono text-xs leading-relaxed">
        {error && <p className="text-red-400">{error}</p>}
        {!error && !latest && <p className="text-zinc-500">No analysis has run yet.</p>}
        {latest &&
          analysisLines(latest).map((line, index) => (
            <p key={index} className={TONE[line.tone]}>
              {line.time && <span className="mr-2 text-zinc-500">[{line.time}]</span>}
              {line.text}
            </p>
          ))}
      </div>
    </section>
  )
}
