// SRS presentation — lib/srs.ts
//
// The arithmetic is trivial; the ordering and the omissions are what these
// tests protect. Both exist to stop the breakdown telling a confident story
// that the score does not support.

import { describe, it, expect } from 'vitest'
import { srsLayers, srsMode, srsHeadline, SRS_WEIGHTS } from './srs'
import type { ResonanceRow } from './types'

function res(partial: Partial<ResonanceRow>): ResonanceRow {
  return {
    brand_id: 'stelz', creator_handle: 'someone', platform: 'instagram',
    srs: 50, graph: null, hashtag: null, subculture: null, comment: null,
    geo: null, visual: null, bootstrap_mode: 'hot',
    computed_at: '2026-01-01T00:00:00Z', creator_id: null, full_name: null,
    follower_count: null, tier: null, status: null, category: null,
    relevance_score: null, clear_visibility_hits: null,
    latest_detection_at: null, posts_scraped: null,
    ...partial,
  }
}

describe('srsMode', () => {
  it('defaults to hot when the doc predates the mode field', () => {
    expect(srsMode(res({ bootstrap_mode: null }))).toBe('hot')
  })
})

describe('srsLayers', () => {
  it('drops subculture when the doc says the layer did not count', () => {
    // The layer spent a long time disabled for want of seed data, and old docs
    // still carry a number from before that. Rendering it would credit the
    // score with a component it does not have.
    const layers = srsLayers(res({ subculture: 0.9, graph: 0.5, subculture_layer_live: false }))
    expect(layers.map((l) => l.key)).not.toContain('subculture')
  })

  it('includes subculture when the layer counted', () => {
    const layers = srsLayers(res({ subculture: 0.9, subculture_layer_live: true }))
    expect(layers.map((l) => l.key)).toContain('subculture')
  })

  it('redistributes the subculture weight exactly as the backend does', () => {
    // If the two disagree, the bars add up to something other than the score
    // shown next to them — the one error a breakdown must never make.
    const dead = srsLayers(res({ bootstrap_mode: 'hot', subculture_layer_live: false }))
    const total = dead.reduce((a, l) => a + l.weight, 0)
    expect(total).toBe(100)
    expect(dead.find((l) => l.key === 'graph')!.weight).toBeGreaterThan(30)
  })

  it('sorts by contribution, not by raw value', () => {
    // In hot mode graph is worth 30% and geo 10%. A weak graph still explains
    // more of the score than a perfect geo.
    const layers = srsLayers(res({ bootstrap_mode: 'hot', graph: 0.4, geo: 1.0 }))
    expect(layers[0].key).toBe('graph')
  })

  it('drops layers with no weight in the current mode', () => {
    // Cold mode switches the visual layer off. Showing it at zero reads as
    // "this creator looks off-brand", which is not what a 0 weight means.
    const cold = srsLayers(res({ bootstrap_mode: 'cold', visual: 0 }))
    expect(cold.map((l) => l.key)).not.toContain('visual')
    const hot = srsLayers(res({ bootstrap_mode: 'hot', visual: 0 }))
    expect(hot.map((l) => l.key)).toContain('visual')
  })

  it('carries the weight that applies in this mode', () => {
    // Cold-start leans on hashtag signal; a mature brand leans on the graph.
    const cold = srsLayers(res({ bootstrap_mode: 'cold', hashtag: 0.5 }))
    expect(cold.find((l) => l.key === 'hashtag')!.weight).toBe(40)
    const hot = srsLayers(res({ bootstrap_mode: 'hot', hashtag: 0.5 }))
    expect(hot.find((l) => l.key === 'hashtag')!.weight).toBe(20)
  })

  it('keeps null layers rather than turning them into zeros', () => {
    // Null means "not computed"; zero means "computed, no signal". The UI
    // renders them differently and must be able to tell them apart.
    const layers = srsLayers(res({ graph: null, hashtag: 0 }))
    expect(layers.find((l) => l.key === 'graph')!.value).toBeNull()
    expect(layers.find((l) => l.key === 'hashtag')!.value).toBe(0)
  })
})

describe('SRS_WEIGHTS', () => {
  it('sums to 100 in every mode — otherwise scores are not comparable', () => {
    for (const mode of ['cold', 'warm', 'hot'] as const) {
      const total = Object.values(SRS_WEIGHTS[mode]).reduce((a, b) => a + b, 0)
      expect(total, `${mode} weights`).toBe(100)
    }
  })
})

describe('srsHeadline', () => {
  it('names the strongest contributing layer', () => {
    expect(srsHeadline(res({ bootstrap_mode: 'hot', graph: 0.9, geo: 0.2 })))
      .toBe('Well connected inside the brand’s network')
  })

  it('returns null when nothing has been computed', () => {
    expect(srsHeadline(res({}))).toBeNull()
  })

  it('returns null when every layer is a genuine zero', () => {
    expect(srsHeadline(res({ graph: 0, hashtag: 0, comment: 0, geo: 0, visual: 0, subculture: 0 }))).toBeNull()
  })

  it('can name the subculture layer', () => {
    expect(srsHeadline(res({ subculture: 0.9, graph: 0.1, subculture_layer_live: true })))
      .toBe('Deep in a scene the brand already lands in')
  })
})
