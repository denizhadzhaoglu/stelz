// Regressions for four things that made the dashboard look broken in a demo.
//
// None of them was a crash; all four were the same mistake in different places
// — rendering ABSENT data as though it were MEASURED data. "0 followers" for a
// creator whose follower count was never scraped, "-100%" for a creator whose
// only crime is that we haven't scanned recently, "NO IMAGE" where there was
// never an image to load, and one "(untitled)" row that was really every
// unidentifiable track added together.
//
// The logic lives inline in pages/Home.tsx; these tests cover the exact
// expressions, so they pin the behaviour rather than the rendering.

import { describe, it, expect } from 'vitest'
import { formatFollowers } from '../components/ui'

// ── Growth, as computed for the leaderboard ──────────────────────────
type Growth = number | 'new' | null
function growthFor(recent: number, prior: number): Growth {
  return recent === 0 ? null : prior === 0 ? 'new' : ((recent - prior) / prior) * 100
}

describe('leaderboard growth', () => {
  it('says nothing when the creator was quiet in the recent half', () => {
    // THE demo bug. Scans run on demand, so on any day without a fresh scan
    // every creator has recent=0 and the old formula printed a red -100% on
    // every row — a statement about our scan schedule dressed up as a
    // statement about the brand collapsing.
    expect(growthFor(0, 12)).toBeNull()
    expect(growthFor(0, 1)).toBeNull()
  })

  it('never returns -100', () => {
    for (let prior = 1; prior <= 50; prior++) {
      expect(growthFor(0, prior)).not.toBe(-100)
    }
  })

  it('marks a creator with no prior activity as new, not +100%', () => {
    // +100% invites the reader to compare it with a real percentage elsewhere
    // in the same column. "new" is the thing that actually happened.
    expect(growthFor(3, 0)).toBe('new')
  })

  it('computes a real percentage when both halves have data', () => {
    expect(growthFor(6, 3)).toBe(100)
    expect(growthFor(3, 6)).toBe(-50)
    expect(growthFor(4, 4)).toBe(0)
  })

  it('says nothing for a creator with no activity at all', () => {
    expect(growthFor(0, 0)).toBeNull()
  })
})

// ── Follower counts ──────────────────────────────────────────────────

describe('formatFollowers', () => {
  it('returns null for the values that mean "not scraped"', () => {
    // Instagram's hashtag endpoint returns no follower count, so most
    // detections carry null. Printing "0 followers" asserts something false.
    expect(formatFollowers(null)).toBeNull()
    expect(formatFollowers(undefined)).toBeNull()
    expect(formatFollowers(0)).toBeNull()
  })

  it('formats a real count', () => {
    expect(formatFollowers(1234)).toBe('1,234')
  })
})

// ── Top sounds ───────────────────────────────────────────────────────

type Music = { musicId?: string | null; title?: string | null; artist?: string | null }

/** Mirrors the guard + key in DashboardSection's sound tally. */
function tallySounds(tracks: Music[]): { label: string; count: number }[] {
  const acc = new Map<string, { label: string; count: number }>()
  for (const m of tracks) {
    if (!m.musicId && !(m.title || '').trim()) continue
    const key = m.musicId || `${m.title || ''}|${m.artist || ''}`
    if (!key.trim()) continue
    const cur = acc.get(key) ?? { label: m.title || 'Original sound', count: 0 }
    cur.count += 1
    acc.set(key, cur)
  }
  return [...acc.values()].sort((a, b) => b.count - a.count)
}

describe('top sounds', () => {
  it('drops tracks with no identity instead of pooling them', () => {
    // The reported symptom: "Top sound is (untitled) with 306 hits". The old
    // key for a track with no id, title or artist was the literal string "|",
    // which is not blank — so the skip never fired and every unreadable track
    // in the data set landed in one bucket that then topped the chart.
    const out = tallySounds([
      { musicId: null, title: null, artist: null },
      { musicId: null, title: '', artist: '' },
      { musicId: null, title: '   ', artist: null },
      { musicId: 'm1', title: 'Real Song', artist: 'Someone' },
    ])
    expect(out).toHaveLength(1)
    expect(out[0].label).toBe('Real Song')
  })

  it('keeps a track that has an id but no title, and does not merge two of them', () => {
    // These are identifiable and genuinely distinct — TikTok original audio.
    const out = tallySounds([
      { musicId: 'a', title: null },
      { musicId: 'a', title: null },
      { musicId: 'b', title: null },
    ])
    expect(out.map((s) => s.count)).toEqual([2, 1])
    expect(out.every((s) => s.label === 'Original sound')).toBe(true)
  })

  it('groups by title when there is no id', () => {
    const out = tallySounds([
      { title: 'Zomer', artist: 'X' },
      { title: 'Zomer', artist: 'X' },
    ])
    expect(out).toEqual([{ label: 'Zomer', count: 2 }])
  })

  it('returns nothing when no track is identifiable', () => {
    expect(tallySounds([{ musicId: null, title: null }])).toEqual([])
  })
})
