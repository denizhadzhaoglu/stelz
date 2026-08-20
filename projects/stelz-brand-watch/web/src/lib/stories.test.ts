import { describe, expect, it } from 'vitest'
import { isStory, splitByExpiry, storyChip, storyExpiry } from './stories'

const NOW = Date.parse('2026-08-20T12:00:00Z')
const story = (expires: string | null) => ({ content_type: 'story' as const, expires_at: expires })

describe('isStory', () => {
  it('only matches stories', () => {
    expect(isStory({ content_type: 'story' })).toBe(true)
    expect(isStory({ content_type: 'video' })).toBe(false)
    expect(isStory({ content_type: null })).toBe(false)
    expect(isStory({ content_type: undefined })).toBe(false)
  })
})

describe('storyExpiry', () => {
  it('returns nothing for a normal post', () => {
    expect(storyExpiry({ content_type: 'image', expires_at: null }, NOW)).toBeNull()
  })

  it('counts down in hours', () => {
    const out = storyExpiry(story('2026-08-20T19:00:00Z'), NOW)
    expect(out?.expired).toBe(false)
    expect(out?.label).toBe('Story · nog 7u')
  })

  it('switches to minutes in the last hour', () => {
    expect(storyExpiry(story('2026-08-20T12:40:00Z'), NOW)?.label).toBe('Story · nog 40 min')
  })

  it('marks an expired story instead of hiding it', () => {
    // A story Instagram no longer has is the most valuable row in the feed.
    const out = storyExpiry(story('2026-08-20T09:00:00Z'), NOW)
    expect(out?.expired).toBe(true)
    expect(out?.label).toBe('Story · verlopen')
  })

  it('still labels a story with no expiry recorded', () => {
    expect(storyExpiry(story(null), NOW)?.label).toBe('Story')
    expect(storyExpiry(story('rommel'), NOW)?.label).toBe('Story')
  })

  it('is timezone-independent', () => {
    // Injected now + absolute timestamps: no reliance on the runner's TZ.
    const out = storyExpiry(story('2026-08-20T13:00:00Z'), Date.parse('2026-08-20T12:00:00Z'))
    expect(out?.hoursLeft).toBeCloseTo(1, 5)
  })
})

describe('storyChip', () => {
  it('drops the word the tile already carries', () => {
    expect(storyChip(storyExpiry(story('2026-08-20T19:00:00Z'), NOW)!)).toBe('nog 7u')
    expect(storyChip(storyExpiry(story('2026-08-20T09:00:00Z'), NOW)!)).toBe('verlopen')
    expect(storyChip(storyExpiry(story(null), NOW)!)).toBe('—')
  })
})

describe('splitByExpiry', () => {
  const row = (expiresAt: string | null, postedAt: string | null) => ({ expiresAt, postedAt })

  it('puts live stories first, newest of each half at the front', () => {
    const oldLive = row('2026-08-20T14:00:00Z', '2026-08-19T14:00:00Z')
    const newLive = row('2026-08-20T20:00:00Z', '2026-08-19T20:00:00Z')
    const gone = row('2026-08-20T08:00:00Z', '2026-08-19T08:00:00Z')
    const out = splitByExpiry([gone, oldLive, newLive], NOW)
    expect(out.active).toEqual([newLive, oldLive])
    expect(out.expired).toEqual([gone])
    // Expired stories stay in the list: they are the only surviving copy of
    // something Instagram has already deleted.
    expect(out.all).toEqual([newLive, oldLive, gone])
  })

  it('treats a story with no recorded expiry as live rather than dropping it', () => {
    const undated = row(null, '2026-08-19T20:00:00Z')
    expect(splitByExpiry([undated], NOW).active).toEqual([undated])
  })

  it('sorts a missing postedAt to the back rather than dropping it', () => {
    const dated = row('2026-08-20T20:00:00Z', '2026-08-19T20:00:00Z')
    const undated = row('2026-08-20T20:00:00Z', null)
    expect(splitByExpiry([undated, dated], NOW).active).toEqual([dated, undated])
  })
})
