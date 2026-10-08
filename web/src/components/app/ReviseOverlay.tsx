import { useCallback, useEffect, useState } from 'react'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { RunTrace } from '@/components/app/RunTrace'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchProfileOutputs, fetchReviseTurns, postReviseTurn } from '@/lib/api'
import { PROFILE_DOCUMENT_CONTEXT, PROFILE_DOCUMENT_TITLES } from '@/lib/profileDocuments'
import type { ProfileOutput, ReviseTurn } from '@/lib/types'

// How often the conversation is read back while the overlay is open (useClaudeJobs.ts's own
// pattern): tighter while a turn is still queued or running, so the chat and the document both
// update promptly once it finishes.
const POLL_MS = 4000
const ACTIVE_POLL_MS = 1000

// The Revise (LLM) overlay (brainstorm #4): the current document on the left, a chat on the
// right. Each sent message queues one Claude Job (D-106); its turn shows the user's ask plus a
// RunTrace for that job, so the model's progress reads the same way the analysis overlay's does.
export function ReviseOverlay({
  outputKind,
  open,
  onOpenChange,
  onChanged,
}: {
  outputKind: string
  open: boolean
  onOpenChange: (open: boolean) => void
  // Called once a turn's job finishes, so the Profile page's file row (size, date) catches up
  // to the new version the turn wrote (D-84).
  onChanged: () => void
}) {
  const [output, setOutput] = useState<ProfileOutput | null>(null)
  const [turns, setTurns] = useState<ReviseTurn[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  const reload = useCallback(() => {
    fetchReviseTurns(outputKind)
      .then((list) => {
        setTurns(list)
        setError(null)
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the conversation.')
      })
    fetchProfileOutputs()
      .then((list) => setOutput(list.find((candidate) => candidate.kind === outputKind) ?? null))
      .catch(() => undefined)
  }, [outputKind])

  useEffect(() => {
    if (open) reload()
  }, [open, reload])

  useEffect(() => {
    if (!open) return
    const active = turns.some((turn) => turn.job.status === 'processing' || turn.job.status === 'queued')
    const timer = window.setInterval(reload, active ? ACTIVE_POLL_MS : POLL_MS)
    return () => window.clearInterval(timer)
  }, [open, turns, reload])

  // Fires once there is at least one finished turn, and again each time another one finishes —
  // the signature is stable otherwise, so this does not fire on every poll tick.
  const doneSignature = turns
    .filter((turn) => turn.job.status === 'done')
    .map((turn) => turn.id)
    .join(',')
  useEffect(() => {
    if (doneSignature) onChanged()
    // onChanged is stable across renders in practice; doneSignature is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneSignature])

  async function send() {
    const text = message.trim()
    if (!text) return
    setSending(true)
    setError(null)
    try {
      await postReviseTurn(outputKind, text)
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
          <DialogTitle>Revise (LLM): {PROFILE_DOCUMENT_TITLES[outputKind] ?? outputKind}</DialogTitle>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-h-0 overflow-y-auto rounded border border-border p-3">
            {output ? (
              <MarkdownDocument text={output.document} />
            ) : (
              <p className="text-sm text-muted-foreground">Nothing to revise yet.</p>
            )}
          </div>
          <div className="flex min-h-0 flex-col gap-2">
            <div className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
              <span>Context:</span>
              {(PROFILE_DOCUMENT_CONTEXT[outputKind] ?? []).map((label) => (
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
