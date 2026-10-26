// Color choices for the Dashboard's charts (Phase 10), picked and validated per the dataviz
// skill's method: color assigned by the job it does, never eyeballed.
//
// Categorical (identity: lane, stage) - the 8 slots below are --chart-1..8 in index.css,
// validated with the skill's own script against this app's real dark surface (#101419):
// `node scripts/validate_palette.js "<hexes>" --mode dark --surface "#101419"` - all five
// checks pass (lightness band, chroma floor, CVD separation, normal-vision floor, contrast).
export const CATEGORICAL_CHART_COLORS: readonly string[] = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
  'var(--chart-7)',
  'var(--chart-8)',
]

// Sequential (magnitude: the match-score buckets are an ordered 0-100% scale, not a set of
// distinct identities) - one hue, low -> high. On this dark surface, the low end recedes toward
// the surface (darker, but capped at the dataviz skill's own 2:1-contrast ordinal floor for dark
// mode, step 600) and the high end pops with the most contrast (lightest step). 10 steps, one
// per 10%-wide bucket, drawn from the skill's documented blue sequential ramp.
export const MATCH_SCORE_RAMP: readonly string[] = [
  '#184f95', // 0-10%  (step 600 - the darkest step that still clears 2:1 on this surface)
  '#1c5cab', // 10-20% (step 550)
  '#256abf', // 20-30% (step 500)
  '#2a78d6', // 30-40% (step 450)
  '#3987e5', // 40-50% (step 400)
  '#5598e7', // 50-60% (step 350)
  '#6da7ec', // 60-70% (step 300)
  '#86b6ef', // 70-80% (step 250)
  '#9ec5f4', // 80-90% (step 200)
  '#b7d3f6', // 90-100% (step 150)
]

// "Not scored" is absence of a value, not a low value - it never borrows a ramp step. A neutral
// already used elsewhere in the app for de-emphasized text/fills.
export const NOT_SCORED_COLOR = 'var(--muted-foreground)'

// Sequential (magnitude: daily counts on the "Applications sent" calendar heatmap, Phase 14,
// D-276) - a dedicated ramp, not MATCH_SCORE_RAMP above (built and indexed for that unrelated
// ordinal chart, with no notion of "zero" and the wrong direction for this one: reusing it made
// the busiest day the darkest, almost blending into the background). Zero itself is handled by
// the caller as 'var(--muted)', never a ramp step (matching NOT_SCORED_COLOR's "absence is not a
// low value" rule). Non-zero counts interpolate linearly from this ramp's dark end (the blue
// ramp's own darkest step, 700, nearest zero) up to literal white at the busiest day - the dark-
// mode "flip" the sequential job calls for, with white as the brightest step by the user's
// explicit choice over the documented blue ramp's own near-white step.
const HEATMAP_LOW_RGB: readonly [number, number, number] = [0x0d, 0x36, 0x6b] // '#0d366b', step 700
const HEATMAP_HIGH_RGB: readonly [number, number, number] = [0xff, 0xff, 0xff] // literal white

export function heatmapIntensityColor(fraction: number): string {
  const clamped = Math.min(1, Math.max(0, fraction))
  const [r, g, b] = HEATMAP_LOW_RGB.map((low, index) =>
    Math.round(low + (HEATMAP_HIGH_RGB[index] - low) * clamped),
  )
  return `rgb(${r}, ${g}, ${b})`
}
