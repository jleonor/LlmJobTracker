import { BriefcaseBusiness, GitBranch, Plus, Settings, UserRound } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// Only Jobs has a screen in Phase 1. The other entries are placeholders for later phases.
const NAV = [
  { label: 'Jobs', icon: BriefcaseBusiness, active: true },
  { label: 'Profile', icon: UserRound, active: false },
  { label: 'Settings', icon: Settings, active: false },
  { label: 'Run Trace', icon: GitBranch, active: false },
]

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="text-sm font-semibold tracking-tight">LocalJobTracker</span>
        </div>
        <nav className="flex flex-col gap-0.5 p-2" aria-label="Main">
          {NAV.map(({ label, icon: Icon, active }) => (
            <button
              key={label}
              type="button"
              disabled={!active}
              aria-current={active ? 'page' : undefined}
              title={active ? undefined : 'Not in this phase yet'}
              className={cn(
                'flex items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors',
                active
                  ? 'border-l-2 border-primary bg-secondary pl-[10px] font-semibold text-foreground'
                  : 'cursor-not-allowed text-muted-foreground opacity-60',
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </button>
          ))}
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
