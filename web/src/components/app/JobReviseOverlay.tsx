import { useCallback, useEffect, useState } from 'react'

import { RunTrace } from '@/components/app/RunTrace'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchJobReviseTurns, postJobReviseTurn } from '@/lib/api'
import type { ReviseTurn } from '@/lib/types'

// How often the conversation is read back while the overlay is open (ReviseOverlay.tsx's own
// pattern): tighter while a turn is still queued or running.
const POLL_MS = 4000
const ACTIVE_POLL_MS = 1000

// What each job-page section's chat turn reads (mirrors profileDocuments.ts's
// PROFILE_DOCUMENT_CONTEXT), shown as chips so the user can see what the model reads without
// opening the prompt itself. Only job_details has a real chat so far (D-136's build order).
const JOB_REVISE_CONTEXT: Record<string, string[]> = {
  job_details: ['Listing'],
}

// The job page's chat-revise overlay (D-136): the job-scoped counterpart to ReviseOverlay, same
// current-content-left, chat-right layout, but the "document" on the left is Job details' own
// description and numbered requirements, not a single Markdown file - there's no document to
// show for a section backed by structured fields, so this renders them directly instead of
// reusing MarkdownDocument. Each requirement keeps the number the chat prompt itself uses
// ("Current requirements, numbered"), so a message like "remove #3" refers to what the user sees.
export function JobReviseOverlay({
  applicationId,
  sectionKind,
  title,
  description,
  requirements,
  open,
  onOpenChange,
  onChanged,
}: {
  applicationId: number
  sectionKind: string
  title: string
  description: string | null
  requirements: string[]
  open: boolean
  onOpenChange: (open: boolean) => void
  // Called once a turn's job finishes, so the page's own fields catch up to what the turn wrote.
  onChanged: () => void
}) {
  const [turns, setTurns] = useState<ReviseTurn[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  const reload = useCallback(() => {
    fetchJobReviseTurns(applicationId, sectionKind)
      .then((list) => {
        setTurns(list)
        setError(null)
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the conversation.')
      })
  }, [applicationId, sectionKind])

  useEffect(() => {
    if (open) reload()
  }, [open, reload])

  useEffect(() => {
    if (!open) return
    const active = turns.some((turn) => turn.job.status === 'processing' || turn.job.status === 'queued')
    const timer = window.setInterval(reload, active ? ACTIVE_POLL_MS : POLL_MS)
    return () => window.clearInterval(timer)
  }, [open, turns, reload])

  // Fires once there is at least one finished turn, and again each time another one finishes.
  const doneSignature = turns
    .filter((turn) => turn.job.status === 'done')
    .map((turn) => turn.id)
    .join(',')
  useEffect(() => {
    if (doneSignature) onChanged()
    // onChanged is stable in practice; doneSignature is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneSignature])

  async function send() {
    const text = message.trim()
    if (!text) return
    setSending(true)
    setError(null)
    try {
      await postJobReviseTurn(applicationId, sectionKind, text)
      setMessage('')
      reload()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The message could not be sent.')
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Revise (LLM): {title}</DialogTitle>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-h-0 overflow-y-auto rounded border border-border p-3">
            <CurrentJobDetails description={description} requirements={requirements} />
          </div>
          <div className="flex min-h-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <span>Context:</span>
              {(JOB_REVISE_CONTEXT[sectionKind] ?? []).map((label) => (
                <Badge key={label} variant="outline" className="rounded-sm font-mono text-[10px] font-normal">
                  {label}
                </Badge>
              ))}
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto rounded border border-border p-3">
              {error && <p className="text-sm text-destructive">{error}</p>}
              {turns.length === 0 && (
                <p className="text-sm text-muted-foreground">Ask for a change below.</p>
              )}
              {turns.map((turn) => (
                <Turn key={turn.id} turn={turn} />
              ))}
            </div>
            <div className="flex gap-2">
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Ask for a change..."
                rows={2}
                className="flex-1 resize-none rounded border border-border bg-background p-2 text-sm"
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void send()
                  }
                }}
              />
              <Button disabled={sending || !message.trim()} onClick={() => void send()}>
                {sending ? 'Sending...' : 'Send'}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function CurrentJobDetails({
  description,
  requirements,
}: {
  description: string | null
  requirements: string[]
}) {
  if (!description && requirements.length === 0) {
    return <p className="text-sm text-muted-foreground">Nothing to revise yet.</p>
  }
  return (
    <div className="flex flex-col gap-3 text-sm">
      {description && <p className="whitespace-pre-wrap">{description}</p>}
      {requirements.length > 0 && (
        <ol className="list-decimal space-y-1 pl-5">
          {requirements.map((requirement) => (
            <li key={requirement}>{requirement}</li>
          ))}
        </ol>
      )}
    </div>
  )
}

function Turn({ turn }: { turn: ReviseTurn }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded bg-primary/10 px-3 py-2 text-sm whitespace-pre-wrap">
          {turn.message}
        </div>
      </div>
      <RunTrace job={turn.job} />
    </div>
  )
}
