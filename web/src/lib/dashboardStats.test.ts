import { describe, expect, it } from 'vitest'

import type { JobApplication, OpenApplication } from '@/lib/types'
import {
  applicationsSentHeatmap,
  applySlicers,
  applyStageSlicer,
  averageDaysIdentifiedToApplied,
  averageMatchScoreForLane,
  combinedApplicationsSentHeatmap,
  combinedProportionByStage,
  combinedTotals,
  combinedWholeHistoryRates,
  distinctLanes,
  distinctLocations,
  earliestIdentifiedDate,
  foldToOther,
  hasBeenApplied,
  isActiveApplication,
  isColdApplication,
  matchScoreBucket,
  proportionByLane,
  proportionByMatchScoreBucket,
  proportionByStage,
  snapshotAsOf,
  wholeHistoryRates,
} from './dashboardStats'

function openApplication(overrides: Partial<OpenApplication> = {}): OpenApplication {
  return {
    id: 1,
    target_name: 'Acme Talent Pool',
    target_type: 'talent_pool',
    status: 'Identified',
    last_updated: '2026-10-01T09:00:00Z',
    status_history: [],
    has_company_details: true,
    has_tailored_cv: false,
    has_cover_letter: false,
    has_introduction_message: false,
    ...overrides,
  }
}

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

describe('matchScoreBucket', () => {
  it('buckets a null score as "Not scored"', () => {
    expect(matchScoreBucket(null)).toBe('Not scored')
  })

  it('buckets a score into its 10%-wide band', () => {
    expect(matchScoreBucket(0)).toBe('0-10%')
    expect(matchScoreBucket(45)).toBe('40-50%')
    expect(matchScoreBucket(100)).toBe('90-100%')
  })
})

describe('applySlicers', () => {
  const applications = [
    application({ id: 1, lane: 'Data Analytics', status: 'Identified', match_score: 42, location: 'Remote' }),
    application({ id: 2, lane: 'Product Analytics', status: 'Applied', match_score: null, location: 'Montreal' }),
  ]

  it('filters by lane', () => {
    const result = applySlicers(applications, {
      lane: 'Data Analytics',
      stage: null,
      matchScoreBucket: null,
      location: null,
    })
    expect(result.map((a) => a.id)).toEqual([1])
  })

  it('filters by stage', () => {
    const result = applySlicers(applications, {
      lane: null,
      stage: 'Applied',
      matchScoreBucket: null,
      location: null,
    })
    expect(result.map((a) => a.id)).toEqual([2])
  })

  it('filters by the "Not scored" match-score bucket', () => {
    const result = applySlicers(applications, {
      lane: null,
      stage: null,
      matchScoreBucket: 'Not scored',
      location: null,
    })
    expect(result.map((a) => a.id)).toEqual([2])
  })

  it('filters by location', () => {
    const result = applySlicers(applications, {
      lane: null,
      stage: null,
      matchScoreBucket: null,
      location: 'Montreal',
    })
    expect(result.map((a) => a.id)).toEqual([2])
  })

  it('combines every slicer at once', () => {
    const result = applySlicers(applications, {
      lane: 'Data Analytics',
      stage: 'Identified',
      matchScoreBucket: '40-50%',
      location: 'Remote',
    })
    expect(result.map((a) => a.id)).toEqual([1])
  })
})

describe('distinctLanes and distinctLocations', () => {
  it('report a "No lane"/"No location" entry for a null value, each once', () => {
    const applications = [
      application({ lane: 'Data Analytics', location: 'Remote' }),
      application({ lane: null, location: null }),
      application({ lane: 'Data Analytics', location: null }),
    ]
    expect(distinctLanes(applications)).toEqual(['Data Analytics', 'No lane'])
    expect(distinctLocations(applications)).toEqual(['No location', 'Remote'])
  })
})

describe('proportionByLane/Stage/MatchScoreBucket', () => {
  const applications = [
    application({ lane: 'Data Analytics', status: 'Identified', match_score: 85 }),
    application({ lane: 'Data Analytics', status: 'Applied', match_score: 15 }),
    application({ lane: null, status: 'Applied', match_score: null }),
  ]

  it('counts by lane, with no-lane applications grouped together', () => {
    expect(proportionByLane(applications)).toEqual([
      { label: 'Data Analytics', count: 2 },
      { label: 'No lane', count: 1 },
    ])
  })

  it('counts by stage, in the defined stage order, skipping stages with no applications', () => {
    expect(proportionByStage(applications)).toEqual([
      { label: 'Identified', count: 1 },
      { label: 'Applied', count: 2 },
    ])
  })

  it('counts by match-score bucket, in bucket order including "Not scored"', () => {
    expect(proportionByMatchScoreBucket(applications)).toEqual([
      { label: 'Not scored', count: 1 },
      { label: '10-20%', count: 1 },
      { label: '80-90%', count: 1 },
    ])
  })
})

describe('foldToOther', () => {
  it('leaves the list untouched when it is already at or under the cap', () => {
    const entries = [{ label: 'A', count: 3 }, { label: 'B', count: 1 }]
    expect(foldToOther(entries, 2, 'Other lanes')).toEqual(entries)
  })

  it('keeps the largest entries and folds the rest into one entry under the given label', () => {
    const entries = [
      { label: 'A', count: 5 },
      { label: 'B', count: 4 },
      { label: 'C', count: 3 },
      { label: 'D', count: 2 },
    ]
    expect(foldToOther(entries, 2, 'Other lanes')).toEqual([
      { label: 'A', count: 5 },
      { label: 'B', count: 4 },
      { label: 'Other lanes', count: 5 },
    ])
  })

  it('does not collide with a real entry that happens to be named "Other"', () => {
    // The lanes catalog has its own fixed "Other" catch-all lane (D-219) - if it ranks in the
    // kept set while other lanes overflow, the fold bucket must read as a distinct thing, not a
    // second row with the same label.
    const entries = [
      { label: 'Data Analytics', count: 5 },
      { label: 'Other', count: 4 },
      { label: 'Product Analytics', count: 3 },
      { label: 'Platform Engineering', count: 2 },
    ]
    const folded = foldToOther(entries, 2, 'Other lanes')
    expect(folded).toEqual([
      { label: 'Data Analytics', count: 5 },
      { label: 'Other', count: 4 },
      { label: 'Other lanes', count: 5 },
    ])
    const labels = folded.map((entry) => entry.label)
    expect(new Set(labels).size).toBe(labels.length) // every label is unique
  })
})

describe('averageMatchScoreForLane', () => {
  it('averages only that lane\'s own scored applications', () => {
    const applications = [
      application({ lane: 'Data Analytics', match_score: 80 }),
      application({ lane: 'Data Analytics', match_score: 60 }),
      application({ lane: 'Data Analytics', match_score: null }),
      application({ lane: 'Product Analytics', match_score: 10 }),
    ]
    expect(averageMatchScoreForLane(applications, 'Data Analytics')).toBe(70)
  })

  it('returns null when the lane has no scored application', () => {
    const applications = [application({ lane: 'Data Analytics', match_score: null })]
    expect(averageMatchScoreForLane(applications, 'Data Analytics')).toBeNull()
  })
})

describe('averageDaysIdentifiedToApplied', () => {
  it('averages only applications with both an Identified and a later Applied date', () => {
    const applications = [
      application({
        status_history: [
          { status: 'Identified', changed_at: '2026-09-01T00:00:00Z' },
          { status: 'Applied', changed_at: '2026-09-05T00:00:00Z' },
        ],
      }),
      application({
        status_history: [{ status: 'Identified', changed_at: '2026-09-10T00:00:00Z' }],
      }),
    ]
    expect(averageDaysIdentifiedToApplied(applications)).toBe(4)
  })

  it('returns null when no application has both dates', () => {
    const applications = [
      application({ status_history: [{ status: 'Identified', changed_at: '2026-09-01T00:00:00Z' }] }),
    ]
    expect(averageDaysIdentifiedToApplied(applications)).toBeNull()
  })
})

describe('wholeHistoryRates', () => {
  it('divides each status count by the days/weeks since the earliest tracked entry', () => {
    const applications = [
      application({
        status_history: [
          { status: 'Identified', changed_at: '2026-09-01T00:00:00Z' },
          { status: 'Applied', changed_at: '2026-09-06T00:00:00Z' },
        ],
      }),
      application({
        status_history: [{ status: 'Identified', changed_at: '2026-09-05T00:00:00Z' }],
      }),
    ]
    const now = new Date('2026-09-11T00:00:00Z') // 10 days after the earliest entry
    const rates = wholeHistoryRates(applications, now)
    expect(rates).not.toBeNull()
    expect(rates?.identifiedPerDay).toBeCloseTo(2 / 10)
    expect(rates?.appliedPerDay).toBeCloseTo(1 / 10)
    expect(rates?.identifiedPerWeek).toBeCloseTo(2 / (10 / 7))
  })

  it('returns null with no status history anywhere', () => {
    expect(wholeHistoryRates([application()])).toBeNull()
  })
})

describe('applicationsSentHeatmap', () => {
  it('spans exactly 365 trailing days and counts Applied entries on their own day', () => {
    const today = new Date('2026-10-18T00:00:00Z')
    const applications = [
      application({
        status_history: [
          { status: 'Applied', changed_at: '2026-10-18T09:00:00Z' },
          { status: 'Applied', changed_at: '2026-10-18T14:00:00Z' },
          { status: 'Identified', changed_at: '2026-10-17T09:00:00Z' },
        ],
      }),
    ]
    const heatmap = applicationsSentHeatmap(applications, today)
    expect(heatmap).toHaveLength(365)
    expect(heatmap[heatmap.length - 1]).toEqual({ date: '2026-10-18', count: 2 })
    expect(heatmap[heatmap.length - 2]).toEqual({ date: '2026-10-17', count: 0 }) // Identified, not Applied
  })
})

describe('combinedProportionByStage', () => {
  it('folds Open Applications into the same stage bars as Job Applications', () => {
    const jobApplications = [application({ status: 'Identified' }), application({ status: 'Applied' })]
    const openApplications = [openApplication({ status: 'Applied' }), openApplication({ status: 'Expired' })]
    const result = combinedProportionByStage(jobApplications, openApplications)
    expect(result).toEqual([
      { label: 'Identified', count: 1 },
      { label: 'Applied', count: 2 },
      { label: 'Expired', count: 1 },
    ])
  })
})

describe('applyStageSlicer', () => {
  it('filters Open Applications by status only (no lane/match-score dimension exists)', () => {
    const openApplications = [openApplication({ id: 1, status: 'Identified' }), openApplication({ id: 2, status: 'Applied' })]
    expect(applyStageSlicer(openApplications, 'Applied')).toEqual([openApplications[1]])
    expect(applyStageSlicer(openApplications, null)).toEqual(openApplications)
  })
})

describe('combinedTotals', () => {
  it('counts both entity types and splits Alive/Dead by the shared end-state set', () => {
    const jobApplications = [
      application({ status: 'Identified' }),
      application({ status: 'Rejected' }),
    ]
    const openApplications = [
      openApplication({ status: 'Applied' }),
      openApplication({ status: 'Expired' }),
    ]
    const totals = combinedTotals(jobApplications, openApplications)
    expect(totals).toEqual({
      totalJobApplications: 2,
      totalOpenApplications: 2,
      total: 4,
      alive: 2,
      dead: 2,
    })
  })
})

describe('combinedWholeHistoryRates', () => {
  it('merges Identified/Applied events from both entity types', () => {
    const now = new Date('2026-10-11T00:00:00Z')
    const jobApplications = [
      application({ status_history: [{ status: 'Identified', changed_at: '2026-10-01T00:00:00Z' }] }),
    ]
    const openApplications = [
      openApplication({ status_history: [{ status: 'Applied', changed_at: '2026-10-05T00:00:00Z' }] }),
    ]
    const rates = combinedWholeHistoryRates(jobApplications, openApplications, now)
    expect(rates).not.toBeNull()
    expect(rates?.identifiedPerDay).toBeCloseTo(1 / 10)
    expect(rates?.appliedPerDay).toBeCloseTo(1 / 10)
  })

  it('is null when neither list has any status history', () => {
    expect(combinedWholeHistoryRates([], [])).toBeNull()
  })
})

describe('combinedApplicationsSentHeatmap', () => {
  it('counts Applied entries from both entity types on the same day', () => {
    const today = new Date('2026-10-18T00:00:00Z')
    const jobApplications = [
      application({ status_history: [{ status: 'Applied', changed_at: '2026-10-18T09:00:00Z' }] }),
    ]
    const openApplications = [
      openApplication({ status_history: [{ status: 'Applied', changed_at: '2026-10-18T14:00:00Z' }] }),
    ]
    const heatmap = combinedApplicationsSentHeatmap(jobApplications, openApplications, today)
    expect(heatmap[heatmap.length - 1]).toEqual({ date: '2026-10-18', count: 2 })
  })
})

describe('earliestIdentifiedDate', () => {
  it('is null when nothing has ever been Identified', () => {
    expect(earliestIdentifiedDate([application({ status_history: [] })])).toBeNull()
  })

  it('is the earliest Identified entry across every application', () => {
    const applications = [
      application({
        id: 1,
        status_history: [{ status: 'Identified', changed_at: '2026-09-15T00:00:00Z' }],
      }),
      application({
        id: 2,
        status_history: [{ status: 'Identified', changed_at: '2026-08-01T00:00:00Z' }],
      }),
    ]
    expect(earliestIdentifiedDate(applications)).toBe('2026-08-01T00:00:00Z')
  })
})

describe('snapshotAsOf', () => {
  it('drops an application not yet Identified by the given date', () => {
    const applications = [
      application({ status_history: [{ status: 'Identified', changed_at: '2026-10-15T00:00:00Z' }] }),
    ]
    expect(snapshotAsOf(applications, '2026-10-10')).toEqual([])
  })

  it('keeps an application Identified by the given date, with its status as of then', () => {
    const applications = [
      application({
        id: 1,
        status: 'Interview',
        last_updated: '2026-10-20T00:00:00Z',
        status_history: [
          { status: 'Identified', changed_at: '2026-10-01T00:00:00Z' },
          { status: 'Applied', changed_at: '2026-10-05T00:00:00Z' },
          { status: 'Screening', changed_at: '2026-10-12T00:00:00Z' },
          { status: 'Interview', changed_at: '2026-10-20T00:00:00Z' },
        ],
      }),
    ]

    const snapshot = snapshotAsOf(applications, '2026-10-10')

    expect(snapshot).toHaveLength(1)
    expect(snapshot[0].status).toBe('Applied')
    expect(snapshot[0].last_updated).toBe('2026-10-05T00:00:00Z')
  })

  it('truncates status_history itself, not just the summary fields', () => {
    const applications = [
      application({
        status_history: [
          { status: 'Identified', changed_at: '2026-10-01T00:00:00Z' },
          { status: 'Applied', changed_at: '2026-10-05T00:00:00Z' },
          { status: 'Screening', changed_at: '2026-10-20T00:00:00Z' },
        ],
      }),
    ]

    const snapshot = snapshotAsOf(applications, '2026-10-10')

    expect(snapshot[0].status_history).toEqual([
      { status: 'Identified', changed_at: '2026-10-01T00:00:00Z' },
      { status: 'Applied', changed_at: '2026-10-05T00:00:00Z' },
    ])
  })

  it('works the same way for Open Applications', () => {
    const applications = [
      openApplication({
        status_history: [{ status: 'Identified', changed_at: '2026-10-01T00:00:00Z' }],
      }),
    ]
    const snapshot = snapshotAsOf(applications, '2026-10-01')
    expect(snapshot).toHaveLength(1)
    expect(snapshot[0].status).toBe('Identified')
  })

  it('on the exact as-of day, keeps that day\'s own status change', () => {
    const applications = [
      application({
        status_history: [
          { status: 'Identified', changed_at: '2026-10-01T00:00:00Z' },
          { status: 'Applied', changed_at: '2026-10-10T23:00:00Z' },
        ],
      }),
    ]
    const snapshot = snapshotAsOf(applications, '2026-10-10')
    expect(snapshot[0].status).toBe('Applied')
  })
})

describe('isActiveApplication', () => {
  const now = new Date('2026-10-26T00:00:00Z')

  it('is true for an in-progress status updated within 30 days', () => {
    expect(isActiveApplication(application({ status: 'Applied', last_updated: '2026-10-10T00:00:00Z' }), now)).toBe(
      true,
    )
  })

  it('is false once untouched for more than 30 days', () => {
    expect(isActiveApplication(application({ status: 'Applied', last_updated: '2026-09-01T00:00:00Z' }), now)).toBe(
      false,
    )
  })

  it('is false for Identified, even if recently touched', () => {
    expect(
      isActiveApplication(application({ status: 'Identified', last_updated: '2026-10-25T00:00:00Z' }), now),
    ).toBe(false)
  })

  it('is false for a dead end state', () => {
    expect(isActiveApplication(application({ status: 'Rejected', last_updated: '2026-10-25T00:00:00Z' }), now)).toBe(
      false,
    )
  })
})

describe('isColdApplication', () => {
  const now = new Date('2026-10-26T00:00:00Z')

  it('is true for a non-dead status untouched for more than 30 days, Identified included', () => {
    expect(isColdApplication(application({ status: 'Identified', last_updated: '2026-09-01T00:00:00Z' }), now)).toBe(
      true,
    )
    expect(isColdApplication(application({ status: 'Applied', last_updated: '2026-09-01T00:00:00Z' }), now)).toBe(
      true,
    )
  })

  it('is false when recently touched', () => {
    expect(isColdApplication(application({ status: 'Applied', last_updated: '2026-10-10T00:00:00Z' }), now)).toBe(
      false,
    )
  })

  it('is false for a dead end state, however stale', () => {
    expect(isColdApplication(application({ status: 'Expired', last_updated: '2026-01-01T00:00:00Z' }), now)).toBe(
      false,
    )
  })
})

describe('hasBeenApplied', () => {
  it('is true once an Applied entry exists', () => {
    expect(
      hasBeenApplied(
        application({ status_history: [{ status: 'Applied', changed_at: '2026-10-05T00:00:00Z' }] }),
      ),
    ).toBe(true)
  })

  it('is false when it never got past Identified', () => {
    expect(
      hasBeenApplied(
        application({ status_history: [{ status: 'Identified', changed_at: '2026-10-05T00:00:00Z' }] }),
      ),
    ).toBe(false)
  })
})
