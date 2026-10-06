import { BriefcaseBusiness, GitBranch, Plus, Settings, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type Screen = 'jobs' | 'profile'

// Jobs and Profile have screens. The other entries are placeholders for later phases.
const NAV: { label: string; icon: typeof UserRound; screen: Screen | null }[] = [
  { label: 'Jobs', icon: BriefcaseBusiness, screen: 'jobs' },
  { label: 'Profile', icon: UserRound, screen: 'profile' },
  { label: 'Settings', icon: Settings, screen: null },
  { label: 'Run Trace', icon: GitBranch, screen: null },
]

type Props = {
  children: ReactNode
  current: Screen
  onNavigate: (screen: Screen) => void
}

export function AppShell({ children, current, onNavigate }: Props) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="text-sm font-semibold tracking-tight">LocalJobTracker</span>
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
        <header className="sticky top-0 z-30 flex h-14 items-center justify-end border-b border-border bg-card/90 px-6 backdrop-blur">
          <Button disabled title="Adding jobs comes in Phase 4">
            <Plus className="size-4" aria-hidden="true" />
            Add Job
          </Button>
        </header>
        <main className="p-6">{children}</main>
      </div>
    </div>
  )
}
