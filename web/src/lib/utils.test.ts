import { describe, expect, it } from 'vitest'

import { cn } from './utils'

describe('cn', () => {
  it('joins class names and drops falsy values', () => {
    expect(cn('a', false, 'b', undefined)).toBe('a b')
  })

  it('keeps the last of two conflicting Tailwind utilities', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4')
  })
})
