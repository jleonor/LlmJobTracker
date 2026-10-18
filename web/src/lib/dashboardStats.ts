// Pure data-shaping functions behind the Dashboard (Phase 10): slicing the full job-applications
// list, and turning a (possibly sliced) list into each chart's data. No fetching and no React
// here - DashboardPage.tsx owns the data and the slicer state, this module only computes from
// what it's given, so every function here is trivially testable on plain arrays.

import { STATUS_ORDER, type JobApplication } from '@/lib/types'

// --- Slicers (D-241: these filter every chart except the whole-history rate stats) -------------

export type DashboardSlicers = {
  lane: string | null
  stage: string | null
  matchScoreBucket: string | null
  location: string | null
}

export const EMPTY_SLICERS: DashboardSlicers = {
  lane: null,
  stage: null,
  matchScoreBucket: null,
  location: null,
}

export function applySlicers(
  applications: JobApplication[],
  slicers: DashboardSlicers,
): JobApplication[] {
  return applications.filter((application) => {
    if (slicers.lane !== null && (application.lane ?? NO_LANE_LABEL) !== slicers.lane) {
      return false
    }
    if (slicers.stage !== null && application.status !== slicers.stage) {
      return false
    }
    if (
      slicers.matchScoreBucket !== null &&
      matchScoreBucket(application.match_score) !== slicers.matchScoreBucket
    ) {
      return false
    }
    if (
      slicers.location !== null &&
      (application.location ?? NO_LOCATION_LABEL) !== slicers.location
    ) {
      return false
    }
    return true
  })
}

export function distinctLanes(applications: JobApplication[]): string[] {
  return distinctLabels(applications, (application) => application.lane ?? NO_LANE_LABEL)
}

export function distinctLocations(applications: JobApplication[]): string[] {
  return distinctLabels(
    applications,
    (application) => application.location ?? NO_LOCATION_LABEL,
  )
}

function distinctLabels(
  applications: JobApplication[],
  label: (application: JobApplication) => string,
): string[] {
  return [...new Set(applications.map(label))].sort((a, b) => a.localeCompare(b))
}

// --- Match-score buckets (D-239: a dedicated "Not scored" bucket, never excluded) ---------------

export const NO_LANE_LABEL = 'No lane'
export const NO_LOCATION_LABEL = 'No location'
export const NOT_SCORED_BUCKET = 'Not scored'

export const MATCH_SCORE_BUCKETS: readonly string[] = [
  NOT_SCORED_BUCKET,
  '0-10%',
  '10-20%',
  '20-30%',
  '30-40%',
  '40-50%',
  '50-60%',
  '60-70%',
  '70-80%',
  '80-90%',
  '90-100%',
]

export function matchScoreBucket(matchScore: number | null): string {
  if (matchScore === null) {
    return NOT_SCORED_BUCKET
  }
  const clamped = Math.min(Math.max(matchScore, 0), 100)
  const lower = Math.min(Math.floor(clamped / 10) * 10, 90)
  return `${lower}-${lower + 10}%`
}

// --- Proportion charts ---------------------------------------------------------------------

export type CountEntry = { label: string; count: number }

function countBy(
  applications: JobApplication[],
  label: (application: JobApplication) => string,
): Map<string, number> {
  const counts = new Map<string, number>()
  for (const application of applications) {
    const key = label(application)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return counts
}

function sortedEntries(counts: Map<string, number>, order?: readonly string[]): CountEntry[] {
  const labels = order ? order.filter((label) => counts.has(label)) : [...counts.keys()].sort()
  return labels.map((label) => ({ label, count: counts.get(label) ?? 0 }))
}

function sortedByCountDescending(counts: Map<string, number>): CountEntry[] {
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

// Keeps the `max` largest entries as-is and folds the rest into one trailing "Other" entry
// (the dataviz skill's series-count ladder: past ~7-8 categorical slots, fold the tail rather
// than generate more hues). A no-op when there are `max` or fewer entries already. `otherLabel`
// is a required, caller-chosen label (not a hardcoded "Other") precisely because the entries
// being folded can themselves already contain something named "Other" - the lanes catalog's own
// fixed catch-all lane (D-219) - and a second, unrelated row with that same label reads as a
// duplicate rather than two different things.
export function foldToOther(entries: CountEntry[], max: number, otherLabel: string): CountEntry[] {
  if (entries.length <= max) return entries
  const kept = entries.slice(0, max)
  const foldedCount = entries.slice(max).reduce((total, entry) => total + entry.count, 0)
  return [...kept, { label: otherLabel, count: foldedCount }]
}

export function proportionByLane(applications: JobApplication[]): CountEntry[] {
  const counts = countBy(applications, (application) => application.lane ?? NO_LANE_LABEL)
  return sortedByCountDescending(counts)
}

export function proportionByStage(applications: JobApplication[]): CountEntry[] {
  const counts = countBy(applications, (application) => application.status)
  return sortedEntries(counts, STATUS_ORDER)
}

export function proportionByMatchScoreBucket(applications: JobApplication[]): CountEntry[] {
  const counts = countBy(applications, (application) => matchScoreBucket(application.match_score))
  return sortedEntries(counts, MATCH_SCORE_BUCKETS)
}

// The Dashboard's per-lane strengths/weaknesses table (D-238) always reads the full,
// unfiltered application list - filtering it by the lane slicer itself would leave at most one
// row, and filtering by the others would blur what "this lane's own average" means. null when
// the lane has no scored application yet.
export function averageMatchScoreForLane(
  applications: JobApplication[],
  laneName: string,
): number | null {
  const scores = applications
    .filter((application) => application.lane === laneName)
    .map((application) => application.match_score)
    .filter((score): score is number => score !== null)
  if (scores.length === 0) return null
  return scores.reduce((total, score) => total + score, 0) / scores.length
}

// --- Identified -> Applied lead time -------------------------------------------------------

function earliestDateFor(application: JobApplication, status: string): string | null {
  let earliest: string | null = null
  for (const entry of application.status_history) {
    if (entry.status !== status) continue
    if (earliest === null || entry.changed_at < earliest) {
      earliest = entry.changed_at
    }
  }
  return earliest
}

function daysBetween(fromIso: string, toIso: string): number {
  return (new Date(toIso).getTime() - new Date(fromIso).getTime()) / (1000 * 60 * 60 * 24)
}

// null when no application in the (sliced) list has both an Identified and a later Applied date.
export function averageDaysIdentifiedToApplied(applications: JobApplication[]): number | null {
  const leadTimes: number[] = []
  for (const application of applications) {
    const identified = earliestDateFor(application, 'Identified')
    const applied = earliestDateFor(application, 'Applied')
    if (identified === null || applied === null) continue
    const days = daysBetween(identified, applied)
    if (days >= 0) leadTimes.push(days)
  }
  if (leadTimes.length === 0) return null
  return leadTimes.reduce((total, days) => total + days, 0) / leadTimes.length
}

// --- Whole-history identified/applied rates (D-241: always unfiltered by the slicers) ----------

export type WholeHistoryRates = {
  identifiedPerDay: number
  identifiedPerWeek: number
  appliedPerDay: number
  appliedPerWeek: number
}

// Pass the FULL, unsliced application list here, never the slicer-filtered one (D-241).
export function wholeHistoryRates(
  applications: JobApplication[],
  now: Date = new Date(),
): WholeHistoryRates | null {
  const allEntries = applications.flatMap((application) => application.status_history)
  if (allEntries.length === 0) return null
  const earliest = allEntries.reduce(
    (min, entry) => (entry.changed_at < min ? entry.changed_at : min),
    allEntries[0].changed_at,
  )
  const elapsedDays = Math.max(1, daysBetween(earliest, now.toISOString()))
  const elapsedWeeks = elapsedDays / 7
  const identifiedCount = allEntries.filter((entry) => entry.status === 'Identified').length
  const appliedCount = allEntries.filter((entry) => entry.status === 'Applied').length
  return {
    identifiedPerDay: identifiedCount / elapsedDays,
    identifiedPerWeek: identifiedCount / elapsedWeeks,
    appliedPerDay: appliedCount / elapsedDays,
    appliedPerWeek: appliedCount / elapsedWeeks,
  }
}

// --- Applications-sent calendar heatmap (D-239: trailing 12 months, every calendar day) --------

export type HeatmapDay = { date: string; count: number }

function toDateKey(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function applicationsSentHeatmap(
  applications: JobApplication[],
  today: Date = new Date(),
): HeatmapDay[] {
  const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()))
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - 364) // a trailing 12-month window, GitHub-heatmap style

  const countsByDay = new Map<string, number>()
  for (const application of applications) {
    for (const entry of application.status_history) {
      if (entry.status !== 'Applied') continue
      const key = entry.changed_at.slice(0, 10)
      countsByDay.set(key, (countsByDay.get(key) ?? 0) + 1)
    }
  }

  const days: HeatmapDay[] = []
  const cursor = new Date(start)
  while (cursor <= end) {
    const key = toDateKey(cursor)
    days.push({ date: key, count: countsByDay.get(key) ?? 0 })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days
}
