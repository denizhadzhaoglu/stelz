// The campaign across both platforms: what each creator posted, where, and
// where Stëlz was actually in frame.
//
// WHY THIS IS SEPARATE FROM storyStats.ts. Stories are one surface with one
// honest metric (poll votes). A campaign spans three surfaces that do not share
// a single number between them:
//
//   * IG story   — no view count exists at all; poll votes are the only floor.
//   * IG post    — likes and comments; a reel also reports plays, a photo does not.
//   * TikTok     — playCount, published. The FIRST real viewing figure anywhere
//                  in this product, and worth naming as such.
//
// THE RULE THAT MATTERS: metrics are never summed across surfaces. A TikTok
// play and a poll vote are not the same event, and adding them produces a
// "total reach" that means nothing while looking authoritative — which is
// exactly how these numbers become fiction in a deck. Every total here is
// per-surface, and the type makes the other thing hard to write by accident.

import type { DetectionRow } from './types'
import type { CreatorProfile } from './firestore'
import {
  isNearMiss, isStelzStory, VERDICT_LABEL, type StoryVerdict,
} from './storyStats'
import { detectionQuality } from './quality'

export { VERDICT_LABEL }

export type Surface = 'story' | 'post' | 'tiktok'

export const SURFACE_LABEL: Record<Surface, string> = {
  story: 'IG story',
  post: 'IG post',
  tiktok: 'TikTok',
}

/** What each surface actually publishes. Rendered next to every number so a
 *  reader never has to guess whether "12k" means people or taps. */
export const SURFACE_METRIC: Record<Surface, string> = {
  story: 'poll-stemmen (ondergrens kijkers)',
  post: 'likes',
  tiktok: 'weergaven',
}

/** One piece of content, before the verdict is attached. Mirrors what the
 *  archives and (after deploy) the posts collection hold. */
export type CampaignItem = {
  itemId: string
  platform: 'instagram' | 'tiktok'
  surface: Surface
  /** The PERSON. Rein is @rvdofficial on Instagram and @rinnavandoffoe on
   *  TikTok; keyed on the account he shows up as two creators and the roster
   *  of 28 reports 42, which makes "who delivered nothing" unanswerable. */
  creatorHandle: string
  /** The account it was actually posted from, kept for the link and the label. */
  platformHandle?: string
  url: string | null
  coverUrl: string | null
  videoUrl: string | null
  mediaType: 'image' | 'video'
  postedAt: string | null
  caption: string | null
  hashtags: string[]
  mentions: string[]
  videoDuration: number | null
  /** TikTok playCount, or an IG reel's plays. Null where the surface has no
   *  such number — never 0, which would read as "nobody watched". */
  views: number | null
  likes: number | null
  comments: number | null
  shares: number | null
  pollVotes: number | null
  isPaidPartnership: boolean
}

export type CampaignRow = CampaignItem & {
  verdict: StoryVerdict
  detection: DetectionRow | null
  confidence: number | null
  framesJudged: number
  /** The clip was never obtained; only its cover was judged. */
  coverOnly: boolean
}

/** Same join as joinStories, over items instead of story posts. Pass RAW
 *  detections — the number of documents per item is what says how many images
 *  were examined. */
export function joinCampaign(items: CampaignItem[], detections: DetectionRow[]): CampaignRow[] {
  const byItem = new Map<string, DetectionRow[]>()
  for (const d of detections) {
    if (!d.post_id) continue
    const arr = byItem.get(d.post_id)
    if (arr) arr.push(d)
    else byItem.set(d.post_id, [d])
  }
  return items.map((it) => {
    const group = byItem.get(it.itemId) ?? []
    const best = pickBest(group)
    return {
      ...it,
      detection: best,
      confidence: best?.confidence ?? null,
      verdict: verdictFor(best),
      framesJudged: framesJudgedIn(group),
      coverOnly: best?.cover_only === true,
    }
  })
}

function pickBest(group: DetectionRow[]): DetectionRow | null {
  if (group.length === 0) return null
  const rejected = group.find((d) => d.is_false_positive === true)
  if (rejected) return rejected
  const hits = group.filter((d) => d.detected === true)
  if (hits.length > 0) return hits.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
  const near = group.filter(isNearMiss)
  const pool = near.length > 0 ? near : group
  return pool.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
}

function verdictFor(d: DetectionRow | null): StoryVerdict {
  if (!d) return 'unanalysed'
  if (d.is_false_positive === true) return 'rejected'
  if (d.detected !== true) return isNearMiss(d) ? 'near' : 'absent'
  return detectionQuality(d).quality === 'clear' ? 'visible' : 'small'
}

function framesJudgedIn(group: DetectionRow[]): number {
  if (group.length === 0) return 0
  const stated = group.reduce((sum, d) => sum + (d.frames_judged ?? 0), 0)
  return Math.max(stated, group.length)
}

// ─────────────────────────── rollup ───────────────────────────

export type SurfaceStats = {
  items: number
  judged: number
  imagesSeen: number
  withStelz: number
  near: number
  unanalysed: number
  coverOnly: number
  /** The one metric this surface actually publishes. Null when it publishes
   *  none — a story has no view count and 0 would be a claim, not a blank. */
  metric: number | null
  lastPostedAt: string | null
}

const EMPTY: SurfaceStats = {
  items: 0, judged: 0, imagesSeen: 0, withStelz: 0, near: 0,
  unanalysed: 0, coverOnly: 0, metric: null, lastPostedAt: null,
}

export type CampaignCreator = {
  handle: string
  fullName: string | null
  avatarUrl: string | null
  followers: number | null
  bySurface: Record<Surface, SurfaceStats>
  /** Content items across every surface. Safe to add — these are counts of
   *  things, not audience measurements. */
  items: number
  withStelz: number
  near: number
  /** True when this creator is on the roster and posted nothing anywhere.
   *  Silence from someone being paid to post is a finding, not an empty row. */
  silent: boolean
}

export type CampaignRollup = {
  creators: CampaignCreator[]
  rosterSize: number
  delivered: number       // creators with at least one item
  silent: number
  items: number
  judged: number
  imagesSeen: number
  withStelz: number
  near: number
  unanalysed: number
  bySurface: Record<Surface, SurfaceStats>
  /** Named, not "reach": TikTok is the only surface here that publishes views.
   *  Kept out of every other total on purpose. */
  tiktokViews: number
  pollVotes: number
  postLikes: number
}

const SURFACES: Surface[] = ['story', 'post', 'tiktok']

function blankSurfaces(): Record<Surface, SurfaceStats> {
  return { story: { ...EMPTY }, post: { ...EMPTY }, tiktok: { ...EMPTY } }
}

/** The metric a surface publishes, or null when it publishes none. */
export function metricFor(r: CampaignRow): number | null {
  if (r.surface === 'tiktok') return r.views
  if (r.surface === 'post') return r.likes
  return r.pollVotes && r.pollVotes > 0 ? r.pollVotes : null
}

/**
 * @param roster handles that SHOULD have posted. A member who posted nothing
 *   stays in the table at zero — that is the row a brand most needs to see.
 */
export function campaignRollup(
  rows: CampaignRow[],
  profiles: Record<string, CreatorProfile> = {},
  roster: string[] = [],
): CampaignRollup {
  const byCreator = new Map<string, CampaignCreator>()
  const blank = (handle: string): CampaignCreator => ({
    handle,
    fullName: profiles[handle]?.fullName ?? null,
    avatarUrl: profiles[handle]?.avatarUrl ?? null,
    followers: profiles[handle]?.followerCount ?? null,
    bySurface: blankSurfaces(),
    items: 0, withStelz: 0, near: 0, silent: true,
  })
  for (const h of roster) byCreator.set(h.toLowerCase(), blank(h.toLowerCase()))

  const out: CampaignRollup = {
    creators: [], rosterSize: roster.length, delivered: 0, silent: 0,
    items: 0, judged: 0, imagesSeen: 0, withStelz: 0, near: 0, unanalysed: 0,
    bySurface: blankSurfaces(),
    tiktokViews: 0, pollVotes: 0, postLikes: 0,
  }

  const bump = (s: SurfaceStats, r: CampaignRow) => {
    s.items += 1
    s.imagesSeen += r.framesJudged
    if (r.verdict === 'unanalysed') s.unanalysed += 1
    else s.judged += 1
    if (isStelzStory(r.verdict)) s.withStelz += 1
    if (r.verdict === 'near') s.near += 1
    if (r.coverOnly) s.coverOnly += 1
    const m = metricFor(r)
    if (m != null) s.metric = (s.metric ?? 0) + m
    if (r.postedAt && (!s.lastPostedAt || r.postedAt > s.lastPostedAt)) {
      s.lastPostedAt = r.postedAt
    }
  }

  for (const r of rows) {
    const h = (r.creatorHandle || '').toLowerCase()
    if (!h) continue
    const c = byCreator.get(h) ?? blank(h)
    byCreator.set(h, c)
    c.silent = false
    c.items += 1
    if (isStelzStory(r.verdict)) c.withStelz += 1
    if (r.verdict === 'near') c.near += 1
    bump(c.bySurface[r.surface], r)
    bump(out.bySurface[r.surface], r)

    out.items += 1
    out.imagesSeen += r.framesJudged
    if (r.verdict === 'unanalysed') out.unanalysed += 1
    else out.judged += 1
    if (isStelzStory(r.verdict)) out.withStelz += 1
    if (r.verdict === 'near') out.near += 1

    // Kept in three separate fields rather than one "reach". Nothing in this
    // file adds them together, and nothing downstream should either.
    if (r.surface === 'tiktok') out.tiktokViews += r.views ?? 0
    if (r.surface === 'story') out.pollVotes += r.pollVotes ?? 0
    if (r.surface === 'post') out.postLikes += r.likes ?? 0
  }

  for (const c of byCreator.values()) {
    if (c.silent) out.silent += 1
    else out.delivered += 1
  }

  out.creators = [...byCreator.values()].sort(
    (a, b) => b.withStelz - a.withStelz || b.items - a.items || a.handle.localeCompare(b.handle),
  )
  return out
}

/** Share of judged items containing Stëlz, or null when nothing was judged —
 *  a 0% that only means "we have not looked" is a lie in a KPI box. */
export function stelzShare(r: { judged: number; withStelz: number }): number | null {
  if (r.judged <= 0) return null
  return (r.withStelz / r.judged) * 100
}

export { SURFACES }
