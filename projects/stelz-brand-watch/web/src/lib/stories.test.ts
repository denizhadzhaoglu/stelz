import { describe, expect, it } from 'vitest'
import { isStory, storyChip, storyExpiry, storyFeed } from './stories'

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

describe('storyFeed', () => {
  const row = (expires: string, posted: string, type = 'story') =>
    ({ content_type: type as 'story', expires_at: expires, posted_at: posted })

  it('ignores everything that is not a story', () => {
    const out = storyFeed([row('2026-08-20T19:00:00Z', '2026-08-19T19:00:00Z', 'image')], NOW)
    expect(out.all).toEqual([])
  })

  it('puts live stories first, newest of each half at the front', () => {
    const oldLive = row('2026-08-20T14:00:00Z', '2026-08-19T14:00:00Z')
    const newLive = row('2026-08-20T20:00:00Z', '2026-08-19T20:00:00Z')
    const gone = row('2026-08-20T08:00:00Z', '2026-08-19T08:00:00Z')
    const out = storyFeed([gone, oldLive, newLive], NOW)
    expect(out.active).toEqual([newLive, oldLive])
    expect(out.expired).toEqual([gone])
    // Expired stories stay in the list: they are the only surviving copy of
    // something Instagram has already deleted.
    expect(out.all).toEqual([newLive, oldLive, gone])
  })

  it('sorts a missing posted_at to the back rather than dropping it', () => {
    const dated = row('2026-08-20T20:00:00Z', '2026-08-19T20:00:00Z')
    const undated = { content_type: 'story' as const, expires_at: '2026-08-20T20:00:00Z', posted_at: null }
    expect(storyFeed([undated, dated], NOW).active).toEqual([dated, undated])
  })
})
