// Stories: the surface the product is sold on and, until now, the one it did
// not have. A story is gone 24h after it is posted, so "we caught it before it
// disappeared" is the whole point — which means the UI has to say how long is
// left, and has to keep showing the ones that already expired.

import type { DetectionRow } from './types'

export function isStory(d: Pick<DetectionRow, 'content_type'>): boolean {
  return d.content_type === 'story'
}

export type StoryExpiry = {
  expired: boolean
  hoursLeft: number | null
  /** Ready to render, Dutch. */
  label: string
}

export function storyExpiry(
  d: Pick<DetectionRow, 'content_type' | 'expires_at'>,
  now = Date.now(),
): StoryExpiry | null {
  if (!isStory(d)) return null
  if (!d.expires_at) return { expired: false, hoursLeft: null, label: 'Story' }
  const t = new Date(d.expires_at).getTime()
  if (Number.isNaN(t)) return { expired: false, hoursLeft: null, label: 'Story' }

  const msLeft = t - now
  if (msLeft <= 0) {
    // Not hidden: a story we caught and Instagram no longer has is the most
    // valuable row in the feed, not a stale one.
    return { expired: true, hoursLeft: 0, label: 'Story · verlopen' }
  }
  const hoursLeft = msLeft / 3_600_000
  if (hoursLeft < 1) {
    return { expired: false, hoursLeft, label: `Story · nog ${Math.max(1, Math.round(msLeft / 60_000))} min` }
  }
  return { expired: false, hoursLeft, label: `Story · nog ${Math.round(hoursLeft)}u` }
}

/** Short form for the strip, where the tile already says "story". */
export function storyChip(e: StoryExpiry): string {
  return e.label.replace(/^Story · /, '').replace(/^Story$/, '—')
}

type StoryRow = Pick<DetectionRow, 'content_type' | 'expires_at' | 'posted_at'>

/**
 * Split scraped stories into what is still live and what has already gone.
 *
 * Both halves are kept and both are shown. An expired story is not stale data:
 * it is the only surviving copy of something Instagram has already deleted,
 * which is the entire reason for scraping stories at all. Live ones lead
 * because they are the ones you can still open on Instagram and react to.
 */
export function storyFeed<T extends StoryRow>(rows: T[], now = Date.now()): {
  active: T[]
  expired: T[]
  all: T[]
} {
  const active: T[] = []
  const expired: T[] = []
  for (const r of rows) {
    const e = storyExpiry(r, now)
    if (!e) continue
    ;(e.expired ? expired : active).push(r)
  }
  const newestFirst = (a: T, b: T) =>
    (b.posted_at ? Date.parse(b.posted_at) : 0) - (a.posted_at ? Date.parse(a.posted_at) : 0)
  active.sort(newestFirst)
  expired.sort(newestFirst)
  return { active, expired, all: [...active, ...expired] }
}
