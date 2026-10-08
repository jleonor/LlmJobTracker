import { useEffect, useState } from 'react'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { PromptSentBlock } from '@/components/app/RunTrace'
import { Badge } from '@/components/ui/badge'
import { ApiError, fetchPromptExchange } from '@/lib/api'
import { PROFILE_DOCUMENT_CONTEXT, PROFILE_DOCUMENT_TITLES } from '@/lib/profileDocuments'
import type { ClaudeJob, ClaudeJobPrompt, PromptExchange } from '@/lib/types'

// One document's own read-only "chat" — the prompt that was (or will be) sent, and what Claude
// answered, with no input of its own. Three of these, one per document, replace the single
// combined trace: each document gets its own thread instead of one shared terminal.
export function PromptThread({ job, kind }: { job: ClaudeJob | null; kind: string }) {
  const title = PROFILE_DOCUMENT_TITLES[kind] ?? kind
  const context = PROFILE_DOCUMENT_CONTEXT[kind] ?? []
  const prompt = job?.prompts.find((candidate) => candidate.prompt_kind === kind) ?? null

  const [exchange, setExchange] = useState<PromptExchange | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!job || !prompt || prompt.skipped) return
    let cancelled = false
    fetchPromptExchange(job.id, prompt.position)
      .then((loaded) => {
        if (!cancelled) {
          setExchange(loaded)
          setError(null)
        }
      })
      .catch((failure: unknown) => {
        if (cancelled) return
        setError(failure instanceof ApiError ? failure.message : 'Could not read this prompt.')
      })
    return () => {
      cancelled = true
    }
    // Refetched whenever this prompt's own status changes (queued -> running -> done), not on
    // every poll tick, so the prompt text shows up as soon as it is built and the answer as
    // soon as it is kept (D-77). job/prompt themselves are read at effect-run time, not watched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, prompt?.position, prompt?.status])

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded border border-border">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        <StatusLabel prompt={prompt} />
      </div>
      {context.length > 0 && (
        <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border px-3 py-2 text-xs text-muted-foreground">
          <span>Context:</span>
          {context.map((label) => (
            <Badge key={label} variant="outline" className="rounded-sm font-mono text-[10px] font-normal">
              {label}
            </Badge>
          ))}
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        {!prompt && <p className="text-sm text-muted-foreground">Not queued yet.</p>}
        {prompt?.skipped && (
          <Bubble align="start">
            {(prompt.skip_reason ?? 'Skipped: already in place.').replace(/^Skipped:\s*/, '')}
          </Bubble>
        )}
        {prompt && !prompt.skipped && (
          <>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Bubble align="end">
              {exchange?.prompt_text ? (
                <PromptSentBlock text={exchange.prompt_text} />
              ) : (
                <span className="text-muted-foreground">Not sent yet.</span>
              )}
            </Bubble>
            <ClaudeBubble prompt={prompt} exchange={exchange} />
          </>
        )}
      </div>
    </section>
  )
}

function StatusLabel({ prompt }: { prompt: ClaudeJobPrompt | null }) {
  if (!prompt) return null
  if (prompt.skipped) return <span className="text-xs text-muted-foreground">skipped</span>
  if (prompt.status === 'done') {
    const seconds = prompt.duration_ms === null ? '' : ` · ${(prompt.duration_ms / 1000).toFixed(1)}s`
    const cost = prompt.cost_usd === null ? '' : ` · $${prompt.cost_usd.toFixed(4)}`
    return (
      <span className="text-xs text-emerald-600 dark:text-emerald-400">
        done{seconds}
        {cost}
      </span>
    )
  }
  if (prompt.status === 'failed') return <span className="text-xs text-destructive">failed</span>
  return <span className="text-xs text-muted-foreground">{prompt.status}</span>
}

function Bubble({ align, children }: { align: 'start' | 'end'; children: React.ReactNode }) {
  return (
    <div className={`flex ${align === 'end' ? 'justify-end' : 'justify-start'}`}>
      <div className="w-full max-w-full rounded bg-muted px-3 py-2 text-sm">{children}</div>
    </div>
  )
}

// Claude's side of the thread: live text while it writes, the final document once done, or the
// failure reason. Prefers the streamed-so-far text over the elapsed time (D-105's live
// streaming, once a real run confirms the event shape it assumes — see claude_code_runner.py).
function ClaudeBubble({
  prompt,
  exchange,
}: {
  prompt: ClaudeJobPrompt
  exchange: PromptExchange | null
}) {
  if (prompt.status === 'running') {
    return (
      <Bubble align="start">
        {prompt.live_text ? (
          <pre className="max-h-64 overflow-y-auto whitespace-pre-wrap">{prompt.live_text}</pre>
        ) : (
          <span className="text-muted-foreground">Writing...</span>
        )}
      </Bubble>
    )
  }
  if (prompt.status === 'failed') {
    return (
      <Bubble align="start">
        <span className="text-destructive">{prompt.error ?? 'The run failed.'}</span>
      </Bubble>
    )
  }
  if (prompt.status === 'cancelled') {
    return (
      <Bubble align="start">
        <span className="text-muted-foreground">Cancelled.</span>
      </Bubble>
    )
  }
  if (prompt.status === 'done') {
    return (
      <Bubble align="start">
        {exchange?.result_text ? (
          <MarkdownDocument text={exchange.result_text} />
        ) : (
          <span className="text-muted-foreground">Reading...</span>
        )}
      </Bubble>
    )
  }
  return (
    <Bubble align="start">
      <span className="text-muted-foreground">Waiting for the worker.</span>
    </Bubble>
  )
}
