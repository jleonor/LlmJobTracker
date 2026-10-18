import {
  BriefcaseBusiness,
  GitBranch,
  LayoutDashboard,
  ListOrdered,
  Settings,
  UserRound,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

export type Screen = 'jobs' | 'dashboard' | 'profile' | 'queue' | 'settings'

// Jobs, Dashboard, Profile, LLM history and Settings have screens (Phase 7, D-195; Phase 10
// adds Dashboard). Run Trace is still a placeholder for a later phase.
const NAV: { label: string; icon: typeof UserRound; screen: Screen | null }[] = [
  { label: 'Job Applications', icon: BriefcaseBusiness, screen: 'jobs' },
  { label: 'Dashboard', icon: LayoutDashboard, screen: 'dashboard' },
  { label: 'Profile', icon: UserRound, screen: 'profile' },
  { label: 'LLM history', icon: ListOrdered, screen: 'queue' },
  { label: 'Settings', icon: Settings, screen: 'settings' },
  { label: 'Run Trace', icon: GitBranch, screen: null },
]

type Props = {
  children: ReactNode
  current: Screen
  onNavigate: (screen: Screen) => void
  queueText: string
  userName: string
}

export function AppShell({ children, current, onNavigate, queueText, userName }: Props) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="truncate text-lg font-semibold tracking-tight">{userName}'s Job Tracker</span>
        </div>
        <nav className="flex flex-col gap-0.5 p-2" aria-label="Main">
          {NAV.map(({ label, icon: Icon, screen }) => {
            const active = screen !== null && screen === current
            return (
              <button
                key={label}
                type="button"
                disabled={screen === null}
                onClick={screen === null ? undefined : () => onNavigate(screen)}
                aria-current={active ? 'page' : undefined}
                title={screen === null ? 'Not in this phase yet' : undefined}
                className={cn(
                  'flex items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors',
                  active
                    ? 'border-l-2 border-primary bg-secondary pl-[10px] font-semibold text-foreground'
                    : screen === null
                      ? 'cursor-not-allowed text-muted-foreground opacity-60'
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

      <div className="pl-64">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-end gap-4 border-b border-border bg-card/90 px-6 backdrop-blur">
          <button
            type="button"
            onClick={() => onNavigate('queue')}
            className="font-mono text-xs text-muted-foreground hover:text-foreground"
          >
            {queueText}
          </button>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
