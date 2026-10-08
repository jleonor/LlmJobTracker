import { PromptThread } from '@/components/app/PromptThread'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { PROFILE_DOCUMENT_ORDER } from '@/lib/profileDocuments'
import type { ClaudeJob } from '@/lib/types'

// The overlay that replaces the inline terminal (brainstorm #2): one read-only "chat" per
// document — the prompt sent and what Claude answered, with no input of its own — instead of a
// single combined trace. Each thread fetches its own prompt text and answer as soon as they
// exist (PromptThread.tsx), so a document shows up without waiting for the whole job. Stays
// reopenable while the job keeps running in the background (D-62) — ProfileOutputs.tsx's
// "View last run" button opens this the same way whether the job just started or has been
// running for a while.
export function AnalysisOverlay({
  open,
  onOpenChange,
  job,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: ClaudeJob | null
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Profile analysis</DialogTitle>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-3">
          {PROFILE_DOCUMENT_ORDER.map((kind) => (
            <PromptThread key={kind} job={job} kind={kind} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
