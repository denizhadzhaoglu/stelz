// Tests for the unified sound aggregation.
//
// The case that justifies the module: two ORIGINAL sounds with the same title
// and different musicIds must stay two sounds. The community profiles used to
// key by title alone and merged them — so the dashboard card (keyed by id) and
// the profiles could report different counts for what looked like one sound.

import { describe, expect, it } from 'vitest'
import { rollupSound, soundHref, soundKey, soundLabel, tallySounds } from './sounds'
import type { DetectionMusic, DetectionRow } from './types'

const row = (p: Partial<DetectionRow>): DetectionRow => ({
  detection_id: Math.random().toString(36).slice(2),
  detected: true,
  creator_handle: 'someone',
  platform: 'tiktok',
  ...p,
} as DetectionRow)

const music = (p: Partial<DetectionMusic>): DetectionMusic => ({ ...p })

describe('soundKey', () => {
  it('prefers musicId — the only stable identity', () => {
    expect(soundKey(music({ musicId: '123', title: 'x', artist: 'y' }))).toBe('123')
  })

  it('falls back to title|artist for IG reels (no musicId)', () => {
    expect(soundKey(music({ title: 'Zomer Hit', artist: 'DJ A' }))).toBe('Zomer Hit|DJ A')
  })

  it('returns null for unidentifiable tracks — the "(untitled)" guard', () => {
    // The old key here was the literal string "|", which is not blank, so 306
    // unreadable tracks pooled into one top-of-chart bucket.
    expect(soundKey(music({}))).toBeNull()
    expect(soundKey(music({ title: '   ' }))).toBeNull()
    expect(soundKey(null)).toBeNull()
    expect(soundKey(undefined)).toBeNull()
  })

  it('keeps two same-titled original sounds apart when ids differ', () => {
    const a = soundKey(music({ musicId: 'a1', title: 'original sound' }))
    const b = soundKey(music({ musicId: 'b2', title: 'original sound' }))
    expect(a).not.toBe(b)
  })
})

describe('soundLabel', () => {
  it('uses the title, falling back to Original sound', () => {
    expect(soundLabel(music({ title: 'Belter' }))).toBe('Belter')
    expect(soundLabel(music({ musicId: 'x' }))).toBe('Original sound')
  })
})

describe('soundHref', () => {
  it('URL-encodes keys with arbitrary characters', () => {
    expect(soundHref('Zomer Hit|DJ A/B')).toBe('/sounds/Zomer%20Hit%7CDJ%20A%2FB')
  })
})

describe('tallySounds', () => {
  const rows = [
    row({ music: music({ musicId: 'a1', title: 'Hit A' }), creator_handle: 'anna' }),
    row({ music: music({ musicId: 'a1', title: 'Hit A' }), creator_handle: 'bob' }),
    row({ music: music({ musicId: 'a1', title: 'Hit A' }), creator_handle: 'anna' }),
    row({ music: music({ musicId: 'b2', title: 'Hit B' }), creator_handle: 'carla' }),
    row({ music: music({}) }),                       // unidentifiable — excluded
    row({ music: null, creator_handle: 'dave' }),    // no music — excluded
    row({ detected: false, music: music({ musicId: 'a1' }) }), // miss — excluded
  ]

  it('counts hits and DISTINCT creators per sound, sorted by hits', () => {
    const t = tallySounds(rows)
    expect(t.map((x) => x.key)).toEqual(['a1', 'b2'])
    expect(t[0].hits).toBe(3)
    expect(t[0].creators).toBe(2) // anna twice counts once
  })

  it('never emits an unidentifiable bucket', () => {
    expect(tallySounds(rows).some((t) => !t.key)).toBe(false)
  })

  it('handles an empty list', () => {
    expect(tallySounds([])).toEqual([])
  })
})

describe('rollupSound', () => {
  const rows = [
    row({
      music: music({ musicId: 'a1', title: 'Hit A', coverUrl: 'https://c/1.jpg' }),
      creator_handle: 'anna', likes_count: 100, follower_count: 5000,
      posted_at: '2026-08-01T10:00:00Z', sentiment: 'positive',
      extras: { author: { nickName: 'Anna!', avatar: 'https://a/1.jpg' } },
    } as Partial<DetectionRow>),
    row({
      music: music({ musicId: 'a1', title: 'Hit A', playUrl: 'https://p/1.mp3' }),
      creator_handle: 'anna', likes_count: 50, posted_at: '2026-08-02T10:00:00Z',
    }),
    row({
      music: music({ musicId: 'a1', title: 'Hit A' }),
      creator_handle: 'bob', platform: 'instagram', sentiment: null,
    }),
  ]

  it('rolls up hits, platforms and creators sorted by hits', () => {
    const r = rollupSound(rows, 'a1')!
    expect(r.hits).toBe(3)
    expect(r.platforms).toEqual({ instagram: 1, tiktok: 2 })
    expect(r.creators[0].handle).toBe('anna')
    expect(r.creators[0].hits).toBe(2)
    expect(r.creators[0].likes).toBe(150)
  })

  it('carries author chips and media urls from whichever row has them', () => {
    const r = rollupSound(rows, 'a1')!
    expect(r.creators[0].avatar).toBe('https://a/1.jpg')
    expect(r.coverUrl).toBe('https://c/1.jpg')
    expect(r.playUrl).toBe('https://p/1.mp3')
  })

  it('treats unscored sentiment as unscored, never neutral', () => {
    const r = rollupSound(rows, 'a1')!
    expect(r.sentiment.positive).toBe(1)
    expect(r.sentiment.neutral).toBe(0)
    expect(r.sentiment.unscored).toBe(2)
  })

  it('returns null for an unknown key — the page shows not-found, not an empty shell', () => {
    expect(rollupSound(rows, 'nope')).toBeNull()
  })
})

// ── dedupeByPost music merge (lives in types.ts, tested here with the sounds
// it protects) ────────────────────────────────────────────────────────────
import { dedupeByPost } from './types'

describe('dedupeByPost music merge', () => {
  it('keeps the post music when a music-less carousel child wins on confidence', () => {
    const parent = row({
      detection_id: 'instagram_p1_a', post_id: 'instagram_p1',
      confidence: 0.7, music: music({ musicId: 'a1', title: 'Hit A' }),
    })
    const child = row({
      detection_id: 'instagram_p1_2_b', post_id: 'instagram_p1_2',
      confidence: 0.95, music: null,
    })
    const [merged] = dedupeByPost([parent, child])
    // Without the merge this is null and the sound silently vanishes from
    // every aggregation — the drill-down would count fewer than the card.
    expect(merged.music?.musicId).toBe('a1')
    expect(merged.confidence).toBe(0.95) // best still wins everything else
  })

  it('leaves music null when no sibling has any', () => {
    const a = row({ detection_id: 'instagram_p2_a', post_id: 'instagram_p2', confidence: 0.9, music: null })
    expect(dedupeByPost([a])[0].music).toBeNull()
  })
})
