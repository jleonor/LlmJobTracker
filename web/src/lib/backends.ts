// Shared backend display constants (D-195/D-206). Originally private to SettingsPage.tsx; moved
// here once the Dashboard's rescore sections (D-237) needed the same backend/model label a
// confirm dialog already shows on Settings, rather than a second copy.
import type { Backend } from '@/lib/types'

export const BACKEND_LABELS: Record<Backend, string> = { claude_code: 'Claude Code', codex: 'Codex' }

export const BACKENDS: Backend[] = ['claude_code', 'codex']

// Which Settings field holds each provider's selected model.
export const MODEL_FIELD: Record<Backend, 'claude_code_model' | 'codex_model'> = {
  claude_code: 'claude_code_model',
  codex: 'codex_model',
}
