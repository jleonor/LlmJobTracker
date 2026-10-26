import { describe, expect, it } from 'vitest'

import { applicationMatchesFilters } from '@/components/app/JobsTableFilters'
import { JOB_VIEWS } from '@/lib/jobViews'
import type { JobApplication } from '@/lib/types'

function application(overrides: Partial<JobApplication> = {}): JobApplication {
  return {
    id: 1,
    company: 'Acme Inc',
    role_title: 'Analyst',
    lane: null,
    location: null,
    status: 'Identified',
    last_updated: '2026-10-01T09:00:00Z',
    match_score: null,
    portal_name: null,
    portal_url: null,
    work_mode: 'Unknown',
    contract_type: 'Unknown',
    notes: null,
    next_action: null,
    due_date: null,
    status_history: [],
    has_listing: true,
    has_details: false,
    has_analysis: false,
    has_tailored_cv: false,
    has_cover_letter: false,
    has_interview_prep: false,
    ...overrides,
  }
}

const now = new Date('2026-10-31T00:00:00Z')

function viewFilters(id: string) {
  const view = JOB_VIEWS.find((candidate) => candidate.id === id)
  if (!view) throw new Error(`No such view: ${id}`)
  return typeof view.filters === 'function' ? view.filters(now) : view.filters
}

describe('active_applications view (D-275)', () => {
  it('matches an in-progress status touched within 30 days', () => {
    const filters = viewFilters('active_applications')
    const app = application({ status: 'Applied', last_updated: '2026-10-20T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(true)
  })

  it('rejects an in-progress status untouched for more than 30 days', () => {
    const filters = viewFilters('active_applications')
    const app = application({ status: 'Applied', last_updated: '2026-09-01T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(false)
  })

  it('rejects Identified even if recently touched', () => {
    const filters = viewFilters('active_applications')
    const app = application({ status: 'Identified', last_updated: '2026-10-30T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(false)
  })
})

describe('cold_applications view (D-275)', () => {
  it('matches Identified untouched for more than 30 days', () => {
    const filters = viewFilters('cold_applications')
    const app = application({ status: 'Identified', last_updated: '2026-09-01T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(true)
  })

  it('rejects a dead end state, however stale', () => {
    const filters = viewFilters('cold_applications')
    const app = application({ status: 'Rejected', last_updated: '2026-01-01T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(false)
  })

  it('rejects a recently-touched non-dead application', () => {
    const filters = viewFilters('cold_applications')
    const app = application({ status: 'Applied', last_updated: '2026-10-25T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(false)
  })
})
