import { describe, expect, it } from 'vitest'

import { heatmapIntensityColor } from './chartPalette'

describe('heatmapIntensityColor', () => {
  it('is the dark anchor at fraction 0', () => {
    expect(heatmapIntensityColor(0)).toBe('rgb(13, 54, 107)')
  })

  it('is literal white at fraction 1', () => {
    expect(heatmapIntensityColor(1)).toBe('rgb(255, 255, 255)')
  })

  it('is brighter at a higher fraction', () => {
    const brightnessOf = (color: string) => {
      const [r, g, b] = color.match(/\d+/g)!.map(Number)
      return r + g + b
    }
    expect(brightnessOf(heatmapIntensityColor(0.75))).toBeGreaterThan(brightnessOf(heatmapIntensityColor(0.25)))
  })

  it('clamps out-of-range fractions', () => {
    expect(heatmapIntensityColor(-1)).toBe(heatmapIntensityColor(0))
    expect(heatmapIntensityColor(2)).toBe(heatmapIntensityColor(1))
  })
})
