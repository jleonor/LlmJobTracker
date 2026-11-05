// Pure data-shaping functions behind the Dashboard (Phase 10): slicing the full job-applications
// list, and turning a (possibly sliced) list into each chart's data. No fetching and no React
// here - DashboardPage.tsx owns the data and the slicer state, this module only computes from
// what it's given, so every function here is trivially testable on plain arrays.

import { STATUS_ORDER, type JobApplication, type OpenApplication, type StatusHistoryEntry } from '@/lib/types'

// D-249/D-254: the three end states Job Applications and Open Applications share - the only
// status concept both entity types have in common, which is what every "combined" function
// below actually combines on.
const END_STATUSES = new Set(['Rejected', 'Withdrawn', 'Expired'])

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
// D-303: a plain string slice, since CSS truncation (text-overflow: ellipsis) doesn't apply to
// text drawn inside an SVG chart.
export function truncateLabel(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

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

// D-254: the same chart, combining Job and Open Applications' stage counts into the same bars
// (both use the shared STATUS_ORDER - Open Applications only ever populate Identified, Applied,
// Rejected, Withdrawn and Expired, never Screening/Interview/Offer). `openApplications` should
// already be filtered by the Stage slicer if one is active (`applyStageSlicer` below) - Lane,
// Match score and Location don't apply to this entity, so it is never filtered by those.
export function combinedProportionByStage(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
): CountEntry[] {
  const counts = countBy(jobApplications, (application) => application.status)
  for (const application of openApplications) {
    counts.set(application.status, (counts.get(application.status) ?? 0) + 1)
  }
  return sortedEntries(counts, STATUS_ORDER)
}

// The only slicer dimension Open Applications share with Job Applications (D-249: no lane, no
// match score, no location) - applied separately from applySlicers above, which is Job
// Application-shaped throughout.
export function applyStageSlicer(
  openApplications: OpenApplication[],
  stage: string | null,
): OpenApplication[] {
  if (stage === null) return openApplications
  return openApplications.filter((application) => application.status === stage)
}

// --- Totals, Alive/Dead (D-254) -------------------------------------------------------------

export type CombinedTotals = {
  totalJobApplications: number
  totalOpenApplications: number
  total: number
  alive: number
  dead: number
}

// Always the FULL, unsliced lists (matching the whole-history rates' own D-241 rule) - a
// top-level "how many applications are there" count shouldn't change as the slicers change.
export function combinedTotals(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
): CombinedTotals {
  const totalJobApplications = jobApplications.length
  const totalOpenApplications = openApplications.length
  const dead =
    jobApplications.filter((application) => END_STATUSES.has(application.status)).length +
    openApplications.filter((application) => END_STATUSES.has(application.status)).length
  const total = totalJobApplications + totalOpenApplications
  return {
    totalJobApplications,
    totalOpenApplications,
    total,
    alive: total - dead,
    dead,
  }
}

// --- Active / Cold applications (Phase 14, D-274/D-275; combined with Open Applications since
// D-301 - both entity types share status/last_updated/status_history, the only fields these need)

const ACTIVE_STATUSES = new Set(['Applied', 'Screening', 'Interview', 'Offer'])
const STALE_AFTER_DAYS = 30

function daysSinceLastUpdated<T extends { last_updated: string }>(application: T, now: Date): number {
  return (now.getTime() - new Date(application.last_updated).getTime()) / (1000 * 60 * 60 * 24)
}

// Applied through Offer (not Identified, not a dead end state) and touched within the last 30
// days. Not a strict complement of isColdApplication: Identified is neither Active nor Cold until
// it goes stale.
export function isActiveApplication<T extends { status: string; last_updated: string }>(
  application: T,
  now: Date = new Date(),
): boolean {
  if (!ACTIVE_STATUSES.has(application.status)) return false
  return daysSinceLastUpdated(application, now) <= STALE_AFTER_DAYS
}

// Any non-dead status (Identified included) untouched for more than 30 days.
export function isColdApplication<T extends { status: string; last_updated: string }>(
  application: T,
  now: Date = new Date(),
): boolean {
  if (END_STATUSES.has(application.status)) return false
  return daysSinceLastUpdated(application, now) > STALE_AFTER_DAYS
}

// The "Applications sent" count card (D-273/D-274): has an Applied-status entry at all.
export function hasBeenApplied<T extends { status_history: StatusHistoryEntry[] }>(
  application: T,
): boolean {
  return application.status_history.some((entry) => entry.status === 'Applied')
}

// D-301: the Applications sent / Active / Cold stat tiles, combining Job and Open Applications -
// Open Applications gained their own Active/Cold table views in Phase 17, removing the original
// reason (D-274) these stayed Job-only.
export function combinedApplicationsSentCount(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
): number {
  return (
    jobApplications.filter(hasBeenApplied).length + openApplications.filter(hasBeenApplied).length
  )
}

export function combinedActiveCount(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
  now: Date = new Date(),
): number {
  return (
    jobApplications.filter((application) => isActiveApplication(application, now)).length +
    openApplications.filter((application) => isActiveApplication(application, now)).length
  )
}

export function combinedColdCount(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
  now: Date = new Date(),
): number {
  return (
    jobApplications.filter((application) => isColdApplication(application, now)).length +
    openApplications.filter((application) => isColdApplication(application, now)).length
  )
}

// D-306: the "Cold / Rejected" stat tile's second half - Rejected specifically, not the wider
// Dead set (Rejected/Withdrawn/Expired) combinedTotals already reports.
export function combinedRejectedCount(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
): number {
  return (
    jobApplications.filter((application) => application.status === 'Rejected').length +
    openApplications.filter((application) => application.status === 'Rejected').length
  )
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

// --- Identified-date range (Phase 14, D-277, superseding D-271/D-272's as-of-date design): the
// date range slider is a cohort filter, not a time machine - it narrows which applications are
// counted at all (by when they were Identified), but every one of them is read with its real,
// current status and fields, the same as everywhere else in this module. -----------------------

// The earliest "Identified" event across the given applications (Job or Open, or both lists
// concatenated) - the date range slider's lower bound. null when nothing has ever been Identified
// yet.
export function earliestIdentifiedDate<T extends { status_history: StatusHistoryEntry[] }>(
  applications: T[],
): string | null {
  let earliest: string | null = null
  for (const application of applications) {
    for (const entry of application.status_history) {
      if (entry.status !== 'Identified') continue
      if (earliest === null || entry.changed_at < earliest) earliest = entry.changed_at
    }
  }
  return earliest
}

// Keeps only the applications (Job or Open) whose earliest "Identified" day falls within
// [startDate, endDate] (both "YYYY-MM-DD", inclusive) - everything else about a kept application
// is untouched, so every other function in this module keeps working unmodified against the
// result.
export function filterByIdentifiedRange<T extends { status_history: StatusHistoryEntry[] }>(
  applications: T[],
  startDate: string,
  endDate: string,
): T[] {
  return applications.filter((application) => {
    const identified = earliestIdentifiedDate([application])
    if (identified === null) return false
    const day = identified.slice(0, 10)
    return day >= startDate && day <= endDate
  })
}

// --- Identified -> Applied lead time -------------------------------------------------------

function earliestDateFor<T extends { status_history: StatusHistoryEntry[] }>(
  application: T,
  status: string,
): string | null {
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
export function averageDaysIdentifiedToApplied<T extends { status_history: StatusHistoryEntry[] }>(
  applications: T[],
): number | null {
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

// D-301: combines Job and Open Applications' lead times into one average.
export function combinedAverageDaysIdentifiedToApplied(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
): number | null {
  return averageDaysIdentifiedToApplied([...jobApplications, ...openApplications])
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
  return ratesFromEntries(
    applications.flatMap((application) => application.status_history),
    now,
  )
}

// D-254: the same rate, combining Job and Open Applications' Identified/Applied events. Pass
// the FULL, unsliced lists (D-241's rule extends to the combined version).
export function combinedWholeHistoryRates(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
  now: Date = new Date(),
): WholeHistoryRates | null {
  return ratesFromEntries(
    [
      ...jobApplications.flatMap((application) => application.status_history),
      ...openApplications.flatMap((application) => application.status_history),
    ],
    now,
  )
}

function ratesFromEntries(allEntries: StatusHistoryEntry[], now: Date): WholeHistoryRates | null {
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

// --- Applications-sent calendar heatmap (D-302: spans the Identified-date range slider, not a
// fixed trailing year) -------------------------------------------------------------------------

export type HeatmapDay = { date: string; count: number }

export function toDateKey(date: Date): string {
  return date.toISOString().slice(0, 10)
}

// Day arithmetic for the date slider (Phase 14, D-271), kept here alongside the module's other
// date-string helpers rather than in the page component.
export function addDaysToDateKey(dateKey: string, days: number): string {
  const date = new Date(`${dateKey}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return toDateKey(date)
}

export function daysBetweenDateKeys(fromKey: string, toKey: string): number {
  const from = new Date(`${fromKey}T00:00:00Z`).getTime()
  const to = new Date(`${toKey}T00:00:00Z`).getTime()
  return Math.round((to - from) / (1000 * 60 * 60 * 24))
}

export function applicationsSentHeatmap(
  applications: JobApplication[],
  startDate: string,
  endDate: string,
): HeatmapDay[] {
  return heatmapFromEntries(
    applications.flatMap((application) => application.status_history),
    startDate,
    endDate,
  )
}

// D-254/D-302: the same heatmap, combining Job and Open Applications' Applied-date events, spanning
// the Identified-date range slider's own window.
export function combinedApplicationsSentHeatmap(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
  startDate: string,
  endDate: string,
): HeatmapDay[] {
  return heatmapFromEntries(
    [
      ...jobApplications.flatMap((application) => application.status_history),
      ...openApplications.flatMap((application) => application.status_history),
    ],
    startDate,
    endDate,
  )
}

function heatmapFromEntries(
  allEntries: StatusHistoryEntry[],
  startDate: string,
  endDate: string,
): HeatmapDay[] {
  const countsByDay = new Map<string, number>()
  for (const entry of allEntries) {
    if (entry.status !== 'Applied') continue
    const key = entry.changed_at.slice(0, 10)
    countsByDay.set(key, (countsByDay.get(key) ?? 0) + 1)
  }

  const days: HeatmapDay[] = []
  const cursor = new Date(`${startDate}T00:00:00Z`)
  const end = new Date(`${endDate}T00:00:00Z`)
  while (cursor <= end) {
    const key = toDateKey(cursor)
    days.push({ date: key, count: countsByDay.get(key) ?? 0 })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days
}

// --- Applications-sent chart switcher (D-304): three more views over the same per-day Applied
// counts the heatmap already produces, plus a true historical "active jobs" reconstruction -------

// "Count over time" is just `HeatmapDay[]` itself, rendered as a line instead of a calendar grid -
// no separate function needed.

// "Cumulative count over time": a running total over the same per-day counts.
export function cumulativeCounts(days: HeatmapDay[]): HeatmapDay[] {
  let total = 0
  return days.map((day) => {
    total += day.count
    return { date: day.date, count: total }
  })
}

export type WeekdayAverage = { weekday: string; average: number }

const WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

// "Average per day of week": buckets the same per-day counts by weekday (Monday-first) and
// averages across however many of that weekday fall in the given range.
export function averageCountByWeekday(days: HeatmapDay[]): WeekdayAverage[] {
  const totals = new Array(7).fill(0)
  const occurrences = new Array(7).fill(0)
  for (const day of days) {
    const sundayFirst = new Date(`${day.date}T00:00:00Z`).getUTCDay() // 0 = Sunday .. 6 = Saturday
    const mondayFirst = (sundayFirst + 6) % 7 // 0 = Monday .. 6 = Sunday
    totals[mondayFirst] += day.count
    occurrences[mondayFirst] += 1
  }
  return WEEKDAY_LABELS.map((weekday, index) => ({
    weekday,
    average: occurrences[index] === 0 ? 0 : totals[index] / occurrences[index],
  }))
}

export type ActiveCountDay = { date: string; count: number }

// "Active jobs over time" (D-304): a full historical reconstruction, not isActiveApplication's
// current-moment-only check - each application's status as of a given day is whatever its own
// status_history says was current at or before that day, and its staleness is relative to that
// day too (the entry's own changed_at - the only historical "last updated" signal status_history
// carries, status_history being the sole record of the past this app keeps).
export function activeApplicationsOverTime(
  jobApplications: JobApplication[],
  openApplications: OpenApplication[],
  startDate: string,
  endDate: string,
): ActiveCountDay[] {
  const histories = [...jobApplications, ...openApplications].map((application) =>
    [...application.status_history].sort((a, b) => (a.changed_at < b.changed_at ? -1 : 1)),
  )
  // One pointer per application, advanced forward as the day cursor moves forward - valid because
  // both the day cursor and each application's own history are walked in increasing date order.
  const pointers = histories.map(() => -1)

  const days: ActiveCountDay[] = []
  const cursor = new Date(`${startDate}T00:00:00Z`)
  const end = new Date(`${endDate}T00:00:00Z`)
  while (cursor <= end) {
    const dayKey = toDateKey(cursor)
    const dayEnd = `${dayKey}T23:59:59.999Z`
    let count = 0
    for (let i = 0; i < histories.length; i++) {
      const history = histories[i]
      while (pointers[i] + 1 < history.length && history[pointers[i] + 1].changed_at <= dayEnd) {
        pointers[i] += 1
      }
      if (pointers[i] < 0) continue // not Identified yet as of this day
      const current = history[pointers[i]]
      if (!ACTIVE_STATUSES.has(current.status)) continue
      if (daysBetween(current.changed_at, dayEnd) <= STALE_AFTER_DAYS) count += 1
    }
    days.push({ date: dayKey, count })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return days
}
