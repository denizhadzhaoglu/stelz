// Tests mirroring firebase/functions/lib/refs.py _select_reference_docs.
//
// If these drift from the Python, the Settings page lies about which images the
// detector uses — which is worse than not showing it at all, because an operator
// would delete the wrong reference while hunting a false positive.

import { describe, expect, it } from 'vitest'
import { activeReferenceIds, REFERENCE_SLOTS } from './refselect'
import type { ReferenceImage } from './firestore'

const img = (id: string, uploadedAt: string | null, productLine?: string | null): ReferenceImage => ({
  id,
  storagePath: `references/stelz/${id}`,
  url: `https://example.test/${id}.jpg`,
  productLine: productLine ?? null,
  uploadedAt,
})

describe('activeReferenceIds', () => {
  it('takes everything when there are fewer images than slots', () => {
    const items = [img('a', '2026-01-01'), img('b', '2026-01-02')]
    expect(activeReferenceIds(items)).toEqual(new Set(['a', 'b']))
  })

  it('prefers the newest uploads', () => {
    // The bug refs.py:91-96 was written to fix: an unordered take returned the
    // 8 OLDEST, so every good packshot uploaded later was invisible.
    const items = Array.from({ length: 12 }, (_, i) =>
      img(`r${i}`, `2026-01-${String(i + 1).padStart(2, '0')}`))
    const active = activeReferenceIds(items)
    expect(active.size).toBe(REFERENCE_SLOTS)
    expect(active.has('r11')).toBe(true)  // newest
    expect(active.has('r0')).toBe(false)  // oldest
  })

  it('covers every product line before filling with newest', () => {
    // 8 recent seltzer shots plus one old iced-tea shot: the iced tea must
    // survive, or the model never learns that product line exists.
    const items = [
      ...Array.from({ length: 8 }, (_, i) => img(`s${i}`, `2026-02-${String(i + 1).padStart(2, '0')}`, 'hard_seltzer')),
      img('tea', '2020-01-01', 'hard_iced_tea'),
    ]
    const active = activeReferenceIds(items)
    expect(active.has('tea')).toBe(true)
    expect(active.size).toBe(REFERENCE_SLOTS)
  })

  it('treats a missing product line as its own bucket', () => {
    const items = [
      img('a', '2026-01-03', 'hard_seltzer'),
      img('b', '2026-01-02', null),
      img('c', '2026-01-01', 'hard_seltzer'),
    ]
    expect(activeReferenceIds(items, 2)).toEqual(new Set(['a', 'b']))
  })

  it('sorts images with no uploadedAt last', () => {
    const items = [img('nots', null), img('dated', '2026-01-01')]
    expect(activeReferenceIds(items, 1)).toEqual(new Set(['dated']))
  })

  it('never returns more than the slot count', () => {
    const items = Array.from({ length: 40 }, (_, i) => img(`r${i}`, `2026-01-01`, `line${i}`))
    expect(activeReferenceIds(items).size).toBe(REFERENCE_SLOTS)
  })

  it('handles an empty list', () => {
    expect(activeReferenceIds([])).toEqual(new Set())
  })
})
