import { describe, expect, it } from 'vitest'

import type { ClaudeJob, ClaudeJobPrompt } from '@/lib/types'

import { analysisLines } from './AnalysisTerminal'

function prompt(overrides: Partial<ClaudeJobPrompt>): ClaudeJobPrompt {
  return {
    position: 0,
    prompt_kind: 'fact_sheet',
    status: 'queued',
    error: null,
    cost_usd: null,
    duration_ms: null,
    model: null,
    started_at: null,
    finished_at: null,
    skipped: false,
    ...overrides,
  }
}

function job(status: string, prompts: ClaudeJobPrompt[]): ClaudeJob {
  return {
    id: 1,
    label: 'Profile analysis',
    kind: 'profile_analysis',
    job_application_id: null,
    status,
    error: null,
    created_at: '2026-10-06T09:00:00Z',
    updated_at: '2026-10-06T09:00:00Z',
    prompts,
  }
}

describe('analysisLines', () => {
  it('reports a finished prompt with its model, time and cost', () => {
    const lines = analysisLines(
      job('running', [
        prompt({
          prompt_kind: 'full_cv_history',
          status: 'done',
          model: 'claude-sonnet-5',
          started_at: '2026-10-06T09:00:01Z',
          finished_at: '2026-10-06T09:00:14Z',
          duration_ms: 13200,
          cost_usd: 0.0123,
        }),
      ]),
    )
    const texts = lines.map((line) => line.text)
    expect(texts).toContain('Career history: started (claude-sonnet-5)')
    expect(texts).toContain('Career history: done in 13.2 s, $0.0123')
  })

  it('says when a prompt was skipped because it is already in place', () => {
    const lines = analysisLines(job('done', [prompt({ prompt_kind: 'strategy', skipped: true })]))
    expect(lines.map((line) => line.text)).toContain('Strategy: already in place, skipped')
  })

  it('shows a failure with its reason', () => {
    const lines = analysisLines(
      job('failed', [prompt({ status: 'failed', error: 'The answer was not JSON.' })]),
    )
    expect(lines.some((line) => line.tone === 'error' && line.text.includes('not JSON'))).toBe(true)
  })
})
