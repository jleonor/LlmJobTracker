import { useEffect, useState } from 'react'

import { AnalysisOverlay } from '@/components/app/AnalysisOverlay'
import { Button } from '@/components/ui/button'
import { ApiError, startProfileAnalysis } from '@/lib/api'
import type { ClaudeJob } from '@/lib/types'

// Profile analysis sits at the top of the "LLM Files" group (D-58), above the three documents
// it writes, which are read and reopened as files under their own upload sections below (D-84,
// D-86); nothing about their content is shown here. Running the analysis opens the overlay
// (brainstorm #2) instead of showing a terminal inline on the page; "View last run" reopens it
// later, whether the job is still going in the background or already finished.
export function ProfileOutputs({
  onChanged,
  refreshKey,
  analysis,
}: {
  onChanged: () => void
  refreshKey: number | null
  // The latest profile_analysis Claude Job, read once by the Profile page's own queue poll
  // (ProfilePage.tsx) rather than a second poll here.
  analysis: ClaudeJob | null
}) {
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [overlayOpen, setOverlayOpen] = useState(false)

  // When the latest analysis finishes, the file list is read again without a click, so a new
  // or changed document shows up where it can be opened.
  useEffect(() => {
    if (refreshKey !== null) onChanged()
    // onChanged is stable across renders in practice; refreshKey is the only real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  async function handleStart() {
    setStarting(true)
    setNotice(null)
    try {
      await startProfileAnalysis()
      setOverlayOpen(true)
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : 'The analysis did not start.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <section aria-labelledby="outputs-heading" className="flex flex-col gap-4 rounded border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="outputs-heading" className="text-sm font-semibold">
            Profile analysis
          </h2>
          <p className="text-xs text-muted-foreground">
            Run the analysis to make what is missing. Anything you uploaded is used as-is. Each
            document appears as a file under its section below once it is ready.
          </p>
        </div>
        <div className="flex gap-2">
          {analysis && (
            <Button variant="outline" onClick={() => setOverlayOpen(true)}>
              View last run
            </Button>
          )}
          <Button disabled={starting} onClick={() => void handleStart()}>
            {starting ? 'Starting...' : 'Run profile analysis'}
          </Button>
        </div>
      </div>

      {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

      <AnalysisOverlay open={overlayOpen} onOpenChange={setOverlayOpen} job={analysis} />
    </section>
  )
}
