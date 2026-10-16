import { Badge } from '@/components/ui/badge'
import { STATUS_TONE } from '@/lib/tone'
import { cn } from '@/lib/utils'

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge
      variant="outline"
      className={cn('rounded-sm font-mono text-[11px] font-medium', STATUS_TONE[status])}
    >
      {status}
    </Badge>
  )
}
