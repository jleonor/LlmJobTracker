import { useEffect, useState } from 'react'

import { AnalysisTerminal } from '@/components/app/AnalysisTerminal'
import { Button } from '@/components/ui/button'
import { ApiError, startProfileAnalysis } from '@/lib/api'

// Profile analysis on the Profile page (D-58). The three documents (career history,
// questionnaire analysis, strategy) are read and reopened as files under their own upload
// sections above (D-84, D-86); nothing about their content is shown here.
export function ProfileOutputs({ onChanged, refreshKey }: { onChanged: () => void; refreshKey: number | null }) {
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

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
      const job = await startProfileAnalysis()
      setNotice(`Started "${job.label}". It runs in the background; refresh to see the files.`)
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
            document appears as a file under its section above once it is ready.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onChanged}>
            Refresh
          </Button>
          <Button disabled={starting} onClick={() => void handleStart()}>
            {starting ? 'Starting...' : 'Run profile analysis'}
          </Button>
        </div>
      </div>

      {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

      <AnalysisTerminal />
    </section>
  )
}
