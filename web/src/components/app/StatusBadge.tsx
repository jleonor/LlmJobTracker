import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

// Colours follow the status chips in the Jobs table mockup. Unknown statuses fall back to grey.
// Rejected, Withdrawn and Expired (D-223) are the three end states (job_applications.py's
// END_STATUSES) and all share the same red tone, regardless of which ended the application.
const DEAD_TONE = 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]'
const TONE: Record<string, string> = {
  Identified: 'border-muted-foreground/40 text-muted-foreground',
  Applied: 'border-[#234875] bg-[#001c3a] text-[#a6c8fd]',
  Screening: 'border-[#4a3f7a] bg-[#1d1733] text-[#c9bcff]',
  Interview: 'border-[#5c4300] bg-[#2a1800] text-[#ffca85]',
  Offer: 'border-[#005333] bg-[#00210f] text-[#84e7b0]',
  Rejected: DEAD_TONE,
  Withdrawn: DEAD_TONE,
  Expired: DEAD_TONE,
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant="outline"
      className={cn('rounded-sm font-mono text-[11px] font-medium', TONE[status])}
    >
      {status}
    </Badge>
  )
}
