import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { QueueStatus } from '@/lib/types'

// Colours echo StatusBadge's tones, reused for the Claude Jobs queue (D-49 to D-52) instead of
// the D-44 tracker status. Shown beside the status and lane tags on the Job Application page
// (D-56). Reads "LLM", not "Claude" (D-100): the runner is Claude Code for now (D-19), but the
// label should not commit to one vendor if a different runner is tried later.
const TONE: Record<QueueStatus, string> = {
  idle: 'border-muted-foreground/40 text-muted-foreground',
  queued: 'border-[#5c4300] bg-[#2a1800] text-[#ffca85]',
  processing: 'border-[#234875] bg-[#001c3a] text-[#a6c8fd]',
  paused: 'border-[#4a3f7a] bg-[#1d1733] text-[#c9bcff]',
  done: 'border-[#005333] bg-[#00210f] text-[#84e7b0]',
  failed: 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]',
  cancelled: 'border-muted-foreground/30 text-muted-foreground line-through',
}

export function QueueStatusBadge({ status }: { status: QueueStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn('rounded-sm font-mono text-[11px] font-medium', TONE[status])}
    >
      LLM: {status}
    </Badge>
  )
}
