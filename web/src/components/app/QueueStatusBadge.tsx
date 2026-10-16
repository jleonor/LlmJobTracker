import { Badge } from '@/components/ui/badge'
import { QUEUE_TONE } from '@/lib/tone'
import { cn } from '@/lib/utils'
import type { QueueStatus } from '@/lib/types'

// Reused for the Claude Jobs queue (D-49 to D-52) instead of the D-44 tracker status. Shown
// beside the status and lane tags on the Job Application page (D-56). Reads "LLM", not "Claude"
// (D-100): the runner is Claude Code for now (D-19), but the label should not commit to one
// vendor if a different runner is tried later.
export function QueueStatusBadge({ status }: { status: QueueStatus }) {
  return (
    <Badge
      variant="outline"
      className={cn('rounded-sm font-mono text-[11px] font-medium', QUEUE_TONE[status])}
    >
      LLM: {status}
    </Badge>
  )
}
