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
  return expiryAt(d.expires_at, now)
}

/** The countdown itself, on a bare timestamp. One implementation, so the strip,
 *  the feed card and the stories page cannot drift apart on what "verlopen"
 *  means or on where the hour/minute boundary sits. */
export function expiryAt(expiresAt: string | null | undefined, now = Date.now()): StoryExpiry {
  if (!expiresAt) return { expired: false, hoursLeft: null, label: 'Story' }
  const t = new Date(expiresAt).getTime()
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

/** Anything with a story's two timestamps — a StoryRow from storyStats today,
 *  and whatever else needs the same split tomorrow. */
type Expiring = { expiresAt: string | null; postedAt: string | null }

/**
 * Split captured stories into what is still live and what has already gone.
 *
 * Both halves are kept and both are shown. An expired story is not stale data:
 * it is the only surviving copy of something Instagram has already deleted,
 * which is the entire reason for capturing stories at all. Live ones lead
 * because they are the ones you can still open on Instagram and react to.
 */
export function splitByExpiry<T extends Expiring>(rows: T[], now = Date.now()): {
  active: T[]
  expired: T[]
  all: T[]
} {
  const active: T[] = []
  const expired: T[] = []
  for (const r of rows) {
    (expiryAt(r.expiresAt, now).expired ? expired : active).push(r)
  }
  const newestFirst = (a: T, b: T) =>
    (b.postedAt ? Date.parse(b.postedAt) : 0) - (a.postedAt ? Date.parse(a.postedAt) : 0)
  active.sort(newestFirst)
  expired.sort(newestFirst)
  return { active, expired, all: [...active, ...expired] }
}
