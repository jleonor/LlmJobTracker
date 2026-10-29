import { BriefcaseBusiness, LayoutDashboard, ListOrdered, Settings, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'

import { useTitlebarOverlayGutter } from '@/lib/useTitlebarOverlayGutter'
import { cn } from '@/lib/utils'

export type Screen = 'jobs' | 'dashboard' | 'profile' | 'queue' | 'settings'

// Jobs, Dashboard, Profile, LLM history and Settings have screens (Phase 7, D-195; Phase 10
// adds Dashboard).
const NAV: { label: string; icon: typeof UserRound; screen: Screen }[] = [
  { label: 'Job Applications', icon: BriefcaseBusiness, screen: 'jobs' },
  { label: 'Dashboard', icon: LayoutDashboard, screen: 'dashboard' },
  { label: 'Profile', icon: UserRound, screen: 'profile' },
  { label: 'LLM history', icon: ListOrdered, screen: 'queue' },
  { label: 'Settings', icon: Settings, screen: 'settings' },
]

type Props = {
  children: ReactNode
  current: Screen
  onNavigate: (screen: Screen) => void
  queueText: string
  userName: string
  // The header's "Trigger workflows" button (D-288): always visible (so its position never
  // shifts), disabled at zero, next to the LLM status - the same slot the original Add Job stub
  // button occupied before D-144 moved Add Job out of the header (that move was forced by Add
  // Job needing to navigate to the new application; this button needs no such navigation).
  stagedCount: number
  onTriggerStaged: () => void
  triggeringStaged: boolean
}

export function AppShell({
  children,
  current,
  onNavigate,
  queueText,
  userName,
  stagedCount,
  onTriggerStaged,
  triggeringStaged,
}: Props) {
  // Reserves exactly as much right-edge space as Windows' native title bar controls need, so
  // the header's own right-aligned content never renders underneath them (see the hook's own
  // comment - found live once Trigger workflows widened that group enough to reach them).
  const titlebarGutter = useTitlebarOverlayGutter()

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* The full-width top bar: title/logo left, LLM status + Trigger workflows right - no more
          boxed-in sidebar header cell (D-278). app-drag-region/app-no-drag (index.css) make this
          strip the Electron window's own draggable title bar, under the Windows titleBarOverlay
          (electron/main.js) - harmless, inert properties outside Electron. */}
      <header
        className="app-drag-region flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4"
        // px-4's own 1rem (16px) stays in charge when there's no overlay to clear (titlebarGutter
        // is 0 outside Electron/Windows) - only added to, never replaced, when there is one.
        style={titlebarGutter > 0 ? { paddingRight: titlebarGutter + 16 } : undefined}
      >
        <div className="flex min-w-0 items-center gap-2">
          <img src="/logo-white.svg" alt="" className="size-6 shrink-0" aria-hidden="true" />
          <span className="truncate text-lg font-semibold tracking-tight">{userName}'s Job Tracker</span>
        </div>
        <div className="app-no-drag flex shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={() => onNavigate('queue')}
            className="font-mono text-xs text-muted-foreground hover:text-foreground"
          >
            {queueText}
          </button>
          <button
            type="button"
            disabled={stagedCount === 0 || triggeringStaged}
            onClick={onTriggerStaged}
            className="rounded border border-border px-2 py-1 text-xs font-medium text-foreground transition-colors enabled:hover:bg-muted disabled:cursor-not-allowed disabled:text-muted-foreground disabled:opacity-50"
          >
            {triggeringStaged
              ? 'Triggering...'
              : stagedCount > 0
                ? `Trigger workflows (${stagedCount} staged)`
                : 'Trigger workflows'}
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-64 shrink-0 overflow-y-auto border-r border-border bg-card">
          <nav className="flex flex-col gap-0.5 p-2" aria-label="Main">
            {NAV.map(({ label, icon: Icon, screen }) => {
              const active = screen === current
              return (
                <button
                  key={label}
                  type="button"
                  onClick={() => onNavigate(screen)}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'flex items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors',
                    active
                      ? 'border-l-2 border-primary bg-secondary pl-[10px] font-semibold text-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </button>
              )
            })}
          </nav>
        </aside>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  )
}
