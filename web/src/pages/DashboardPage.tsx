import { ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { BACKEND_LABELS, MODEL_FIELD } from '@/lib/backends'
import { CATEGORICAL_CHART_COLORS, MATCH_SCORE_RAMP, NOT_SCORED_COLOR } from '@/lib/chartPalette'
import {
  applicationsSentHeatmap,
  applySlicers,
  averageDaysIdentifiedToApplied,
  averageMatchScoreForLane,
  distinctLanes,
  distinctLocations,
  EMPTY_SLICERS,
  foldToOther,
  MATCH_SCORE_BUCKETS,
  NOT_SCORED_BUCKET,
  proportionByLane,
  proportionByMatchScoreBucket,
  proportionByStage,
  wholeHistoryRates,
  type CountEntry,
  type DashboardSlicers,
} from '@/lib/dashboardStats'
import {
  analyzeLaneOverview,
  analyzeLanes,
  ApiError,
  fetchJobApplications,
  fetchLaneAnalysisPreview,
  fetchLaneOverview,
  fetchLanes,
  fetchPositioningRescoreOpenPreview,
  fetchPositioningRescorePreview,
  runPositioningRescoreAll,
  runPositioningRescoreOpen,
} from '@/lib/api'
import {
  STATUS_ORDER,
  type JobApplication,
  type Lane,
  type LaneAnalysisSummary,
  type LaneOverview,
  type PositioningRescoreSummary,
  type Settings,
} from '@/lib/types'
import { cn } from '@/lib/utils'
import type { QueueState } from '@/lib/useClaudeJobs'

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; applications: JobApplication[] }

// A bar chart's own series cap (the dataviz skill's series-count ladder): past this many bars,
// fold the tail into "Other" rather than keep adding distinct hues.
const MAX_LANE_BARS = 7

export function DashboardPage({ settings, queue }: { settings: Settings; queue: QueueState }) {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [slicers, setSlicers] = useState<DashboardSlicers>(EMPTY_SLICERS)
  const [lanes, setLanes] = useState<Lane[]>([])
  const [overview, setOverview] = useState<LaneOverview>({
    summary: null,
    overall_fit: null,
    overall_gaps: null,
    generated_at: null,
  })

  useEffect(() => {
    let cancelled = false
    fetchJobApplications()
      .then((applications) => {
        if (!cancelled) setState({ kind: 'ready', applications })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'Could not load applications.'
        setState({ kind: 'error', message })
      })
    return () => {
      cancelled = true
    }
  }, [])

  function reloadLanes() {
    fetchLanes()
      .then(setLanes)
      .catch(() => undefined)
  }

  useEffect(() => {
    fetchLanes()
      .then(setLanes)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    fetchLaneOverview()
      .then(setOverview)
      .catch(() => undefined)
  }, [])

  // Reloads the stored overview once a "Summarize lanes" job finishes, the same
  // finished-job-id-as-a-dependency pattern ProfilePage.tsx's own Sync-from-strategy reload uses.
  const summarizeLanesJob = [...queue.jobs].reverse().find((job) => job.kind === 'summarize_lanes')
  const finishedSummarizeLanesJob =
    summarizeLanesJob && (summarizeLanesJob.status === 'done' || summarizeLanesJob.status === 'failed')
      ? summarizeLanesJob.id
      : null
  useEffect(() => {
    if (finishedSummarizeLanesJob === null) return
    fetchLaneOverview()
      .then(setOverview)
      .catch(() => undefined)
  }, [finishedSummarizeLanesJob])

  const allApplications = useMemo(
    () => (state.kind === 'ready' ? state.applications : []),
    [state],
  )
  // The whole-history rate stats always read the full, unsliced list (D-241) - every other
  // chart below reads `sliced`.
  const sliced = useMemo(() => applySlicers(allApplications, slicers), [allApplications, slicers])

  const laneOptions = useMemo(() => distinctLanes(allApplications), [allApplications])
  const locationOptions = useMemo(() => distinctLocations(allApplications), [allApplications])

  const laneEntries = useMemo(
    () => foldToOther(proportionByLane(sliced), MAX_LANE_BARS, 'Other lanes'),
    [sliced],
  )
  const stageEntries = useMemo(() => proportionByStage(sliced), [sliced])
  const matchScoreEntries = useMemo(() => proportionByMatchScoreBucket(sliced), [sliced])
  const leadTimeDays = useMemo(() => averageDaysIdentifiedToApplied(sliced), [sliced])
  const rates = useMemo(() => wholeHistoryRates(allApplications), [allApplications])
  const heatmap = useMemo(() => applicationsSentHeatmap(sliced), [sliced])

  if (state.kind === 'loading') {
    return <p className="text-sm text-muted-foreground">Loading…</p>
  }
  if (state.kind === 'error') {
    return <p className="text-sm text-destructive">{state.message}</p>
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <SlicerBar
        slicers={slicers}
        onChange={setSlicers}
        laneOptions={laneOptions}
        locationOptions={locationOptions}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile
          label="Identified → Applied"
          value={leadTimeDays === null ? '—' : `${leadTimeDays.toFixed(1)} days`}
          secondary="average, applications with both dates"
        />
        <StatTile
          label="Applications identified"
          value={rates === null ? '—' : `${rates.identifiedPerDay.toFixed(2)} / day`}
          secondary={rates === null ? undefined : `${rates.identifiedPerWeek.toFixed(1)} / week`}
        />
        <StatTile
          label="Applications sent"
          value={rates === null ? '—' : `${rates.appliedPerDay.toFixed(2)} / day`}
          secondary={rates === null ? undefined : `${rates.appliedPerWeek.toFixed(1)} / week`}
        />
      </div>

      {/* 3 columns x 2 rows: lane spans both rows in column 1; stage and match score fill row 1's
          remaining two columns; applications sent spans both of those columns in row 2. Relies on
          CSS grid auto-placement (the row-span-2 item first, the col-span-2 item last) rather than
          explicit coordinates (D-243). */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:grid-rows-2">
        <ProportionCard
          className="lg:row-span-2"
          title="Proportion by lane"
          entries={laneEntries}
          colorFor={(_label, index) => CATEGORICAL_CHART_COLORS[index % CATEGORICAL_CHART_COLORS.length]}
        />
        <ProportionCard
          title="Proportion by stage"
          entries={stageEntries}
          colorFor={(label) => {
            const index = STATUS_ORDER.indexOf(label as (typeof STATUS_ORDER)[number])
            return CATEGORICAL_CHART_COLORS[(index === -1 ? 0 : index) % CATEGORICAL_CHART_COLORS.length]
          }}
        />
        <ProportionCard
          title="Proportion by match score"
          entries={matchScoreEntries}
          colorFor={(label) => {
            if (label === NOT_SCORED_BUCKET) return NOT_SCORED_COLOR
            const index = MATCH_SCORE_BUCKETS.indexOf(label)
            // index 0 is "Not scored" itself, so the ramp starts one slot later.
            return MATCH_SCORE_RAMP[index - 1] ?? NOT_SCORED_COLOR
          }}
        />
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Applications sent</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col">
            <ApplicationsSentHeatmap days={heatmap} />
          </CardContent>
        </Card>
      </div>

      <LaneSummarySection
        lanes={lanes}
        applications={allApplications}
        onAnalyzed={reloadLanes}
        overview={overview}
        queue={queue}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <RescoreSection
          title="Re-score all positioning analyses"
          buttonLabel="Re-score all"
          description="Clears and regenerates every job application's positioning analysis under the currently selected backend"
          dialogDescription="This will clear and re-queue positioning analysis for"
          skipReason="missing a Master CV, Job details or the profile documents"
          settings={settings}
          fetchPreview={fetchPositioningRescorePreview}
          run={runPositioningRescoreAll}
        />
        <RescoreSection
          title="Re-score open applications"
          buttonLabel="Re-score open"
          description="Same as above, limited to applications that haven't reached an end state (Rejected, Withdrawn, Expired)"
          dialogDescription="This will clear and re-queue positioning analysis for"
          skipReason="missing a Master CV, Job details, the profile documents, or already at an end state"
          settings={settings}
          fetchPreview={fetchPositioningRescoreOpenPreview}
          run={runPositioningRescoreOpen}
        />
      </div>
    </div>
  )
}

// --- Slicers (D-241: these filter every chart above except the whole-history rate stats) -------

const ALL_VALUE = '__all__'

function SlicerBar({
  slicers,
  onChange,
  laneOptions,
  locationOptions,
}: {
  slicers: DashboardSlicers
  onChange: (next: DashboardSlicers) => void
  laneOptions: string[]
  locationOptions: string[]
}) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <SlicerSelect
        label="Lane"
        value={slicers.lane}
        options={laneOptions}
        onChange={(lane) => onChange({ ...slicers, lane })}
      />
      <SlicerSelect
        label="Stage"
        value={slicers.stage}
        options={[...STATUS_ORDER]}
        onChange={(stage) => onChange({ ...slicers, stage })}
      />
      <SlicerSelect
        label="Match score"
        value={slicers.matchScoreBucket}
        options={[...MATCH_SCORE_BUCKETS]}
        onChange={(matchScoreBucket) => onChange({ ...slicers, matchScoreBucket })}
      />
      <SlicerSelect
        label="Location"
        value={slicers.location}
        options={locationOptions}
        onChange={(location) => onChange({ ...slicers, location })}
      />
    </div>
  )
}

function SlicerSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string | null
  options: string[]
  onChange: (next: string | null) => void
}) {
  const items = useMemo(
    () => Object.fromEntries([[ALL_VALUE, 'All'], ...options.map((option) => [option, option])]),
    [options],
  )
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Select
        items={items}
        value={value ?? ALL_VALUE}
        onValueChange={(next) => onChange(next === ALL_VALUE ? null : next)}
      >
        <SelectTrigger className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_VALUE}>All</SelectItem>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

// --- Stat tiles -----------------------------------------------------------------------------

function StatTile({
  label,
  value,
  secondary,
}: {
  label: string
  value: string
  secondary?: string
}) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-2xl font-semibold text-foreground">{value}</span>
        {secondary && <span className="text-xs text-muted-foreground">{secondary}</span>}
      </CardContent>
    </Card>
  )
}

// --- Proportion charts (part-to-whole, categorical identity) -------------------------------

function ProportionCard({
  title,
  entries,
  colorFor,
  className,
}: {
  title: string
  entries: CountEntry[]
  colorFor: (label: string, index: number) => string
  className?: string
}) {
  const data = useMemo(
    () => entries.map((entry, index) => ({ ...entry, fill: colorFor(entry.label, index) })),
    [entries, colorFor],
  )
  const config = useMemo<ChartConfig>(
    () =>
      Object.fromEntries(
        data.map((entry) => [entry.label, { label: entry.label, color: entry.fill }]),
      ),
    [data],
  )

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No applications match the current filters.</p>
        ) : (
          <ChartContainer
            config={config}
            className="aspect-auto h-full"
            style={{ minHeight: Math.max(140, data.length * 36) }}
          >
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke="var(--border)" />
              <XAxis type="number" allowDecimals={false} tickLine={false} axisLine={false} />
              <YAxis
                type="category"
                dataKey="label"
                width={110}
                tickLine={false}
                axisLine={false}
                tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
              />
              <ChartTooltip content={<ChartTooltipContent hideLabel />} />
              <Bar dataKey="count" radius={4} barSize={20}>
                {data.map((entry) => (
                  <Cell key={entry.label} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}

// --- Calendar heatmap (sequential magnitude, trailing 12 months, D-239) ------------------------

function heatmapColor(count: number, max: number): string {
  if (count === 0) return 'var(--muted)'
  if (max <= 0) return 'var(--muted)'
  const steps = MATCH_SCORE_RAMP.length
  // Lightest-to-highest-contrast step carries the highest count, same direction the sequential
  // ramp already uses for match-score buckets.
  const step = Math.min(steps - 1, Math.floor((count / max) * (steps - 1)))
  return MATCH_SCORE_RAMP[steps - 1 - step]
}

function ApplicationsSentHeatmap({ days }: { days: { date: string; count: number }[] }) {
  const max = useMemo(() => days.reduce((m, day) => Math.max(m, day.count), 0), [days])
  // Pad the front so the grid starts on a Sunday column, GitHub-style.
  const firstDay = days.length > 0 ? new Date(`${days[0].date}T00:00:00Z`).getUTCDay() : 0
  const padded = [...Array(firstDay).fill(null), ...days]
  const weeks: ({ date: string; count: number } | null)[][] = []
  for (let i = 0; i < padded.length; i += 7) {
    weeks.push(padded.slice(i, i + 7))
  }

  if (days.length === 0) {
    return <p className="text-sm text-muted-foreground">No applications sent yet.</p>
  }

  return (
    <div className="flex h-full flex-col gap-2">
      {/* A CSS grid with fractional tracks (not fixed-size cells) so the whole year fills the
          card's actual width and height exactly, oldest week at the left, today's at the right -
          no fixed cell size, no horizontal scroll. */}
      <div
        className="grid flex-1 gap-1"
        style={{
          gridTemplateColumns: `repeat(${weeks.length}, 1fr)`,
          gridTemplateRows: 'repeat(7, 1fr)',
          gridAutoFlow: 'column',
          // A floor for when nothing stretches this card taller (e.g. below the `lg` breakpoint,
          // where it isn't sharing a row with the taller lane chart) - without it, 1fr rows have
          // no intrinsic size to fall back on and the grid collapses toward zero height.
          minHeight: 112,
        }}
      >
        {weeks.flatMap((week, weekIndex) =>
          week.map((day, dayIndex) =>
            day === null ? (
              <div key={`${weekIndex}-${dayIndex}`} />
            ) : (
              <div
                key={day.date}
                title={`${day.date}: ${day.count} application${day.count === 1 ? '' : 's'} sent`}
                className="rounded-sm"
                style={{ backgroundColor: heatmapColor(day.count, max) }}
              />
            ),
          ),
        )}
      </div>
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <span>Less</span>
        {[0, ...MATCH_SCORE_RAMP.slice().reverse()].map((step, index) => (
          <div
            key={index}
            className="size-3 rounded-sm"
            style={{ backgroundColor: index === 0 ? 'var(--muted)' : (step as string) }}
          />
        ))}
        <span>More</span>
      </div>
    </div>
  )
}

// --- Per-lane strengths/weaknesses (D-238) ------------------------------------------------------

function LaneSummarySection({
  lanes,
  applications,
  onAnalyzed,
  overview,
  queue,
}: {
  lanes: Lane[]
  applications: JobApplication[]
  onAnalyzed: () => void
  overview: LaneOverview
  queue: QueueState
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Per-lane strengths and weaknesses</CardTitle>
        <div className="flex items-center gap-2">
          <SummarizeLanesButton
            lanesAnalyzed={lanes.some((lane) => lane.fit_gap_summary !== null)}
            queue={queue}
          />
          <AnalyzeLanesButton onAnalyzed={onAnalyzed} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <LaneOverviewReport overview={overview} />
        {lanes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No lanes yet.</p>
        ) : (
          lanes.map((lane) => (
            <LaneSummaryRow
              key={lane.id}
              lane={lane}
              averageMatchScore={averageMatchScoreForLane(applications, lane.name)}
            />
          ))
        )}
      </CardContent>
    </Card>
  )
}

function LaneOverviewReport({ overview }: { overview: LaneOverview }) {
  if (overview.summary === null) {
    return (
      <p className="text-sm text-muted-foreground border-b border-border pb-4">
        No overview yet - run "Summarize lanes" once at least one lane has been analyzed.
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2 border-b border-border pb-4">
      <MarkdownDocument text={overview.summary} />
      <OverviewDetailSection title="Overall fit" text={overview.overall_fit} />
      <OverviewDetailSection title="Overall gaps" text={overview.overall_gaps} />
      {overview.generated_at && (
        <p className="text-xs text-muted-foreground">
          Generated {new Date(overview.generated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}

// One of the overview's two detail sections (D-245) - collapsed by default so the always-visible
// short summary above is what the user sees first; the same Collapsible shape LaneSummaryRow's
// own per-lane detail already uses.
function OverviewDetailSection({ title, text }: { title: string; text: string | null }) {
  const [open, setOpen] = useState(false)
  if (text === null) return null
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex items-center gap-1 text-left text-sm font-medium">
        <ChevronRight className={cn('size-4 transition-transform', open && 'rotate-90')} />
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 pl-5">
        <MarkdownDocument text={text} />
      </CollapsibleContent>
    </Collapsible>
  )
}

function LaneSummaryRow({
  lane,
  averageMatchScore,
}: {
  lane: Lane
  averageMatchScore: number | null
}) {
  const [open, setOpen] = useState(false)
  const matchScoreText =
    averageMatchScore === null ? 'No scored applications' : `${averageMatchScore.toFixed(1)}% average match`

  if (lane.fit_gap_summary === null) {
    return (
      <div className="flex flex-col gap-1 border-b border-border pb-4 last:border-b-0 last:pb-0">
        <div className="flex items-center justify-between">
          <span className="font-medium">{lane.name}</span>
          <span className="text-sm text-muted-foreground">{matchScoreText}</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Not analyzed yet - run "Analyze lanes" once it has a scored application.
        </p>
      </div>
    )
  }

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="border-b border-border pb-4 last:border-b-0 last:pb-0"
    >
      <CollapsibleTrigger className="flex w-full items-center justify-between text-left">
        <span className="flex items-center gap-1 font-medium">
          <ChevronRight className={cn('size-4 transition-transform', open && 'rotate-90')} />
          {lane.name}
        </span>
        <span className="text-sm text-muted-foreground">{matchScoreText}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-1 pt-2 pl-5">
        <MarkdownDocument text={lane.fit_gap_summary} />
        {lane.fit_gap_summary_generated_at && (
          <p className="text-xs text-muted-foreground">
            Generated {new Date(lane.fit_gap_summary_generated_at).toLocaleString()}
          </p>
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}

function SummarizeLanesButton({
  lanesAnalyzed,
  queue,
}: {
  lanesAnalyzed: boolean
  queue: QueueState
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (!open) return
    setError(null)
    setJobId(null)
    setRunning(false)
  }, [open])

  const job = jobId === null ? null : (queue.jobs.find((j) => j.id === jobId) ?? null)

  async function start() {
    setBusy(true)
    setError(null)
    try {
      const started = await analyzeLaneOverview()
      setJobId(started.id)
      setRunning(true)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The summary did not start.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={!lanesAnalyzed}
        title={lanesAnalyzed ? undefined : 'Analyze at least one lane first'}
        onClick={() => setOpen(true)}
      >
        Summarize lanes
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>Summarize lanes</DialogTitle>
          </DialogHeader>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
            {!running && (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  Generates one overview report from the career history, the positioning
                  strategy, and every lane's own analysis so far. Replaces the current overview,
                  if there is one.
                </p>
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button disabled={busy} onClick={() => void start()} className="self-start">
                  {busy ? 'Starting...' : 'Summarize'}
                </Button>
              </div>
            )}
            {running && <RunTrace job={job} />}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function AnalyzeLanesButton({ onAnalyzed }: { onAnalyzed: () => void }) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [preview, setPreview] = useState<LaneAnalysisSummary | null>(null)
  const [result, setResult] = useState<LaneAnalysisSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function openConfirm() {
    setError(null)
    setResult(null)
    setConfirmOpen(true)
    fetchLaneAnalysisPreview()
      .then(setPreview)
      .catch(() => setPreview(null))
  }

  async function confirmAndRun() {
    setBusy(true)
    setError(null)
    try {
      const summary = await analyzeLanes()
      setResult(summary)
      setConfirmOpen(false)
      onAnalyzed()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The analysis did not start.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button size="sm" variant="outline" onClick={openConfirm}>
        Analyze lanes
      </Button>
      {result && (
        <p className="text-xs text-muted-foreground">
          Queued {result.queued}, skipped {result.skipped}.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Analyze lanes?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {preview === null
              ? 'Checking how many lanes are ready...'
              : `This will generate a fit/gap summary for ${preview.queued} lane${preview.queued === 1 ? '' : 's'} (${preview.skipped} skipped - no positioning-scored application yet).`}{' '}
            It can take a while and uses real usage.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy || preview === null || preview.queued === 0}
              onClick={() => void confirmAndRun()}
            >
              {busy ? 'Queuing...' : 'Analyze'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// --- Re-score all / Re-score open positioning analyses (D-218, moved from Settings; D-237) -----

function RescoreSection({
  title,
  buttonLabel,
  description,
  dialogDescription,
  skipReason,
  settings,
  fetchPreview,
  run,
}: {
  title: string
  buttonLabel: string
  description: string
  dialogDescription: string
  skipReason: string
  settings: Settings
  fetchPreview: () => Promise<PositioningRescoreSummary>
  run: () => Promise<PositioningRescoreSummary>
}) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [preview, setPreview] = useState<PositioningRescoreSummary | null>(null)
  const [result, setResult] = useState<PositioningRescoreSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function openConfirm() {
    setError(null)
    setResult(null)
    setConfirmOpen(true)
    fetchPreview()
      .then(setPreview)
      .catch(() => setPreview(null))
  }

  async function confirmAndRun() {
    setBusy(true)
    setError(null)
    try {
      const summary = await run()
      setResult(summary)
      setConfirmOpen(false)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The re-score did not start.')
    } finally {
      setBusy(false)
    }
  }

  const modelField = MODEL_FIELD[settings.backend]
  const activeModel = settings[modelField]
  const backendText = `${BACKEND_LABELS[settings.backend]} (${activeModel})`

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-xs text-muted-foreground">
          {description}, under the currently selected backend ({backendText}).
        </p>
        <div>
          <Button onClick={openConfirm}>{buttonLabel}</Button>
        </div>
        {result && (
          <p className="text-xs text-muted-foreground">
            Queued {result.queued}, skipped {result.skipped}.
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
      </CardContent>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {preview === null
              ? 'Checking how many applications are ready...'
              : `${dialogDescription} ${preview.queued} job application${preview.queued === 1 ? '' : 's'} (${preview.skipped} skipped - ${skipReason}).`}{' '}
            It runs under {backendText}, can take a while, and uses real usage.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={busy || preview === null || preview.queued === 0}
              onClick={() => void confirmAndRun()}
            >
              {busy ? 'Queuing...' : 'Re-score'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
