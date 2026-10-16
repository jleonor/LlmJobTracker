// One shared color-by-meaning palette (D-225), reused everywhere a tracker status, a queue
// state, or a run-trace log line needs a color. Previously four separate maps, hand-copied
// hex triplet by hex triplet; unifying them surfaced a real drift, not just duplication:
// LlmHistoryPage's job-card badge used a different queued/processing/paused assignment than
// QueueStatusBadge's own badge for the same status elsewhere on the Job Application page. This
// file's QUEUE_TONE follows QueueStatusBadge's original mapping (the one with an explicit
// comment tying it to StatusBadge's own tones), so LlmHistoryPage's colors now match it.

const MUTED_TONE = 'border-muted-foreground/40 text-muted-foreground'
const BLUE_TONE = 'border-[#234875] bg-[#001c3a] text-[#a6c8fd]'
const PURPLE_TONE = 'border-[#4a3f7a] bg-[#1d1733] text-[#c9bcff]'
const AMBER_TONE = 'border-[#5c4300] bg-[#2a1800] text-[#ffca85]'
const GREEN_TONE = 'border-[#005333] bg-[#00210f] text-[#84e7b0]'
const RED_TONE = 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]'
const CANCELLED_TONE = 'border-muted-foreground/30 text-muted-foreground line-through'

// Just the text-color half of each tone above, for a plain colored label rather than a full
// bordered badge (LlmHistoryPage's per-date status counts).
const BLUE_TEXT = 'text-[#a6c8fd]'
const PURPLE_TEXT = 'text-[#c9bcff]'
const AMBER_TEXT = 'text-[#ffca85]'
const GREEN_TEXT = 'text-[#84e7b0]'
const RED_TEXT = 'text-[#ffb4ab]'
const CANCELLED_TEXT = 'text-muted-foreground line-through'

// QueueStatusBadge's and LlmHistoryPage's queue states (idle/queued/processing/paused/done/
// failed/cancelled, D-49 to D-52).
export const QUEUE_TONE: Record<string, string> = {
  idle: MUTED_TONE,
  queued: AMBER_TONE,
  processing: BLUE_TONE,
  paused: PURPLE_TONE,
  done: GREEN_TONE,
  failed: RED_TONE,
  cancelled: CANCELLED_TONE,
}

export const QUEUE_STATUS_TEXT: Record<string, string> = {
  idle: 'text-muted-foreground',
  queued: AMBER_TEXT,
  processing: BLUE_TEXT,
  paused: PURPLE_TEXT,
  done: GREEN_TEXT,
  failed: RED_TEXT,
  cancelled: CANCELLED_TEXT,
}

// StatusBadge's D-44/D-223 tracker statuses. Rejected, Withdrawn and Expired are the three end
// states and all share the same red tone, regardless of which ended the application.
export const STATUS_TONE: Record<string, string> = {
  Identified: MUTED_TONE,
  Applied: BLUE_TONE,
  Screening: PURPLE_TONE,
  Interview: AMBER_TONE,
  Offer: GREEN_TONE,
  Rejected: RED_TONE,
  Withdrawn: RED_TONE,
  Expired: RED_TONE,
}

// RunTrace's log-line severities - a different shape (text-only, no border/background) and a
// different color vocabulary, but the same idea of naming a color by meaning in one place.
export const LOG_TONE: Record<'info' | 'ok' | 'warn' | 'error', string> = {
  info: 'text-zinc-300',
  ok: 'text-emerald-400',
  warn: 'text-amber-300',
  error: 'text-red-400',
}
