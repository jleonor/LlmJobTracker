import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

// Colours follow the status chips in the Jobs table mockup. Unknown statuses fall back to grey.
const TONE: Record<string, string> = {
  Identified: 'border-muted-foreground/40 text-muted-foreground',
  Applied: 'border-[#234875] bg-[#001c3a] text-[#a6c8fd]',
  Screening: 'border-[#4a3f7a] bg-[#1d1733] text-[#c9bcff]',
  Interview: 'border-[#5c4300] bg-[#2a1800] text-[#ffca85]',
  Offer: 'border-[#005333] bg-[#00210f] text-[#84e7b0]',
  Rejected: 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]',
  Withdrawn: 'border-muted-foreground/30 text-muted-foreground line-through',
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
