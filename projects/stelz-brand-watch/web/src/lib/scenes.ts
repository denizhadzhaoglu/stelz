// Which scenes the brand lives in — grouped from what the detector already saw.
//
// TWO SOURCES, IN ORDER OF PREFERENCE
// -----------------------------------
// 1. SUBCULTURES — hand-curated scenes ("Vrijmibo", "Student life") that
//    creators are filed into by handlers/seed_subcultures.py. These are the
//    real thing: named scenes the brand recognises, matched on the creator's
//    own hashtag history. Use them whenever the data exists.
// 2. PER-PHOTO GROUPING — the fallback below, derived from what the detector
//    saw in each individual image.
//
// The subculture data was absent for a long time (its seeding script wrote to
// the Supabase database removed in 2026-06), which is why the fallback exists
// at all and why it must keep working: a brand that has never run the seeding
// step still gets a scenes block, just a coarser one.
//
// The two answer subtly different questions and neither replaces the other.
// A subculture is a property of the CREATOR — the crowd they belong to. A
// photo grouping is a property of the POST — what was happening in that shot.
// A festival photographer posting from their kitchen is in the festival scene
// and the post is not.
//
// WHAT THE FALLBACK IS
// --------------------
// `activity` and `setting` are written on every detection by the vision prompt
// (DETECT_PROMPT_V8 → detect_image.py), for every hit, today. They describe the
// scene the can was found in. Grouping them gives the same story the subculture
// layer was meant to tell — which scenes the brand shows up in — from data that
// actually exists.
//
// THE NUMBER THAT MATTERS is the untagged count per scene, not the total. A
// scene where the brand is tagged is a scene the brand already knows about.

import { classifySignal, BRAND_OWNED_HANDLES } from './signal'
import type { DetectionRow } from './types'

export type Scene = {
  key: string
  label: string
  /** Hits in this scene, post-level. */
  total: number
  /** Of those, the ones carrying no brand hashtag, mention or brand account. */
  untagged: number
  /** untagged / total, 0-100. */
  untaggedPct: number
  /** Where indoors/outdoors is known, the outdoor share — 0-100, or null. */
  outdoorPct: number | null
}

// `activity` is free text: the prompt gives examples ("drinking, partying,
// sports, posing, eating, none, etc.") rather than an enum, so the model
// returns whatever fits — "dancing at a festival", "chilling on a terrace",
// "aan het BBQ'en". Matching on substrings is therefore the only workable
// approach, and the buckets have to be broad enough to survive the phrasing.
//
// Order matters: the first bucket whose patterns match wins. Festival and
// nightlife come before the generic drinking/social buckets, because "drinking
// at a festival" is a festival scene first — that is the distinction the brand
// is buying.
const BUCKETS: { key: string; label: string; patterns: RegExp }[] = [
  { key: 'festival', label: 'Festivals & events', patterns: /festival|concert|gig|rave|stage|crowd|optreden|evenement/ },
  { key: 'nightlife', label: 'Nightlife & clubs', patterns: /club|night ?life|nightclub|bar|pub|disco|dj|dansen|dancing|uitgaan/ },
  { key: 'party', label: 'Parties & gatherings', patterns: /part(y|ying)|celebrat|feest|borrel|vrijmibo|toast|proost|cheers|birthday|verjaardag/ },
  { key: 'outdoor_leisure', label: 'Outdoors & terraces', patterns: /terrace|terras|beach|strand|picnic|park|bbq|barbec|camping|boat|boot|garden|tuin|hiking|festivalcamping/ },
  { key: 'sport', label: 'Sport & active', patterns: /sport|gym|foot ?ball|voetbal|surf|skate|ski|snowboard|run(ning)?|cycl|fiets|padel|tennis|match|wedstrijd/ },
  { key: 'food', label: 'Food & dining', patterns: /eat|eten|dining|dinner|diner|lunch|restaurant|food|koken|cooking|snack/ },
  { key: 'home', label: 'At home', patterns: /home|thuis|kitchen|keuken|couch|bank|living ?room|huiskamer|indoor gathering|studeren|studying/ },
  { key: 'social', label: 'Hanging out', patterns: /drink|hang|chill|social|relax|friends|vrienden|gezellig|pos(e|ing)|selfie|portrait/ },
]

/** Rows the detector couldn't place: activity null, empty, or "none"/"unclear". */
const UNPLACEABLE = /^(none|null|n\/a|unclear|unknown|)$/

export function sceneKeyFor(d: Pick<DetectionRow, 'activity' | 'setting' | 'context'>): { key: string; label: string } {
  const raw = (d.activity ?? '').trim().toLowerCase()
  if (!UNPLACEABLE.test(raw)) {
    for (const b of BUCKETS) {
      if (b.patterns.test(raw)) return { key: b.key, label: b.label }
    }
  }
  // Fall back to the detector's free-text scene description before giving up.
  // `context` is one sentence about what is happening, so it often names the
  // scene even when `activity` came back "none" — throwing that away would
  // dump a large share of real festival and party hits into "Other".
  const ctx = (d.context ?? '').trim().toLowerCase()
  if (ctx) {
    for (const b of BUCKETS) {
      if (b.patterns.test(ctx)) return { key: b.key, label: b.label }
    }
  }
  return { key: 'other', label: 'Unplaced' }
}

/**
 * Group hits into scenes, counting how many in each carry no brand signal.
 *
 * Pass post-level (deduped) rows. `Unplaced` is returned like any other scene
 * rather than dropped: how much of the data the detector couldn't place is
 * itself worth seeing, and hiding it would make the rest look more complete
 * than it is.
 */
export function sceneBreakdown(rows: DetectionRow[]): Scene[] {
  const acc = new Map<string, { label: string; total: number; untagged: number; outdoor: number; placed: number }>()
  for (const d of rows) {
    // Brand-owned posts are excluded — see the long note in lib/communities.ts.
    // A scene count dominated by the brand's own account measures the marketing
    // calendar, not the audience.
    if (BRAND_OWNED_HANDLES.has((d.creator_handle ?? '').toLowerCase())) continue
    const { key, label } = sceneKeyFor(d)
    const e = acc.get(key) ?? { label, total: 0, untagged: 0, outdoor: 0, placed: 0 }
    e.total += 1
    const sig = d.signal?.signal ?? classifySignal(d).signal
    if (sig === 'visual_only') e.untagged += 1
    const setting = (d.setting ?? '').toLowerCase()
    if (setting === 'indoor' || setting === 'outdoor') {
      e.placed += 1
      if (setting === 'outdoor') e.outdoor += 1
    }
    acc.set(key, e)
  }
  return [...acc.entries()]
    .map(([key, e]) => ({
      key,
      label: e.label,
      total: e.total,
      untagged: e.untagged,
      untaggedPct: e.total ? Math.round((e.untagged / e.total) * 100) : 0,
      outdoorPct: e.placed ? Math.round((e.outdoor / e.placed) * 100) : null,
    }))
    // Untagged first — that is the story. "Unplaced" sinks to the bottom
    // regardless of size, because it is a gap in the data, not a scene.
    .sort((a, b) => {
      if (a.key === 'other') return 1
      if (b.key === 'other') return -1
      return b.untagged - a.untagged || b.total - a.total
    })
}


// ── Subculture-backed breakdown (preferred when the data exists) ──────

/** Which scenes each creator belongs to, keyed by lowercase handle. */
export type CreatorSceneMap = Record<string, { slug: string; confidence: number }[]>

export type SubcultureScene = Scene & {
  /** Creators filed into this scene who produced at least one of these hits. */
  creators: number
}

/**
 * Group hits by the SUBCULTURE of the creator who posted them.
 *
 * A creator can belong to several scenes, so a hit is counted once per scene
 * they belong to. Totals therefore exceed the hit count — deliberately, since
 * the question each row answers is "how much of our content comes out of this
 * scene", not "how do the hits partition". The UI has to say so; a reader who
 * adds the rows up and compares to the headline will otherwise think something
 * is broken.
 *
 * Hits whose creator has no scene are folded into `Unplaced`, exactly as in the
 * fallback, so coverage stays visible.
 */
export function subcultureBreakdown(
  rows: DetectionRow[],
  creatorScenes: CreatorSceneMap,
  labels: Record<string, string> = {},
): SubcultureScene[] {
  const acc = new Map<string, { total: number; untagged: number; creators: Set<string> }>()
  const bump = (key: string, d: DetectionRow, handle: string) => {
    const e = acc.get(key) ?? { total: 0, untagged: 0, creators: new Set<string>() }
    e.total += 1
    if ((d.signal?.signal ?? classifySignal(d).signal) === 'visual_only') e.untagged += 1
    e.creators.add(handle)
    acc.set(key, e)
  }

  for (const d of rows) {
    const handle = (d.creator_handle ?? '').toLowerCase()
    if (BRAND_OWNED_HANDLES.has(handle)) continue
    const scenes = creatorScenes[handle]
    if (!scenes || scenes.length === 0) {
      bump('other', d, handle)
      continue
    }
    for (const s of scenes) bump(s.slug, d, handle)
  }

  return [...acc.entries()]
    .map(([key, e]) => ({
      key,
      label: key === 'other' ? 'Unplaced' : (labels[key] ?? key.replace(/_/g, ' ')),
      total: e.total,
      untagged: e.untagged,
      untaggedPct: e.total ? Math.round((e.untagged / e.total) * 100) : 0,
      outdoorPct: null,
      creators: e.creators.size,
    }))
    .sort((a, b) => {
      if (a.key === 'other') return 1
      if (b.key === 'other') return -1
      return b.untagged - a.untagged || b.total - a.total
    })
}
