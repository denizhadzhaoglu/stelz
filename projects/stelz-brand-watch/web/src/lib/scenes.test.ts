// Scene grouping — lib/scenes.ts
//
// The risk here is not arithmetic, it's classification. `activity` is free text
// from a vision model with no enum to hold it, in a mix of Dutch and English,
// so the tests that matter are the ones about what lands where — and the one
// about bucket ORDER, since "drinking at a festival" matches two buckets and
// only the festival answer is useful to the brand.

import { describe, it, expect } from 'vitest'
import { sceneKeyFor, sceneBreakdown, subcultureBreakdown } from './scenes'
import type { DetectionRow } from './types'

function row(partial: Partial<DetectionRow>): DetectionRow {
  return {
    detection_id: Math.random().toString(36).slice(2),
    creator_id: null, creator_handle: 'someone', creator_category: null,
    platform: 'instagram', product_line: null, confidence: 0.9,
    size_in_frame: null, is_primary_subject: null, image_url: null,
    stored_path: null, post_url: null, post_caption: null, posted_at: null,
    likes_count: null, comments_count: null, views_count: null,
    follower_count: null, creator_tier: null, verified: null, context: null,
    post_hashtags: null, post_mentions: null, music: null, extras: null,
    surface_type: null, visible_text: null, false_positive_risk: null,
    people_count: null, setting: null, activity: null, gate: null,
    verify_verdict: null, verify_brand: null, verify_reason: null,
    sentiment: null, sentiment_score: null, sentiment_rationale: null,
    brand_id: 'stelz', detected: true, is_false_positive: null,
    ...partial,
  }
}

describe('sceneKeyFor', () => {
  it('buckets plain English activities', () => {
    expect(sceneKeyFor(row({ activity: 'partying' })).key).toBe('party')
    expect(sceneKeyFor(row({ activity: 'eating' })).key).toBe('food')
    expect(sceneKeyFor(row({ activity: 'playing football' })).key).toBe('sport')
  })

  it('buckets Dutch activities — most captions and scenes are Dutch', () => {
    expect(sceneKeyFor(row({ activity: 'op het terras' })).key).toBe('outdoor_leisure')
    expect(sceneKeyFor(row({ activity: 'vrijmibo met collegas' })).key).toBe('party')
    expect(sceneKeyFor(row({ activity: 'uitgaan in de stad' })).key).toBe('nightlife')
  })

  it('prefers the more specific scene when an activity matches two buckets', () => {
    // "drinking" alone is a social scene; at a festival it is a festival scene.
    // Getting this backwards would collapse the most valuable bucket into the
    // vaguest one.
    expect(sceneKeyFor(row({ activity: 'drinking' })).key).toBe('social')
    expect(sceneKeyFor(row({ activity: 'drinking at a festival' })).key).toBe('festival')
    expect(sceneKeyFor(row({ activity: 'drinking in a club' })).key).toBe('nightlife')
  })

  it('falls back to the context sentence when activity is empty or "none"', () => {
    // The model returns "none" often; context still names the scene.
    expect(sceneKeyFor(row({ activity: 'none', context: 'Friends at a festival, can in hand' })).key).toBe('festival')
    expect(sceneKeyFor(row({ activity: null, context: 'A can on a kitchen counter at home' })).key).toBe('home')
  })

  it('returns Unplaced when neither field says anything', () => {
    expect(sceneKeyFor(row({ activity: 'none', context: null })).key).toBe('other')
    expect(sceneKeyFor(row({ activity: 'unclear', context: '' })).key).toBe('other')
    expect(sceneKeyFor(row({})).key).toBe('other')
  })
})

describe('sceneBreakdown', () => {
  it('counts untagged hits per scene', () => {
    const rows = [
      // Untagged: no brand hashtag, no mention.
      row({ activity: 'partying', post_hashtags: ['weekend'] }),
      row({ activity: 'partying', post_hashtags: ['feestje'] }),
      // Tagged: carries the brand hashtag.
      row({ activity: 'partying', post_hashtags: ['stelz'] }),
    ]
    const [party] = sceneBreakdown(rows)
    expect(party.key).toBe('party')
    expect(party.total).toBe(3)
    expect(party.untagged).toBe(2)
    expect(party.untaggedPct).toBe(67)
  })

  it('sorts by untagged count, not by total', () => {
    // The point of the block is discovery. A big scene the brand is already
    // tagged in is worth less than a smaller one it is invisible in.
    const rows = [
      ...Array.from({ length: 10 }, () => row({ activity: 'partying', post_hashtags: ['stelz'] })),
      ...Array.from({ length: 3 }, () => row({ activity: 'festival', post_hashtags: ['zomer'] })),
    ]
    const out = sceneBreakdown(rows)
    expect(out[0].key).toBe('festival')
    expect(out[0].untagged).toBe(3)
    expect(out[1].untagged).toBe(0)
  })

  it('keeps Unplaced last however large it is', () => {
    const rows = [
      ...Array.from({ length: 50 }, () => row({ activity: 'none' })),
      row({ activity: 'festival' }),
    ]
    const out = sceneBreakdown(rows)
    expect(out[out.length - 1].key).toBe('other')
    expect(out[out.length - 1].total).toBe(50)
  })

  it('computes outdoor share only over rows where setting is known', () => {
    const rows = [
      row({ activity: 'festival', setting: 'outdoor' }),
      row({ activity: 'festival', setting: 'indoor' }),
      row({ activity: 'festival', setting: 'unclear' }),
      row({ activity: 'festival', setting: null }),
    ]
    const [scene] = sceneBreakdown(rows)
    expect(scene.total).toBe(4)
    expect(scene.outdoorPct).toBe(50)  // 1 of the 2 placed rows, not 1 of 4
  })

  it('reports outdoorPct as null when nothing is placed', () => {
    expect(sceneBreakdown([row({ activity: 'festival' })])[0].outdoorPct).toBeNull()
  })

  it('returns an empty list for no rows rather than throwing', () => {
    expect(sceneBreakdown([])).toEqual([])
  })
})


describe('subcultureBreakdown', () => {
  const scenes = {
    anna: [{ slug: 'vrijmibo', confidence: 1 }, { slug: 'student_life', confidence: 0.5 }],
    bob: [{ slug: 'vrijmibo', confidence: 0.67 }],
    carol: [],  // classified, matched nothing
  }
  const labels = { vrijmibo: '🍻 Vrijdagmiddagborrel', student_life: '🎓 Student life' }

  it('counts a hit once per scene its creator belongs to', () => {
    // Anna is in two scenes, so her one hit shows up in both. Rows adding up to
    // more than the hit count is intended, and the UI copy says so.
    const out = subcultureBreakdown([row({ creator_handle: 'anna' })], scenes, labels)
    expect(out.map((s) => s.key).sort()).toEqual(['student_life', 'vrijmibo'])
    expect(out.every((s) => s.total === 1)).toBe(true)
  })

  it('uses the seeded scene name, not the raw slug', () => {
    const out = subcultureBreakdown([row({ creator_handle: 'bob' })], scenes, labels)
    expect(out[0].label).toBe('🍻 Vrijdagmiddagborrel')
  })

  it('falls back to a readable label when the definition is missing', () => {
    const out = subcultureBreakdown([row({ creator_handle: 'bob' })], scenes, {})
    expect(out[0].label).toBe('vrijmibo')
  })

  it('counts untagged hits per scene', () => {
    const out = subcultureBreakdown([
      row({ creator_handle: 'bob', post_hashtags: ['weekend'] }),
      row({ creator_handle: 'bob', post_hashtags: ['stelz'] }),
    ], scenes, labels)
    expect(out[0].total).toBe(2)
    expect(out[0].untagged).toBe(1)
    expect(out[0].untaggedPct).toBe(50)
  })

  it('counts distinct creators per scene', () => {
    const out = subcultureBreakdown([
      row({ creator_handle: 'anna' }),
      row({ creator_handle: 'bob' }),
      row({ creator_handle: 'bob' }),
    ], scenes, labels)
    expect(out.find((s) => s.key === 'vrijmibo')!.creators).toBe(2)
  })

  it('is case-insensitive on the handle', () => {
    // Firestore stores the handle lowercased; detections do not guarantee it.
    const out = subcultureBreakdown([row({ creator_handle: 'ANNA' })], scenes, labels)
    expect(out.some((s) => s.key === 'vrijmibo')).toBe(true)
  })

  it('folds creators with no scene into Unplaced', () => {
    const out = subcultureBreakdown([
      row({ creator_handle: 'carol' }),      // classified, matched nothing
      row({ creator_handle: 'stranger' }),   // never classified
    ], scenes, labels)
    expect(out[out.length - 1].key).toBe('other')
    expect(out[out.length - 1].total).toBe(2)
  })

  it('keeps Unplaced last even when it dominates', () => {
    const rows = [
      ...Array.from({ length: 20 }, () => row({ creator_handle: 'stranger' })),
      row({ creator_handle: 'bob' }),
    ]
    const out = subcultureBreakdown(rows, scenes, labels)
    expect(out[out.length - 1].key).toBe('other')
    expect(out[0].key).toBe('vrijmibo')
  })

  it('returns an empty list for no rows', () => {
    expect(subcultureBreakdown([], scenes, labels)).toEqual([])
  })
})
