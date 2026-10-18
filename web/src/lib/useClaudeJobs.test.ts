import { describe, expect, it } from 'vitest'

import type { ClaudeJob } from './types'
import { queueLabel, queueStatusFor } from './useClaudeJobs'

function job(id: number, status: string, jobApplicationId: number | null = null): ClaudeJob {
  return {
    id,
    label: `job ${id}`,
    kind: 'profile_analysis',
    job_application_id: jobApplicationId,
    status,
    error: null,
    created_at: '2026-10-06T09:00:00Z',
    updated_at: '2026-10-06T09:00:00Z',
    resume_at: null,
    retry_attempts: 0,
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

describe('queueStatusFor', () => {
  it('reads idle with no jobs of its own', () => {
    expect(queueStatusFor([job(1, 'processing', 2)], 1)).toBe('idle')
  })

  it('reads done and cancelled jobs as idle', () => {
    expect(queueStatusFor([job(1, 'done', 1)], 1)).toBe('idle')
    expect(queueStatusFor([job(1, 'cancelled', 1)], 1)).toBe('idle')
  })

  it('surfaces a failed job (D-227) rather than reading it as idle', () => {
    expect(queueStatusFor([job(1, 'failed', 1)], 1)).toBe('failed')
  })

  it('ranks processing above paused above queued above failed', () => {
    expect(queueStatusFor([job(1, 'queued', 1), job(2, 'failed', 1)], 1)).toBe('queued')
    expect(queueStatusFor([job(1, 'paused', 1), job(2, 'queued', 1)], 1)).toBe('paused')
    expect(queueStatusFor([job(1, 'processing', 1), job(2, 'paused', 1)], 1)).toBe('processing')
  })
})
