// A second look at a detection, using only what is already stored.
//
// READ THIS BEFORE TRUSTING IT
// This module is deliberately weak, and the measurements below are why. I tested
// both obvious deterministic rules against the 72 cached Gemini responses on the
// labelled golden set (tools/eval/.cache) before writing any of it:
//
//   rule                                    keeps true   keeps false
//   baseline (strictness gate only)            12/12         2/2
//   reject when the transcript names a rival   12/12         2/2
//   require supporting label copy              11/12         1/2
//
// So: the competitor denylist catches NOTHING on the labelled set, and requiring
// label copy buys one false positive at the price of a genuine can. The two
// false positives that survive the backend gate are indistinguishable from true
// positives in every stored field:
//
//   FALSE  conf=0.70  legibility=clear  fp_risk=low  text='STËLZ HARD SELTZER'
//   TRUE   conf=0.70  legibility=clear  fp_risk=low  text='STËLZ HARD SELTZER S H S ALCOHOL INFUSED SPARKLING WATER WIT…'
//
// The only separator is transcript length, and n=2 is not a sample you fit a
// threshold to. Fitting one is how a recall regression ships.
//
// THEREFORE: nothing here hard-filters on evidence strength. `evidenceTier` sorts
// and labels; it never hides. The real fix has to look at the image again at full
// resolution, which is a backend change — see the plan, Part B.

import type { DetectionRow } from './types'
import { normalize } from './signal'

/**
 * Other drinks brands whose cans share a shelf, a fridge, and a party table with
 * Stëlz. Matched against the model's own transcript of the label.
 *
 * HONEST SCOPE: on the golden set this fires zero times, because the backend
 * gate already rejects these — the model reads `TRULY`, `HEINEKEN`, `Red Bull`,
 * `Coca-Cola` correctly and returns detected=false. This is insurance for the
 * case where a transcript contains BOTH a partial Stëlz read and a rival's
 * wordmark, which the gate would let through since it only asks "is a Stelz
 * variant present". It is not the thing that fixes the feed.
 */
export const COMPETITOR_MARKS = [
  // Hard seltzer / RTD — the direct lookalikes, named in DETECT_PROMPT_V8 rule 2
  'white claw', 'whiteclaw', 'truly', 'viper', 'kokanee', 'lone river',
  'bud light seltzer', 'smirnoff', 'captain morgan', 'jillz', 'topper',
  // Dutch/EU beer — same fridge, same hand
  'bavaria', 'heineken', 'grolsch', 'amstel', 'brand bier', 'hertog jan',
  'desperados', 'corona', 'budweiser', 'skol', 'wickuler', 'jupiler',
  // Soft drinks / energy — the rest of the party table
  'red bull', 'redbull', 'monster', 'coca-cola', 'coca cola', 'pepsi',
  'fanta', 'sprite', 'lipton',
]

/**
 * Label copy that a genuine Stëlz can carries BESIDES the wordmark.
 *
 * Sourced from the transcripts of the 12 confirmed true positives, e.g.
 * "STËLZ HARD ICED TEA ICED TEA PEACH 69 4.5% ALC. VOL". A hallucinated wordmark
 * arrives bare, because the model is pattern-completing a name it was primed
 * with and cannot invent consistent surrounding label text.
 */
export const LABEL_COPY = [
  'hard seltzer', 'hard iced tea', 'iced tea', 'hard lemonade', 'lemonade',
  'mixed classics', 'hard sparkling', 'sparkling water', 'seltzer water',
  'alcohol infused', 'alcohol-infused', 'gin & tonic', 'gin and tonic',
  'moscow mule', 'spritz', 'golden can', 'naturally flavoured',
  'natural flavouring', 'alc. vol', 'non alc',
]

export type EvidenceTier = 'corroborated' | 'wordmark_only'

export type VerifyInfo = {
  tier: EvidenceTier
  /** A rival brand's name appears in the transcript — treat as not-Stëlz. */
  competitor: string | null
  /** One sentence for the UI. */
  reason: string
}

type VerifyInput = Pick<DetectionRow, 'visible_text'>

/**
 * Does the model's transcript name a different drinks brand?
 * Returns the matched mark so the UI can say which one.
 */
export function namesCompetitor(visibleText: string | null | undefined): string | null {
  const t = normalize(visibleText)
  if (!t) return null
  // Substring, not word-boundary: transcripts run words together ("HEINEKEN
  // LAGER BEER Heineken PREMIUM QUALITY") and these marks are distinctive
  // enough that a substring hit is not a coincidence. The opposite tradeoff
  // from isBrandTag in signal.ts, where a false match HIDES a real post — here
  // a false match only demotes one row, and a miss keeps a rival in the feed.
  for (const mark of COMPETITOR_MARKS) if (t.includes(mark)) return mark
  return null
}

/** Does the transcript carry Stëlz label copy beyond the bare wordmark? */
export function hasLabelCopy(visibleText: string | null | undefined): boolean {
  const t = normalize(visibleText)
  if (!t) return false
  return LABEL_COPY.some((c) => t.includes(c))
}

export function verifyDetection(d: VerifyInput): VerifyInfo {
  const competitor = namesCompetitor(d.visible_text)
  if (competitor) {
    return {
      tier: 'wordmark_only',
      competitor,
      reason: `The label text reads "${competitor}" — that is a different brand.`,
    }
  }
  if (hasLabelCopy(d.visible_text)) {
    return {
      tier: 'corroborated',
      competitor: null,
      reason: 'The wordmark is backed up by Stëlz label copy, not just the name on its own.',
    }
  }
  return {
    tier: 'wordmark_only',
    competitor: null,
    reason: 'Only the brand name was read, with none of the surrounding label copy a real can carries. Worth opening.',
  }
}

/**
 * Order a list so the best-evidenced rows come first, preserving the incoming
 * order (postedAt desc) within each tier.
 *
 * Sorting, NOT filtering — see the module header. A row with weak evidence is
 * still shown; it just stops being the first thing seen.
 */
export function sortByEvidence(rows: DetectionRow[]): DetectionRow[] {
  const corroborated: DetectionRow[] = []
  const bare: DetectionRow[] = []
  for (const r of rows) (verifyDetection(r).tier === 'corroborated' ? corroborated : bare).push(r)
  return [...corroborated, ...bare]
}
