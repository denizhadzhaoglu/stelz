// Community profiles — lib/communities.ts
//
// This module exists to answer "what kind of people", which is exactly the
// question where a tool is most tempted to make something up. The tests that
// matter are therefore mostly about restraint: what it must NOT claim when the
// data isn't there.

import { describe, it, expect } from 'vitest'
import { communityProfiles, selfReportedAge, oneLineSummary } from './communities'
import type { DetectionRow } from './types'

function row(p: Partial<DetectionRow>): DetectionRow {
  return {
    detection_id: Math.random().toString(36).slice(2),
    creator_id: null, creator_handle: 'anna', creator_category: null,
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
    ...p,
  }
}
const scenes = { anna: [{ slug: 'vrijmibo', confidence: 1 }], bob: [{ slug: 'vrijmibo', confidence: 1 }] }
const many = (n: number, p: Partial<DetectionRow> = {}) => Array.from({ length: n }, () => row(p))

describe('selfReportedAge', () => {
  it('reads an age a person wrote themselves', () => {
    expect(selfReportedAge('21 yo | Amsterdam')).toBe(21)
    expect(selfReportedAge('24 years old, student')).toBe(24)
    expect(selfReportedAge('leeftijd: 19')).toBe(19)
  })

  it('does not guess from anything else', () => {
    // These all correlate with age and none of them state it. Reading an age
    // out of them would put a number on a real person that they never gave us.
    expect(selfReportedAge('student in Groningen')).toBeNull()
    expect(selfReportedAge('class of 2003')).toBeNull()
    expect(selfReportedAge('born to party')).toBeNull()
    expect(selfReportedAge('mom of 3')).toBeNull()
    expect(selfReportedAge(null)).toBeNull()
  })

  it('rejects numbers that cannot be an adult social-media age', () => {
    expect(selfReportedAge('12 years old')).toBeNull()
    expect(selfReportedAge('99 years old')).toBeNull()
  })

  it('does not mistake a follower count or a year for an age', () => {
    expect(selfReportedAge('2004')).toBeNull()
    expect(selfReportedAge('10k followers')).toBeNull()
  })
})

describe('communityProfiles', () => {
  it('drops scenes too small to describe', () => {
    // Two posts is an anecdote; printed next to a scene of two hundred it
    // reads as an equal finding.
    const out = communityProfiles([row({}), row({})], scenes)
    expect(out).toEqual([])
  })

  it('counts hits, untagged and distinct creators', () => {
    const out = communityProfiles([
      ...many(3, { creator_handle: 'anna', post_hashtags: ['vrijmibo'] }),
      ...many(2, { creator_handle: 'bob', post_hashtags: ['stelz'] }),
    ], scenes)
    expect(out[0].hits).toBe(5)
    expect(out[0].untagged).toBe(3)
    expect(out[0].creators).toBe(2)
  })

  it('excludes brand hashtags from "what else they post about"', () => {
    const out = communityProfiles(
      many(4, { post_hashtags: ['stelz', 'vrijmibo', 'drinkstelz'] }), scenes)
    expect(out[0].topHashtags.map((h) => h.label)).toEqual(['vrijmibo'])
  })

  it('uses medians, so one big account cannot speak for the room', () => {
    const out = communityProfiles([
      row({ creator_handle: 'anna', follower_count: 400000 }),
      row({ creator_handle: 'bob', follower_count: 900 }),
      row({ creator_handle: 'bob', follower_count: 900 }),
      row({ creator_handle: 'anna', follower_count: 400000 }),
    ], { anna: scenes.anna, bob: scenes.bob })
    // Mean would be ~200k and describe neither creator.
    expect(out[0].medianFollowers).toBe(200450)
    expect(out[0].followersKnownFor).toBe(2)
  })

  it('reports how many creators the follower figure is based on', () => {
    const out = communityProfiles([
      ...many(3, { creator_handle: 'anna', follower_count: 1000 }),
      ...many(3, { creator_handle: 'bob' }),  // unknown
    ], scenes)
    expect(out[0].creators).toBe(2)
    expect(out[0].followersKnownFor).toBe(1)
  })

  it('leaves followers null when nothing is known rather than reporting zero', () => {
    const out = communityProfiles(many(4), scenes)
    expect(out[0].medianFollowers).toBeNull()
    expect(out[0].followersKnownFor).toBe(0)
  })

  it('ignores placeholder activities', () => {
    const out = communityProfiles([
      ...many(3, { activity: 'none' }),
      ...many(3, { activity: 'borrelen' }),
    ], scenes)
    expect(out[0].topActivities.map((a) => a.label)).toEqual(['borrelen'])
  })

  it('counts sentiment only over scored posts', () => {
    const out = communityProfiles([
      ...many(3, { sentiment: 'positive' }),
      ...many(4, {}),  // not scored yet
    ], scenes)
    expect(out[0].sentiment.scored).toBe(3)
    expect(out[0].sentiment.positive).toBe(3)
    expect(out[0].sentiment.neutral).toBe(0)
  })

  it('withholds a peak day until there are enough dated posts to have one', () => {
    const friday = '2026-08-14T18:00:00Z'
    expect(communityProfiles(many(3, { posted_at: friday }), scenes)[0].peakDay).toBeNull()
    const out = communityProfiles(many(6, { posted_at: friday }), scenes)
    expect(out[0].peakDay).toEqual({ day: 5, pct: 100 })
  })

  it('pools unidentifiable sounds nowhere', () => {
    const out = communityProfiles([
      ...many(3, { music: { title: null, artist: null, musicId: null } }),
      ...many(3, { music: { title: 'Zomer', musicId: 'z1' } }),
    ], scenes)
    expect(out[0].topSounds.map((s) => s.label)).toEqual(['Zomer'])
  })

  it('ranks scenes by untagged reach', () => {
    const two = {
      anna: [{ slug: 'vrijmibo', confidence: 1 }],
      bob: [{ slug: 'festivals_events', confidence: 1 }],
    }
    const out = communityProfiles([
      ...many(8, { creator_handle: 'anna', post_hashtags: ['stelz'] }),   // all tagged
      ...many(4, { creator_handle: 'bob', post_hashtags: ['zomer'] }),    // all untagged
    ], two)
    expect(out[0].key).toBe('festivals_events')
  })

  it('falls back to per-photo scenes when no subculture data exists', () => {
    const out = communityProfiles(many(4, { activity: 'at a festival' }), {})
    expect(out[0].key).toBe('festival')
  })

  it('never emits the Unplaced bucket as a community', () => {
    // "Unplaced" is a gap in our data, not a group of people. It belongs in a
    // coverage note, never in a list of communities to go and talk to.
    const out = communityProfiles(many(9, { creator_handle: 'stranger' }), scenes)
    expect(out.map((p) => p.key)).not.toContain('other')
  })
})

describe('oneLineSummary', () => {
  const base = communityProfiles(many(6, {
    activity: 'borrelen', posted_at: '2026-08-14T18:00:00Z', follower_count: 2500,
  }), scenes)[0]

  it('describes the scene from parts that exist', () => {
    const line = oneLineSummary(base)!
    expect(line).toContain('borrelen')
    expect(line).toContain('Fridays')
    expect(line).toContain('2,500')
  })

  it('returns null rather than padding when there is nothing to say', () => {
    const empty = communityProfiles(many(4), scenes)[0]
    expect(oneLineSummary(empty)).toBeNull()
  })
})
