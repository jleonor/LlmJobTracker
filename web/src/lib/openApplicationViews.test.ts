import { describe, expect, it } from 'vitest'

import { applicationMatchesFilters } from '@/components/app/OpenApplicationsTableFilters'
import { OPEN_APPLICATION_VIEWS } from '@/lib/openApplicationViews'
import type { OpenApplication } from '@/lib/types'

function application(overrides: Partial<OpenApplication> = {}): OpenApplication {
  return {
    id: 1,
    target_name: 'Acme Talent Pool',
    target_type: 'talent_pool',
    industry: null,
    company_type: null,
    contact_name: null,
    status: 'Identified',
    last_updated: '2026-10-01T09:00:00Z',
    next_action: null,
    due_date: null,
    notes: null,
    status_history: [],
    has_sources: false,
    has_company_details: true,
    has_tailored_cv: false,
    has_cover_letter: false,
    has_introduction_message: false,
    ...overrides,
  }
}

const now = new Date('2026-10-31T00:00:00Z')

function viewFilters(id: string) {
  const view = OPEN_APPLICATION_VIEWS.find((candidate) => candidate.id === id)
  if (!view) throw new Error(`No such view: ${id}`)
  return typeof view.filters === 'function' ? view.filters(now) : view.filters
}

describe('active_applications view (D-298, mirrors D-275)', () => {
  it('matches Applied touched within 30 days', () => {
    const filters = viewFilters('active_applications')
    const app = application({ status: 'Applied', last_updated: '2026-10-20T00:00:00Z' })
    expect(applicationMatchesFilters(app, filters)).toBe(true)
  })

  it('rejects Applied untouched for more than 30 days', () => {
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

describe('cold_applications view (D-298)', () => {
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

describe('to_apply_to view (D-298)', () => {
  it('matches Identified, with no Match score to sort by', () => {
    const view = OPEN_APPLICATION_VIEWS.find((candidate) => candidate.id === 'to_apply_to')
    expect(view?.sort).toEqual({ column: 'last_updated', direction: 'desc' })
    const app = application({ status: 'Identified' })
    expect(applicationMatchesFilters(app, viewFilters('to_apply_to'))).toBe(true)
  })
})

describe('dead_applications view (D-298)', () => {
  it('matches every dead end state', () => {
    const filters = viewFilters('dead_applications')
    for (const status of ['Rejected', 'Withdrawn', 'Expired']) {
      expect(applicationMatchesFilters(application({ status }), filters)).toBe(true)
    }
    expect(applicationMatchesFilters(application({ status: 'Applied' }), filters)).toBe(false)
  })
})

describe('upcoming_actions view (D-298)', () => {
  it('matches Applied with a next action date set', () => {
    const filters = viewFilters('upcoming_actions')
    const app = application({ status: 'Applied', due_date: '2026-11-10' })
    expect(applicationMatchesFilters(app, filters)).toBe(true)
  })

  it('rejects Applied with no next action date', () => {
    const filters = viewFilters('upcoming_actions')
    const app = application({ status: 'Applied', due_date: null })
    expect(applicationMatchesFilters(app, filters)).toBe(false)
  })
})
