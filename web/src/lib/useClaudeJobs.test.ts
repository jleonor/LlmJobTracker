import { describe, expect, it } from 'vitest'

import type { ClaudeJob } from './types'
import { queueLabel } from './useClaudeJobs'

function job(id: number, status: string): ClaudeJob {
  return {
    id,
    label: `job ${id}`,
    kind: 'profile_analysis',
    job_application_id: null,
    status,
    error: null,
    created_at: '2026-10-06T09:00:00Z',
    updated_at: '2026-10-06T09:00:00Z',
    resume_at: null,
    prompts: [],
  }
}

describe('queueLabel', () => {
  it('reads idle when nothing is waiting', () => {
    expect(queueLabel([])).toBe('LLM: idle')
    expect(queueLabel([job(1, 'done')])).toBe('LLM: idle')
  })

  it('counts queued jobs', () => {
    expect(queueLabel([job(1, 'queued'), job(2, 'queued')])).toBe('LLM: 2 queued')
  })

  it('shows a paused queue as paused, and a running job above both', () => {
    expect(queueLabel([job(1, 'queued'), job(2, 'paused')])).toBe('LLM: paused')
    expect(queueLabel([job(1, 'paused'), job(2, 'processing')])).toBe('LLM: processing')
  })
})
