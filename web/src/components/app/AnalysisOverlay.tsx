import { useEffect, useState } from 'react'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchProfileOutputs } from '@/lib/api'
import type { ClaudeJob, ProfileOutput } from '@/lib/types'

const DOCUMENTS: { kind: string; title: string }[] = [
  { kind: 'full_cv_history', title: 'Career history' },
  { kind: 'questionnaire_analysis', title: 'Questionnaire report' },
  { kind: 'strategy', title: 'Strategy' },
]

// The overlay that replaces the inline terminal (brainstorm #2): the trace on the left, the
// three generated documents stacked on the right, each loading what already exists and filling
// in as the job finishes each one. Stays reopenable while the job keeps running in the
// background (D-62) — ProfileOutputs.tsx's "View run" button opens this the same way whether
// the job just started or has been running for a while.
export function AnalysisOverlay({
  open,
  onOpenChange,
  job,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: ClaudeJob | null
}) {
  const [outputs, setOutputs] = useState<ProfileOutput[]>([])
  const [error, setError] = useState<string | null>(null)
  // Bumped by the Clear button beside the trace; 0 means "never cleared" (RunTrace's own rule).
  const [clearSignal, setClearSignal] = useState(0)

  // Changes exactly when a prompt's status changes (a new one started, one finished, one was
  // skipped), so the documents are read again right when a new version could exist — not on
  // every poll tick that found nothing new.
  const progress = job?.prompts.map((prompt) => `${prompt.prompt_kind}:${prompt.status}`).join(',') ?? ''

  useEffect(() => {
    if (!open) return
    fetchProfileOutputs()
      .then((list) => {
        setOutputs(list)
        setError(null)
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the documents.')
      })
  }, [open, progress])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Profile analysis</DialogTitle>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="flex min-h-0 flex-col gap-2 overflow-y-auto">
            {job && (
              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => setClearSignal((current) => current + 1)}
              >
                Clear
              </Button>
            )}
            <RunTrace job={job} clearSignal={clearSignal} />
          </div>
          <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
            {error && <p className="text-sm text-destructive">{error}</p>}
            {DOCUMENTS.map(({ kind, title }) => (
              <DocumentPane key={kind} title={title} output={outputs.find((o) => o.kind === kind)} />
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function DocumentPane({ title, output }: { title: string; output: ProfileOutput | undefined }) {
  return (
    <section className="flex min-h-0 flex-1 flex-col rounded border border-border">
      <h3 className="shrink-0 border-b border-border px-3 py-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      <div className="min-h-32 overflow-y-auto p-3">
        {output ? (
          <MarkdownDocument text={output.document} />
        ) : (
          <p className="text-sm text-muted-foreground">Not written yet.</p>
        )}
      </div>
    </section>
  )
}
