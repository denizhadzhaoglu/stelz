// How much to trust a single detection — and why.
//
// WHY THIS EXISTS
// The feed used to filter on `confidence >= 0.85`, presented as a confidence
// slider. It is not one. The backend's strictness gate (detect_image.py,
// `_strictness_gate` rule 2) OVERWRITES confidence with exactly 0.70 whenever
// the can is not `dominant`/`large` in frame — no matter what the model said.
// Three genuine cans in the golden set were rated 0.95 by the model and stored
// as 0.70 purely for being `medium`.
//
// So `>= 0.85` is not "the model is sure", it is "the can filled the frame".
// Measured over the 72 cached golden responses (tools/eval/.cache):
//
//     size        accepted   visible at >=0.85
//     dominant       3              3
//     large          5              5
//     medium         4              0
//     small          2              0
//
// Every large can was visible; no small one was. That is a size filter wearing
// a confidence label, and it hits the untagged feed hardest, because a post
// nobody tagged is usually one where the can is incidental — on a table, in the
// background, at a party. Exactly the `medium`/`small` rows.
//
// WHAT THIS MODULE DOES NOT DO
// It does not try to rescue the good rows out of the demoted band. That was
// tested and it does not work: in the golden set's sub-0.85 band the true cans
// carry model_confidence 0.95 and the false ones 0.90, at the same sizes with
// the same gate label. No field separates them. So the band is surfaced as a
// clearly-labelled tier with an honest error rate, rather than silently mixed
// into the feed (which is what makes a wrong can read as "this tool is broken")
// or silently hidden (which is what made the feed look empty).

import type { DetectionRow } from './types'

export type Quality = 'clear' | 'small' | 'weak'

export type QualityInfo = {
  quality: Quality
  /** True for the demoted band — needs a human glance before you act on it. */
  needsLook: boolean
  /** One sentence for the UI explaining what the gate did and why. */
  reason: string
}

export function detectionQuality(d: Pick<DetectionRow, 'confidence' | 'gate' | 'size_in_frame'>): QualityInfo {
  const conf = d.confidence ?? 0
  const gate = d.gate ?? null

  // Gate label first, where we have one. It is the only field that records the
  // model's ORIGINAL judgement, and it survives the confidence overwrite.
  // Older rows predate the gate field being persisted, hence the fallbacks.
  if (gate === 'capped_small_object') {
    return {
      quality: 'small',
      needsLook: true,
      reason: 'The can is small or mid-distance in frame. The model was confident; the gate capped the score for size, not for doubt.',
    }
  }
  if (gate === 'accepted_partial_wordmark') {
    return {
      quality: 'small',
      needsLook: true,
      reason: 'Only part of the wordmark was readable, so this was accepted at a reduced score.',
    }
  }

  if (conf >= 0.85) {
    return {
      quality: 'clear',
      needsLook: false,
      reason: 'The wordmark was read cleanly and the can is large in frame.',
    }
  }
  // No gate recorded (older scan) but sitting in the demoted band — the shape of
  // a capped hit. Treat it as one; the alternative is hiding it entirely.
  if (conf >= 0.7) {
    return {
      quality: 'small',
      needsLook: true,
      reason: 'Scored in the capped band — usually a can that is small in frame.',
    }
  }
  return {
    quality: 'weak',
    needsLook: true,
    reason: 'Low score and no clean wordmark read. Most of these are not Stëlz.',
  }
}

export function qualityCounts(rows: DetectionRow[]): Record<Quality, number> {
  const out: Record<Quality, number> = { clear: 0, small: 0, weak: 0 }
  for (const r of rows) out[detectionQuality(r).quality]++
  return out
}

/**
 * Split a feed list into the clean tier and the demoted tier, preserving the
 * incoming order (postedAt desc) inside each.
 *
 * Two chronological groups, not one mixed list: a ~1-in-3 error rate scattered
 * invisibly through a feed destroys trust in every row, while the same rows
 * under a labelled heading are a review queue.
 */
export function splitByQuality(rows: DetectionRow[]): { clear: DetectionRow[]; review: DetectionRow[] } {
  const clear: DetectionRow[] = []
  const review: DetectionRow[] = []
  for (const r of rows) (detectionQuality(r).needsLook ? review : clear).push(r)
  return { clear, review }
}
