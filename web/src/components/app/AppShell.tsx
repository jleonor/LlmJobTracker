import { BriefcaseBusiness, LayoutDashboard, ListOrdered, Settings, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'

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
}

export function AppShell({ children, current, onNavigate, queueText, userName }: Props) {
  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* The full-width top bar: title/logo left, LLM status right - no more boxed-in sidebar
          header cell (D-278). app-drag-region/app-no-drag (index.css) make this strip the
          Electron window's own draggable title bar, under the Windows titleBarOverlay
          (electron/main.js) - harmless, inert properties outside Electron. */}
      <header className="app-drag-region flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4">
        <div className="flex min-w-0 items-center gap-2">
          <img src="/logo-white.svg" alt="" className="size-6 shrink-0" aria-hidden="true" />
          <span className="truncate text-lg font-semibold tracking-tight">{userName}'s Job Tracker</span>
        </div>
        <button
          type="button"
          onClick={() => onNavigate('queue')}
          className="app-no-drag shrink-0 font-mono text-xs text-muted-foreground hover:text-foreground"
        >
          {queueText}
        </button>
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
