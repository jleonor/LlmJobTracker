import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

// A long cell value truncates with "..." (the table's own column width decides where); hovering
// shows the full value in a tooltip. Used by every long-text column (Company, Title, Lane, Job
// portal, Next action, Notes).
export function TruncatedText({ value }: { value: string | null }) {
  if (value === null || value === '') return <span className="text-muted-foreground">-</span>
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span />}
        className="block max-w-full cursor-default truncate text-left"
      >
        {value}
      </TooltipTrigger>
      <TooltipContent>{value}</TooltipContent>
    </Tooltip>
  )
}
