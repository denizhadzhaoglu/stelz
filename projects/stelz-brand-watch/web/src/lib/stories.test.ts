import { describe, expect, it } from 'vitest'
import { isStory, storyExpiry } from './stories'

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
