import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { RunTrace } from '@/components/app/RunTrace'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchJobReviseTurns, postJobReviseTurn, uploadJobFile } from '@/lib/api'
import type { ReviseTurn } from '@/lib/types'

// How often the conversation is read back while the overlay is open (ReviseOverlay.tsx's own
// pattern): tighter while a turn is still queued or running.
const POLL_MS = 4000
const ACTIVE_POLL_MS = 1000

// What each job-page section's chat turn reads (mirrors profileDocuments.ts's
// PROFILE_DOCUMENT_CONTEXT), shown as chips so the user can see what the model reads without
// opening the prompt itself. Only the implemented sections (D-136's build order) are listed.
const JOB_REVISE_CONTEXT: Record<string, string[]> = {
  job_details: ['Listing'],
  application_history: ['Filed emails'],
  positioning: ['Career history', 'Questionnaire report', 'Strategy', 'Job details'],
}

// Which upload kind a turn's attached file is filed under (D-138): an .eml/.msg files the same
// way an uploaded email already does, anything else goes to Additional files - the same split
// EmailsColumn's own upload already uses, just generalized to any file, not only emails.
function attachmentKind(file: File): string {
  const name = file.name.toLowerCase()
  if (name.endsWith('.msg')) return 'msg'
  if (name.endsWith('.eml')) return 'eml'
  return 'other'
}

// The job page's chat-revise overlay (D-136): the job-scoped counterpart to ReviseOverlay, same
// current-content-left, chat-right layout, but the left pane is whatever content the caller
// passes in (a structured-field section has no single document to show the way a Markdown file
// does), and `allowAttachment` turns on a file input next to the message box (Application
// history only, D-138) - the file is filed for real through the existing upload endpoint before
// the turn is sent, not held as throwaway context.
export function JobReviseOverlay({
  applicationId,
  sectionKind,
  title,
  leftPane,
  allowAttachment = false,
  open,
  onOpenChange,
  onChanged,
}: {
  applicationId: number
  sectionKind: string
  title: string
  leftPane: ReactNode
  allowAttachment?: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  // Called once a turn's job finishes, so the page's own fields catch up to what the turn wrote
  // - and right after a successful attachment upload, so Files shows it without waiting.
  onChanged: () => void
}) {
  const [turns, setTurns] = useState<ReviseTurn[]>([])
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [attachedFile, setAttachedFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

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
      let attachmentId: number | undefined
      if (attachedFile) {
        const filed = await uploadJobFile(applicationId, attachmentKind(attachedFile), attachedFile)
        attachmentId = filed.id
        onChanged()
      }
      await postJobReviseTurn(applicationId, sectionKind, text, attachmentId)
      setMessage('')
      setAttachedFile(null)
      if (fileInput.current) fileInput.current.value = ''
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
          <div className="min-h-0 overflow-y-auto rounded border border-border p-3">{leftPane}</div>
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
            {allowAttachment && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  ref={fileInput}
                  type="file"
                  className="sr-only"
                  id={`${sectionKind}-attachment`}
                  aria-label="Attach a file to this message"
                  onChange={(event) => setAttachedFile(event.target.files?.[0] ?? null)}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fileInput.current?.click()}
                >
                  Attach a file
                </Button>
                {attachedFile && (
                  <span className="flex items-center gap-1 truncate">
                    {attachedFile.name}
                    <button
                      type="button"
                      aria-label="Remove the attached file"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() => {
                        setAttachedFile(null)
                        if (fileInput.current) fileInput.current.value = ''
                      }}
                    >
                      ×
                    </button>
                  </span>
                )}
              </div>
            )}
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
