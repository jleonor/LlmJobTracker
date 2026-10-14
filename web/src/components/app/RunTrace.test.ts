import { describe, expect, it } from 'vitest'

import type { ClaudeJob, ClaudeJobPrompt } from '@/lib/types'

import { splitPromptBlocks, traceLines } from './RunTrace'

function prompt(overrides: Partial<ClaudeJobPrompt>): ClaudeJobPrompt {
  return {
    position: 0,
    prompt_kind: 'questionnaire_analysis',
    status: 'queued',
    error: null,
    cost_usd: null,
    duration_ms: null,
    model: null,
    input_tokens: null,
    output_tokens: null,
    started_at: null,
    finished_at: null,
    skipped: false,
    skip_reason: null,
    answer_chars: null,
    live_text: null,
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
    resume_at: null,
    retry_attempts: 0,
    prompts,
  }
}

describe('traceLines', () => {
  it('reports a finished prompt with its model, time and cost', () => {
    const lines = traceLines(
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

  it('reports tokens when the runner supplied them but no cost (D-197)', () => {
    const lines = traceLines(
      job('running', [
        prompt({
          prompt_kind: 'full_cv_history',
          status: 'done',
          model: 'gpt-5-codex',
          finished_at: '2026-10-06T09:00:14Z',
          cost_usd: null,
          input_tokens: 610,
          output_tokens: 5,
        }),
      ]),
    )
    const texts = lines.map((line) => line.text)
    expect(texts).toContain('Career history: done, 610 in / 5 out tokens')
  })

  it('says when a prompt was skipped because it is already in place', () => {
    const lines = traceLines(
      job('done', [
        prompt({
          prompt_kind: 'strategy',
          skipped: true,
          skip_reason: 'Skipped: already in place.',
        }),
      ]),
    )
    expect(lines.map((line) => line.text)).toContain('Strategy: already in place.')
  })

  it('shows the real reason when a prompt was skipped for using the own file', () => {
    const lines = traceLines(
      job('done', [
        prompt({
          prompt_kind: 'questionnaire_analysis',
          skipped: true,
          skip_reason: 'Skipped: using your own file.',
        }),
      ]),
    )
    expect(lines.map((line) => line.text)).toContain('Questionnaire report: using your own file.')
  })

  it('shows a failure with its reason', () => {
    const lines = traceLines(
      job('failed', [prompt({ status: 'failed', error: 'The answer was not JSON.' })]),
    )
    expect(lines.some((line) => line.tone === 'error' && line.text.includes('not JSON'))).toBe(true)
  })

  it('shows how long a prompt has been running', () => {
    const lines = traceLines(
      job('processing', [
        prompt({ prompt_kind: 'full_cv_history', status: 'running', started_at: '2026-10-06T09:00:00Z' }),
      ]),
      Date.parse('2026-10-06T09:03:05Z'),
    )
    expect(lines.map((line) => line.text)).toContain('Career history: still running, 3:05 so far')
  })

  it('labels a revise prompt by the document it is about', () => {
    const lines = traceLines(
      job('processing', [
        prompt({
          prompt_kind: 'revise_own_full_cv_history',
          status: 'done',
          finished_at: '2026-10-06T09:00:14Z',
        }),
      ]),
    )
    expect(lines.map((line) => line.text)).toContain('Career history: done')
  })

  it('shows the elapsed time only until text starts streaming in', () => {
    const lines = traceLines(
      job('processing', [
        prompt({
          prompt_kind: 'full_cv_history',
          status: 'running',
          started_at: '2026-10-06T09:00:00Z',
          live_text: 'Some text so far',
        }),
      ]),
      Date.parse('2026-10-06T09:03:05Z'),
    )
    expect(lines.map((line) => line.text)).not.toContain('Career history: still running, 3:05 so far')
  })
})

describe('splitPromptBlocks', () => {
  it('pulls a file block out of the surrounding instructions', () => {
    const text =
      'Use only the files below.\n\n' +
      '=== FILE 1 | master_cv | cv.pdf ===\nAlex Sample\nAnalyst\n=== END FILE 1 ===\n\n' +
      'Write the history now.'
    const segments = splitPromptBlocks(text)
    expect(segments).toEqual([
      { kind: 'text', text: 'Use only the files below.\n\n' },
      { kind: 'block', header: 'FILE 1 | master_cv | cv.pdf', body: 'Alex Sample\nAnalyst' },
      { kind: 'text', text: '\nWrite the history now.' },
    ])
  })

  it('pulls out a document block the same way', () => {
    const text = '=== CAREER HISTORY ===\n# History\n\nSome text.\n=== END CAREER HISTORY ===\n'
    const segments = splitPromptBlocks(text)
    expect(segments).toEqual([
      { kind: 'block', header: 'CAREER HISTORY', body: '# History\n\nSome text.' },
    ])
  })

  it('returns one text segment when there are no blocks', () => {
    expect(splitPromptBlocks('Just plain instructions.')).toEqual([
      { kind: 'text', text: 'Just plain instructions.' },
    ])
  })
})

describe('answer received', () => {
  it('logs the answer before its check result', () => {
    const lines = traceLines(
      job('failed', [
        prompt({
          prompt_kind: 'full_cv_history',
          status: 'failed',
          error: 'history H-014: date must be YYYY.',
          answer_chars: 4213,
          finished_at: '2026-10-06T09:02:00Z',
        }),
      ]),
    )
    const texts = lines.map((line) => line.text)
    const expected = `Career history: answer received, ${(4213).toLocaleString()} characters`
    const answer = texts.findIndex((text) => text === expected)
    const failure = texts.findIndex((text) => text.startsWith('Career history: failed.'))
    expect(answer).toBeGreaterThan(-1)
    expect(answer).toBeLessThan(failure)
  })
})
