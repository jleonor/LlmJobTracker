import { useEffect, useState } from 'react'

import { FilePreviewBody, useFilePreview } from '@/components/app/FilePreview'
import type { PreviewSource } from '@/components/app/FilePreview'
import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { ClaudeJob } from '@/lib/types'

// Job details, Positioning analysis, Application history, Tailored CV and Cover letter's
// Generate/Revise (LLM) (steps 30-33 and 38, job-llm-steps.md §2-6): unlike Listing's wizard,
// each reads data already stored on the application - there is no source to pick or text to
// review, so this is just a confirm step before the Claude Job runs, then its RunTrace. Reused
// across all five rather than writing the same confirm-then-trace dialog five times.
//
// `preview`, when given, puts the current file next to the confirm/trace column (D-135) -
// reusing FilePreview's own loading/rendering rather than a second viewer - matching
// ReviseOverlay's/GenerateListingOverlay's current-document-left layout. Job details,
// Positioning analysis and Application history pass nothing here: they edit structured fields,
// not one backing document, so there's nothing to preview.
export function GenerateSectionOverlay({
  title,
  hasData,
  preview,
  previewName,
  open,
  onOpenChange,
  onSubmit,
  onChanged,
}: {
  title: string
  hasData: boolean
  preview?: PreviewSource | null
  previewName?: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: () => Promise<ClaudeJob>
  onChanged: () => void
}) {
  const [running, setRunning] = useState(false)
  const [jobId, setJobId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { jobs } = useClaudeJobs()
  const job = jobId === null ? null : (jobs.find((candidate) => candidate.id === jobId) ?? null)

  // `preview` being present (even as `null`, meaning the file doesn't exist yet) is what turns
  // on the left-hand document pane; a dummy, inactive source keeps the hook call unconditional.
  const showPreview = preview !== undefined
  const previewState = useFilePreview(preview ?? { table: 'profile_file', id: -1 }, open && preview != null)

  useEffect(() => {
    if (!open) return
    setRunning(false)
    setJobId(null)
    setBusy(false)
    setError(null)
  }, [open])

  useEffect(() => {
    if (job?.status === 'done') onChanged()
    // onChanged is stable in practice; job.status is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  async function start() {
    setBusy(true)
    setError(null)
    try {
      const created = await onSubmit()
      setJobId(created.id)
      setRunning(true)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'This could not be started.')
    } finally {
      setBusy(false)
    }
  }

  const verb = hasData ? 'Revise' : 'Generate'

  // The confirm-then-trace column: a fixed height with its own scroll region (D-135), so a long
  // trace or an expanded "show the exchange" panel scrolls inside the dialog instead of growing
  // it past the viewport and pushing the close button out of reach.
  const body = (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
      {!running && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {hasData
              ? `This replaces the current ${title.toLowerCase()} with a new one.`
              : `Claude will fill in ${title.toLowerCase()} from what's already on this application.`}
          </p>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button disabled={busy} onClick={() => void start()} className="self-start">
            {busy ? 'Starting...' : verb}
          </Button>
        </div>
      )}
      {running && <RunTrace job={job} />}
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>
            {verb} (LLM): {title}
          </DialogTitle>
        </DialogHeader>
        {showPreview ? (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="min-h-0 flex-1 overflow-hidden rounded border border-border bg-background">
              {preview === null ? (
                <p className="p-3 text-sm text-muted-foreground">No file yet.</p>
              ) : (
                <FilePreviewBody name={previewName ?? title} state={previewState} />
              )}
            </div>
            {body}
          </div>
        ) : (
          body
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
