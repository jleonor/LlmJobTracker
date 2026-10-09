import { useEffect, useState } from 'react'

import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError } from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { ClaudeJob } from '@/lib/types'

// Job details, Positioning analysis and Application history's Generate/Revise (LLM) (steps
// 30-33, job-llm-steps.md §2-4): unlike Listing's wizard, each reads data already stored on the
// application - there is no source to pick or text to review, so this is just a confirm step
// before the Claude Job runs, then its RunTrace. Reused across all three rather than writing the
// same confirm-then-trace dialog three times.
export function GenerateSectionOverlay({
  title,
  hasData,
  open,
  onOpenChange,
  onSubmit,
  onChanged,
}: {
  title: string
  hasData: boolean
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-3">
        <DialogHeader>
          <DialogTitle>
            {verb} (LLM): {title}
          </DialogTitle>
        </DialogHeader>
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
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
