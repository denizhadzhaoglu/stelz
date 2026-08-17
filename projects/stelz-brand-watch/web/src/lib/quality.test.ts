// Tests for the detection quality tiers.
//
// The load-bearing case is `capped_small_object`: those rows carry
// confidence === 0.70 not because the model was unsure but because the backend
// overwrote a 0.95 for being medium-sized in frame. If this module ever starts
// treating them as low-confidence again, the feed silently loses most genuine
// incidental cans — which is the bug that produced "I only see 49 hits".

import { describe, expect, it } from 'vitest'
import { detectionQuality, qualityCounts, splitByQuality } from './quality'
import type { DetectionRow } from './types'

type QIn = Pick<DetectionRow, 'confidence' | 'gate' | 'size_in_frame'>
const row = (p: Partial<QIn> = {}): QIn => ({
  confidence: 0.9,
  gate: null,
  size_in_frame: 'large',
  ...p,
})

describe('detectionQuality', () => {
  it('treats a clean high-confidence read as clear', () => {
    const q = detectionQuality(row({ confidence: 0.92, size_in_frame: 'dominant' }))
    expect(q.quality).toBe('clear')
    expect(q.needsLook).toBe(false)
  })

  it('classifies a capped small object as small, NOT weak', () => {
    // The regression this module exists for: the model said 0.95, the gate
    // stored 0.70. Reading that 0.70 as "uncertain" is how the feed emptied.
    const q = detectionQuality(row({ confidence: 0.7, gate: 'capped_small_object', size_in_frame: 'medium' }))
    expect(q.quality).toBe('small')
    expect(q.needsLook).toBe(true)
    expect(q.reason).toMatch(/size, not for doubt/)
  })

  it('classifies a partial wordmark read as small', () => {
    const q = detectionQuality(row({ confidence: 0.75, gate: 'accepted_partial_wordmark', size_in_frame: 'small' }))
    expect(q.quality).toBe('small')
  })

  it('lets the gate label win over a confidence that would read as clear', () => {
    // Defensive: if a future gate change caps to something >= 0.85, the label
    // must still demote it. Order of the checks in the module is the guarantee.
    const q = detectionQuality(row({ confidence: 0.95, gate: 'capped_small_object' }))
    expect(q.quality).toBe('small')
  })

  it('lets the gate label win over a confidence that would read as weak', () => {
    const q = detectionQuality(row({ confidence: 0.4, gate: 'accepted_partial_wordmark' }))
    expect(q.quality).toBe('small')
  })

  it('falls back to the confidence band when no gate was recorded', () => {
    // Rows written before `gate` was persisted. 0.70 is the capped-band
    // signature, so treat it as demoted rather than hiding it.
    expect(detectionQuality(row({ confidence: 0.7, gate: null })).quality).toBe('small')
    expect(detectionQuality(row({ confidence: 0.84, gate: null })).quality).toBe('small')
  })

  it('calls everything under 0.70 weak', () => {
    expect(detectionQuality(row({ confidence: 0.69, gate: null })).quality).toBe('weak')
    expect(detectionQuality(row({ confidence: 0, gate: null })).quality).toBe('weak')
  })

  it('survives a null confidence', () => {
    expect(detectionQuality(row({ confidence: null, gate: null })).quality).toBe('weak')
  })

  it('puts the 0.85 boundary on the clear side', () => {
    expect(detectionQuality(row({ confidence: 0.85, gate: null })).quality).toBe('clear')
    expect(detectionQuality(row({ confidence: 0.8499, gate: null })).quality).toBe('small')
  })
})

describe('splitByQuality', () => {
  const rows = [
    { detection_id: 'a', confidence: 0.9, gate: null },
    { detection_id: 'b', confidence: 0.7, gate: 'capped_small_object' },
    { detection_id: 'c', confidence: 0.95, gate: null },
    { detection_id: 'd', confidence: 0.5, gate: null },
  ] as unknown as DetectionRow[]

  it('separates the clean tier from the review tier', () => {
    const { clear, review } = splitByQuality(rows)
    expect(clear.map((r) => r.detection_id)).toEqual(['a', 'c'])
    expect(review.map((r) => r.detection_id)).toEqual(['b', 'd'])
  })

  it('preserves the incoming order inside each group', () => {
    // The feed arrives sorted postedAt desc; regrouping must not reshuffle it,
    // or "is this new?" stops being answerable by looking at the top.
    const { clear } = splitByQuality(rows)
    expect(clear[0].detection_id).toBe('a')
  })

  it('loses nothing', () => {
    const { clear, review } = splitByQuality(rows)
    expect(clear.length + review.length).toBe(rows.length)
  })

  it('handles an empty list', () => {
    expect(splitByQuality([])).toEqual({ clear: [], review: [] })
  })
})

describe('qualityCounts', () => {
  it('counts each tier', () => {
    const rows = [
      { confidence: 0.9, gate: null },
      { confidence: 0.7, gate: 'capped_small_object' },
      { confidence: 0.75, gate: 'accepted_partial_wordmark' },
      { confidence: 0.2, gate: null },
    ] as unknown as DetectionRow[]
    expect(qualityCounts(rows)).toEqual({ clear: 1, small: 2, weak: 1 })
  })
})
