// Reading an SRS score — the layers, their weights, and what they mean.
//
// Mirrors firebase/functions/handlers/compute_resonance.py. If the weights
// there change, change them here: a breakdown rendered against stale weights
// is worse than no breakdown, because it looks authoritative.
//
// Two honesty constraints the UI has to carry:
//
//   1. WEIGHTS DEPEND ON BOOTSTRAP MODE. A brand with few confirmed hits is
//      scored mostly on hashtag and geo signal; a mature one mostly on the
//      creator graph. The same layer value means different things in each, so
//      the mode has to be shown alongside.
//   2. THE SUBCULTURE LAYER IS CONDITIONAL. It was dead for a long time — the
//      seed data lived in the removed Supabase database — and compute_resonance
//      redistributed its 15%. It is live again for brands that have run the
//      seeding step, and still redistributed for those that haven't. So the
//      layer is rendered only when the doc says it counted
//      (`subcultureLayerLive`), never merely because the field holds a number:
//      old docs carry a value that contributed nothing.

import type { ResonanceRow } from './types'

export type SrsMode = 'cold' | 'warm' | 'hot'

// With the subculture layer live. When it isn't, compute_resonance
// redistributes its share proportionally across the rest — mirrored by
// `redistribute()` below so the rendered weights always match the score.
export const SRS_WEIGHTS: Record<SrsMode, Record<string, number>> = {
  cold: { graph: 5, hashtag: 40, comment: 15, geo: 25, visual: 0, subculture: 15 },
  warm: { graph: 20, hashtag: 25, comment: 15, geo: 15, visual: 10, subculture: 15 },
  hot: { graph: 30, hashtag: 20, comment: 15, geo: 10, visual: 10, subculture: 15 },
}

/** Mirror of compute_resonance.redistribute_weight: spread a dead layer's
 *  share proportionally over the survivors, remainder to the largest, so the
 *  total still lands on 100. */
function redistribute(weights: Record<string, number>, dead: string): Record<string, number> {
  const w = { ...weights }
  const spare = w[dead] ?? 0
  if (!spare) return w
  const target = Object.values(w).reduce((a, b) => a + b, 0)
  w[dead] = 0
  const others = Object.entries(w).filter(([k, v]) => k !== dead && v > 0)
  if (!others.length) return w
  const totalOther = others.reduce((a, [, v]) => a + v, 0)
  for (const [k, v] of others) w[k] = v + Math.floor((spare * v) / totalOther)
  const drift = target - Object.values(w).reduce((a, b) => a + b, 0)
  if (drift) {
    const biggest = others.map(([k]) => k).reduce((a, b) => (w[a] >= w[b] ? a : b))
    w[biggest] += drift
  }
  return w
}

export const MODE_BLURB: Record<SrsMode, string> = {
  cold: 'Few confirmed hits yet, so the score leans on hashtag and location signal rather than on the creator network.',
  warm: 'Enough confirmed hits to start trusting the creator network, balanced against hashtag and location signal.',
  hot: 'Enough confirmed hits that the creator network carries the most weight.',
}

export type SrsLayer = {
  key: string
  label: string
  /** What a high value in this layer actually tells you about the person. */
  meaning: string
  /** 0-1 as stored, or null when the layer produced no signal. */
  value: number | null
  /** Percent of the total score this layer can contribute, in this mode. */
  weight: number
}

const LAYERS: { key: keyof ResonanceRow & string; label: string; meaning: string }[] = [
  { key: 'graph', label: 'Network', meaning: 'How often people already in the brand’s orbit mention, tag or comment on them.' },
  { key: 'hashtag', label: 'Scene fit', meaning: 'How closely their everyday hashtags match the lifestyle tags the brand shows up in. Brand tags are excluded — tagging the brand is not the same as belonging to its scene.' },
  { key: 'comment', label: 'Engagement', meaning: 'How much conversation their brand posts attract.' },
  { key: 'geo', label: 'Local', meaning: 'Dutch-language signal in their bio and captions.' },
  { key: 'visual', label: 'On-brand look', meaning: 'How close their imagery sits to the brand’s own visual centroid.' },
  { key: 'subculture', label: 'Scene depth', meaning: 'How brand-dense the scenes they belong to are — whether they sit in a crowd where the brand already lands well.' },
]

export function srsMode(r: ResonanceRow): SrsMode {
  return (r.bootstrap_mode ?? 'hot') as SrsMode
}

/**
 * Layers in descending order of what they actually contributed to this score.
 *
 * Contribution, not raw value, is the right sort: a 0.9 on a layer worth 5% of
 * the score is a smaller reason this person ranks than a 0.4 on a layer worth
 * 35%, and sorting by value would tell the opposite story.
 *
 * Layers with zero weight in the current mode are dropped — in cold mode the
 * visual layer is switched off entirely, and showing it at 0 invites the reader
 * to conclude the creator looks off-brand.
 */
export function srsLayers(r: ResonanceRow): SrsLayer[] {
  const base = SRS_WEIGHTS[srsMode(r)]
  // The doc is the authority on whether the layer counted. Falling back to
  // "did the field come back non-null" would credit old docs, written while
  // the layer was disabled, with a contribution they never made.
  const weights = r.subculture_layer_live === false ? redistribute(base, 'subculture') : base
  return LAYERS
    .map((l) => ({
      key: l.key,
      label: l.label,
      meaning: l.meaning,
      value: (r[l.key] as number | null) ?? null,
      weight: weights[l.key] ?? 0,
    }))
    .filter((l) => l.weight > 0)
    .sort((a, b) => (b.value ?? 0) * b.weight - (a.value ?? 0) * a.weight)
}

/** The single strongest reason this creator scores as they do, in words. */
export function srsHeadline(r: ResonanceRow): string | null {
  const top = srsLayers(r).filter((l) => l.value != null && l.value > 0)[0]
  if (!top) return null
  switch (top.key) {
    case 'graph': return 'Well connected inside the brand’s network'
    case 'hashtag': return 'Deep in the scenes the brand lives in'
    case 'comment': return 'Draws conversation on brand posts'
    case 'geo': return 'Strong local (Dutch) signal'
    case 'visual': return 'Visually on-brand'
    case 'subculture': return 'Deep in a scene the brand already lands in'
    default: return null
  }
}
