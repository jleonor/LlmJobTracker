import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { ApiError, runLlmCheck } from '@/lib/api'
import type { RunResult } from '@/lib/types'

type State =
  | { kind: 'idle' }
  | { kind: 'running' }
  | { kind: 'done'; result: RunResult }
  | { kind: 'error'; message: string }

// Sends one real request through whichever backend and model are currently selected (D-195,
// D-206) and shows the answer - the same one the next queued job would actually use.
export function LlmCheck() {
  const [state, setState] = useState<State>({ kind: 'idle' })

  async function handleClick() {
    setState({ kind: 'running' })
    try {
      const result = await runLlmCheck()
      setState({ kind: 'done', result })
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'The check failed.'
      setState({ kind: 'error', message })
    }
  }

  return (
    <section aria-labelledby="runner-heading" className="flex flex-col gap-3 rounded border border-border bg-card p-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="runner-heading" className="text-sm font-semibold">
            LLM check
          </h2>
          <p className="text-xs text-muted-foreground">
            Sends one request through the currently selected backend and model, and shows the
            reply. Uses your login for that backend.
          </p>
        </div>
        <Button onClick={handleClick} disabled={state.kind === 'running'}>
          {state.kind === 'running' ? 'Running...' : 'Run check'}
        </Button>
      </div>

      {state.kind === 'done' && state.result.ok && (
        <div className="flex flex-col gap-1 rounded border border-border bg-background p-3">
          <p className="font-mono text-sm" data-testid="runner-reply">
            {state.result.text}
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            {state.result.model && `${state.result.model} · `}
            {(state.result.duration_ms / 1000).toFixed(1)} s
            {state.result.cost_usd !== null &&
              ` · estimated cost $${state.result.cost_usd.toFixed(4)}`}
          </p>
        </div>
      )}

      {state.kind === 'done' && !state.result.ok && (
        <p role="alert" className="text-sm text-destructive">
          {state.result.error}
        </p>
      )}

      {state.kind === 'error' && (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      )}
    </section>
  )
}
