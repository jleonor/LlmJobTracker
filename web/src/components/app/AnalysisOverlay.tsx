import { useEffect, useState } from 'react'

import { PromptThread } from '@/components/app/PromptThread'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Tabs, TabsList, TabsPanel, TabsTab } from '@/components/ui/tabs'
import { PROFILE_DOCUMENT_ORDER, PROFILE_DOCUMENT_TITLES } from '@/lib/profileDocuments'
import type { ClaudeJob } from '@/lib/types'

// Whichever document's prompt is currently running, if any — the one the tabs should follow.
function runningKind(job: ClaudeJob | null): string | null {
  if (!job) return null
  return (
    PROFILE_DOCUMENT_ORDER.find(
      (kind) => job.prompts.find((prompt) => prompt.prompt_kind === kind)?.status === 'running',
    ) ?? null
  )
}

// The overlay that replaces the inline terminal (brainstorm #2): one read-only "chat" per
// document — the prompt sent and what Claude answered, with no input of its own — instead of a
// single combined trace. Each thread fetches its own prompt text and answer as soon as they
// exist (PromptThread.tsx), so a document shows up without waiting for the whole job. Stays
// reopenable while the job keeps running in the background (D-62) — ProfileOutputs.tsx's
// "View last run" button opens this the same way whether the job just started or has been
// running for a while.
//
// Tabs, not three always-visible columns (D-135): only one document is actually being written at
// a time, so the active tab follows whichever prompt is running, giving it the overlay's full
// width instead of sharing it with two idle ones. The user can switch away at any time; the next
// prompt to start running pulls the tab back, the same "fires on change, not on every poll tick"
// pattern ReviseOverlay's onChanged effect already uses.
export function AnalysisOverlay({
  open,
  onOpenChange,
  job,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  job: ClaudeJob | null
}) {
  const [tab, setTab] = useState<string>(PROFILE_DOCUMENT_ORDER[0])
  const active = runningKind(job)

  useEffect(() => {
    if (open) setTab(active ?? PROFILE_DOCUMENT_ORDER[0])
    // Only `open` resets to a clean start; `active`'s own change (handled below) is what moves
    // the tab once the overlay is already open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (active) setTab(active)
  }, [active])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>Profile analysis</DialogTitle>
        </DialogHeader>
        <Tabs value={tab} onValueChange={(value) => setTab(String(value))} className="flex min-h-0 flex-1 flex-col gap-3">
          <TabsList>
            {PROFILE_DOCUMENT_ORDER.map((kind) => (
              <TabsTab key={kind} value={kind}>
                {PROFILE_DOCUMENT_TITLES[kind] ?? kind}
                {active === kind && (
                  <span className="size-1.5 rounded-full bg-primary" aria-label="Processing" />
                )}
              </TabsTab>
            ))}
          </TabsList>
          {PROFILE_DOCUMENT_ORDER.map((kind) => (
            <TabsPanel key={kind} value={kind} keepMounted className="flex min-h-0 flex-1 flex-col">
              <PromptThread job={job} kind={kind} />
            </TabsPanel>
          ))}
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
