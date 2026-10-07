import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ApiError, cancelClaudeJob, resumeClaudeJob } from '@/lib/api'
import type { ClaudeJob, ClaudeJobPrompt } from '@/lib/types'
import type { QueueState } from '@/lib/useClaudeJobs'

const TONE: Record<string, string> = {
  queued: 'border-[#234875] bg-[#001c3a] text-[#a6c8fd]',
  processing: 'border-[#4a3f7a] bg-[#1d1733] text-[#c9bcff]',
  paused: 'border-[#5c4300] bg-[#2a1800] text-[#ffca85]',
  done: 'border-[#005333] bg-[#00210f] text-[#84e7b0]',
  failed: 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]',
  cancelled: 'border-muted-foreground/30 text-muted-foreground line-through',
}

// Just the text colour from TONE, for the per-status counts beside a date (not a full badge).
const STATUS_TEXT: Record<string, string> = {
  queued: 'text-[#a6c8fd]',
  processing: 'text-[#c9bcff]',
  paused: 'text-[#ffca85]',
  done: 'text-[#84e7b0]',
  failed: 'text-[#ffb4ab]',
  cancelled: 'text-muted-foreground line-through',
}

// Active statuses first (they need attention), then resolved ones.
const STATUS_ORDER = ['processing', 'paused', 'queued', 'failed', 'done', 'cancelled']

// Prompt kinds, in the words the user sees on the Profile page.
const PROMPT_LABELS: Record<string, string> = {
  full_cv_history: 'Career history',
  questionnaire_analysis: 'Questionnaire report',
  strategy: 'Strategy',
}

const CAN_CANCEL = ['queued', 'paused', 'processing']

type PositionedJob = { job: ClaudeJob; position: number }
type DateGroup = { date: string; items: PositionedJob[] }

// Newest first, grouped by the day each job was created. Position is the job's place in
// creation order (the first job ever is #1), kept stable regardless of display order.
function groupByDate(jobs: ClaudeJob[]): DateGroup[] {
  const newestFirst = jobs.map((job, index) => ({ job, position: index + 1 })).reverse()
  const groups: DateGroup[] = []
  for (const item of newestFirst) {
    const date = item.job.created_at.slice(0, 10)
    const current = groups.at(-1)
    if (current && current.date === date) {
      current.items.push(item)
    } else {
      groups.push({ date, items: [item] })
    }
  }
  return groups
}

// How many of a group's jobs are in each status, in STATUS_ORDER, leaving out statuses with none.
function countByStatus(items: PositionedJob[]): [string, number][] {
  const counts = new Map<string, number>()
  for (const { job } of items) {
    counts.set(job.status, (counts.get(job.status) ?? 0) + 1)
  }
  return STATUS_ORDER.filter((status) => counts.has(status)).map((status) => [
    status,
    counts.get(status) as number,
  ])
}

// The Claude Jobs queue: one job runs at a time, in creation order (D-50, D-62, D-63).
export function LlmHistoryPage({ queue }: { queue: QueueState }) {
  const groups = groupByDate(queue.jobs)

  return (
    <section aria-labelledby="queue-heading" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 id="queue-heading" className="text-xl font-semibold tracking-tight">
          LLM history
        </h1>
        <span className="font-mono text-xs text-muted-foreground">
          {queue.jobs.length} {queue.jobs.length === 1 ? 'job' : 'jobs'} · updates every few seconds
        </span>
      </div>

      {queue.error && (
        <p role="alert" className="text-sm text-destructive">
          {queue.error}
        </p>
      )}

      {queue.jobs.length === 0 && !queue.error && (
        <p className="rounded border border-border p-6 text-center text-sm text-muted-foreground">
          No history yet. It appears here when you start the profile analysis.
        </p>
      )}

      {groups.map((group, index) => (
        <DateSection key={group.date} group={group} defaultOpen={index === 0} onChanged={queue.reload} />
      ))}
    </section>
  )
}

function DateSection({
  group,
  defaultOpen,
  onChanged,
}: {
  group: DateGroup
  defaultOpen: boolean
  onChanged: () => void
}) {
  const [open, setOpen] = useState(defaultOpen)
  const Chevron = open ? ChevronDown : ChevronRight

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-left text-sm font-semibold text-foreground"
      >
        <Chevron className="size-4 text-muted-foreground" aria-hidden="true" />
        {group.date}
        <span className="flex gap-2 font-mono text-xs font-normal">
          {countByStatus(group.items).map(([status, count]) => (
            <span key={status} className={STATUS_TEXT[status] ?? 'text-muted-foreground'}>
              {count} {status}
            </span>
          ))}
        </span>
      </button>
      {open && (
        <div className="flex flex-col gap-3">
          {group.items.map(({ job, position }) => (
            <JobCard key={job.id} job={job} position={position} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  )
}

type CardProps = { job: ClaudeJob; position: number; onChanged: () => void }

function JobCard({ job, position, onChanged }: CardProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(true)

  async function act(action: (id: number) => Promise<ClaudeJob>) {
    setBusy(true)
    setError(null)
    try {
      await action(job.id)
      onChanged()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The action did not complete.')
    } finally {
      setBusy(false)
    }
  }

  const Chevron = expanded ? ChevronDown : ChevronRight
  const doneCount = job.prompts.filter((prompt) => prompt.status === 'done').length

  return (
    <article
      aria-label={`Claude Job ${job.id}`}
      className="flex flex-col gap-3 rounded border border-border bg-card p-4"
    >
      <button
        type="button"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
        className="flex items-start justify-between gap-4 text-left"
      >
        <div className="flex items-start gap-1.5">
          <Chevron className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold">
              <span className="mr-2 font-mono text-xs text-muted-foreground">#{position}</span>
              {job.label}
            </h2>
            <p className="font-mono text-xs text-muted-foreground">
              created {job.created_at.replace('T', ' ').slice(0, 16)} UTC
              {!expanded && ` · ${doneCount}/${job.prompts.length} prompts`}
            </p>
          </div>
        </div>
        <Badge
          variant="outline"
          className={`shrink-0 rounded-sm font-mono text-[11px] font-normal ${TONE[job.status] ?? ''}`}
        >
          {job.status}
        </Badge>
      </button>

      {expanded && (
        <>
          {job.error && (
            <p className={job.status === 'failed' ? 'text-sm text-destructive' : 'text-sm text-[#ffca85]'}>
              {job.error}
            </p>
          )}

          {job.status === 'paused' && job.resume_at && (
            <p className="text-sm text-muted-foreground">
              Resumes by itself at {new Date(job.resume_at).toLocaleString()}.
            </p>
          )}

          <ol className="flex flex-col gap-1">
            {job.prompts.map((prompt) => (
              <PromptLine key={prompt.position} prompt={prompt} />
            ))}
          </ol>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}

          <div className="flex gap-2">
            {job.status === 'paused' && (
              <Button disabled={busy} onClick={() => void act(resumeClaudeJob)}>
                Resume
              </Button>
            )}
            {CAN_CANCEL.includes(job.status) && (
              <Button variant="outline" disabled={busy} onClick={() => void act(cancelClaudeJob)}>
                Cancel
              </Button>
            )}
          </div>
        </>
      )}
    </article>
  )
}

function PromptLine({ prompt }: { prompt: ClaudeJobPrompt }) {
  const cost = prompt.cost_usd === null ? null : `$${prompt.cost_usd.toFixed(4)}`
  return (
    <li className="flex items-center justify-between gap-4 text-sm">
      <span>
        {PROMPT_LABELS[prompt.prompt_kind] ?? prompt.prompt_kind}
        {prompt.error && prompt.status === 'failed' && (
          <span className="ml-2 text-xs text-destructive">{prompt.error}</span>
        )}
      </span>
      <span className="shrink-0 font-mono text-xs text-muted-foreground">
        {prompt.status}
        {cost && ` · ${cost}`}
        {prompt.duration_ms !== null && ` · ${(prompt.duration_ms / 1000).toFixed(1)} s`}
      </span>
    </li>
  )
}
