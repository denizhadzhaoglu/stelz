// Tests for the second-look checker.
//
// The cases that matter most are the NEGATIVE ones — the things this module must
// NOT do. It is deliberately weak (see verify.ts header: the competitor denylist
// scores 0/2 on the labelled set), and the danger is someone later promoting it
// from "sorts and labels" to "filters". These tests pin the real transcripts from
// tools/eval/.cache so that regression is visible.

import { describe, expect, it } from 'vitest'
import { hasLabelCopy, namesCompetitor, sortByEvidence, verifyDetection } from './verify'
import type { DetectionRow } from './types'

// Verbatim transcripts from the cached golden-set responses.
const REAL_CANS = [
  'STËLZ HARD SELTZER S H S ALCOHOL INFUSED SPARKLING WATER WITH A HINT',
  'STELZ HARD SPARKLING ALCOHOL-INFUSED SPARKLING WATER WITH A',
  'STËLZ HARD ICED TEA 69',
  'STËLZ MIXED CLASSICS CLASSIC GIN & TONIC 63 CALORIES ALC. 4.5%',
  'STËLZ S H T HARD ICED TEA ICED TEA Peach NATURAL FLAVOURING',
  'STELZ, STELZ YOUR FAVOURITE ICED TEA',
  'STËLZ HARD SELTZER THE GOLDEN CAN ALCOHOL INFUSED SPARKLING WATER',
  'STËLZ HARD ICED TEA ICED TEA PEACH 69 4.5% ALC. VOL',
]
const COMPETITOR_TRANSCRIPTS = [
  'TRULY',
  'LONE RIVER RANCH WATER HARD SELTZER WITH 100% AGAVE AND NATURAL LIME J',
  'HEINEKEN LAGER BEER Heineken PREMIUM QUALITY THE ORIGINAL QUALITY',
  'Red Bull, ENERGY DRINK, 250 ml, 110 CALORIES',
  'MONSTER Rehab, MONSTER ENERGY Absolutely Zero',
  'Coca-Cola',
]

describe('namesCompetitor', () => {
  it('spots each rival brand in a real transcript', () => {
    for (const t of COMPETITOR_TRANSCRIPTS) expect(namesCompetitor(t), t).not.toBeNull()
  })

  it('never fires on a genuine Stëlz transcript', () => {
    // The expensive failure: a false hit here would drop a real can.
    for (const t of REAL_CANS) expect(namesCompetitor(t), t).toBeNull()
  })

  it('ignores case and diacritics', () => {
    expect(namesCompetitor('white claw')).toBe('white claw')
    expect(namesCompetitor('WHITE CLAW')).toBe('white claw')
  })

  it('returns which mark matched, for the UI', () => {
    expect(namesCompetitor('HEINEKEN LAGER')).toBe('heineken')
  })

  it('handles null and empty input', () => {
    expect(namesCompetitor(null)).toBeNull()
    expect(namesCompetitor(undefined)).toBeNull()
    expect(namesCompetitor('')).toBeNull()
  })

  it('catches a rival named alongside a partial Stelz read', () => {
    // The one case the backend gate genuinely misses: it only asks whether a
    // Stelz variant is present, so a transcript containing both passes.
    expect(namesCompetitor('ST??Z ... WHITE CLAW HARD SELTZER')).toBe('white claw')
  })
})

describe('hasLabelCopy', () => {
  it('is true for every confirmed true positive with a full transcript', () => {
    for (const t of REAL_CANS) expect(hasLabelCopy(t), t).toBe(true)
  })

  it('is false for a bare wordmark', () => {
    // Both surviving false positives in the golden set look exactly like this.
    expect(hasLabelCopy('STELZ')).toBe(false)
    expect(hasLabelCopy('ST??Z')).toBe(false)
  })

  it('treats a bare "STËLZ HARD SELTZER" as corroborated', () => {
    // Documenting a KNOWN LIMIT rather than pretending otherwise: golden-set
    // false positive fewshot_neg_00 reads exactly this and passes. That is why
    // this signal only sorts and never filters.
    expect(hasLabelCopy('STËLZ HARD SELTZER')).toBe(true)
  })
})

describe('verifyDetection', () => {
  it('reports a competitor before anything else', () => {
    const v = verifyDetection({ visible_text: 'TRULY HARD SELTZER' } as DetectionRow)
    expect(v.competitor).toBe('truly')
    expect(v.tier).toBe('wordmark_only')
    expect(v.reason).toMatch(/different brand/)
  })

  it('marks a full label read as corroborated', () => {
    const v = verifyDetection({ visible_text: REAL_CANS[0] } as DetectionRow)
    expect(v.tier).toBe('corroborated')
    expect(v.competitor).toBeNull()
  })

  it('marks a bare name as wordmark_only with an actionable reason', () => {
    const v = verifyDetection({ visible_text: 'STELZ' } as DetectionRow)
    expect(v.tier).toBe('wordmark_only')
    expect(v.reason).toMatch(/Worth opening/)
  })

  it('survives a missing transcript', () => {
    expect(verifyDetection({ visible_text: null } as DetectionRow).tier).toBe('wordmark_only')
  })
})

describe('sortByEvidence', () => {
  const rows = [
    { detection_id: 'bare1', visible_text: 'STELZ' },
    { detection_id: 'full1', visible_text: REAL_CANS[0] },
    { detection_id: 'bare2', visible_text: 'ST??Z' },
    { detection_id: 'full2', visible_text: REAL_CANS[2] },
  ] as unknown as DetectionRow[]

  it('puts corroborated rows first', () => {
    expect(sortByEvidence(rows).map((r) => r.detection_id)).toEqual(['full1', 'full2', 'bare1', 'bare2'])
  })

  it('preserves incoming order within each tier', () => {
    // The feed arrives postedAt desc; reshuffling inside a tier would make
    // "is this new?" unanswerable.
    const out = sortByEvidence(rows)
    expect(out[0].detection_id).toBe('full1')
    expect(out[2].detection_id).toBe('bare1')
  })

  it('drops nothing — this sorts, it does not filter', () => {
    // The single most important assertion in this file. See verify.ts header.
    expect(sortByEvidence(rows)).toHaveLength(rows.length)
  })

  it('handles an empty list', () => {
    expect(sortByEvidence([])).toEqual([])
  })
})
