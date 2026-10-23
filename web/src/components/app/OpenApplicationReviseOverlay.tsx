import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchOpenApplicationReviseTurns, postOpenApplicationReviseTurn } from '@/lib/api'
import type { ReviseTurn } from '@/lib/types'

// Mirrors JobReviseOverlay, trimmed: no attachment support (none of Open Applications' four
// sections take one, open-application-domain.md).
const POLL_MS = 4000
const ACTIVE_POLL_MS = 1000

export function OpenApplicationReviseOverlay({
  applicationId,
  sectionKind,
  title,
  leftPane,
  open,
  onOpenChange,
  onChanged,
}: {
  applicationId: number
  sectionKind: string
  title: string
  leftPane: ReactNode
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => void
}) {
  const [turns, setTurns] = useState<ReviseTurn[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)

  const reload = useCallback(() => {
    fetchOpenApplicationReviseTurns(applicationId, sectionKind)
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
      await postOpenApplicationReviseTurn(applicationId, sectionKind, text)
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
          <div className="flex min-h-0 flex-col overflow-y-auto rounded border border-border p-3">
            {leftPane}
          </div>
          <div className="flex min-h-0 flex-col gap-2">
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
