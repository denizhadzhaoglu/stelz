// Stories: what we captured, where Stëlz was visible, and the numbers that are
// actually real.
//
// TWO SOURCES, ON PURPOSE. The story list comes from POSTS and the verdict
// comes from DETECTIONS. detect_image writes no detection document when the
// image fetch fails, and for stories that is common rather than exceptional —
// Instagram serves them from short-lived signed URLs. Driving this page off
// detections would silently drop precisely the story we failed to analyse,
// from a page whose whole claim is that it shows everything.
//
// THE VIEWING-FIGURES PROBLEM, stated once so the UI can state it too:
// Instagram shows story views to the account owner and to nobody else. Every
// item in the live payload carries `can_see_insights_as_brand: false`, and
// there is no view, viewer, reach or impression field anywhere in it. So there
// are exactly two honest numbers here:
//
//   * FOLLOWER BASE — the audience these creators have. Not views. Named
//     "bereik (volgers)" everywhere it appears, never "kijkers".
//   * POLL VOTES — public and exact. A vote requires a person who saw the
//     story, so it is a verified FLOOR on viewers, not an estimate. One
//     Lowlands story carried 18,412 of them.
//
// Anything else would be a guess dressed as a measurement, in a document the
// client reads. Pure functions over rows already fetched, same as
// lib/sounds.ts and lib/projects.ts — zero extra Firestore reads.

import type { StoryPost, CreatorProfile } from './firestore'
import type { DetectionRow } from './types'
import { detectionQuality } from './quality'

export type StoryVerdict =
  | 'visible'      // Stëlz clearly in frame
  | 'small'        // Stëlz found but demoted by the size gate
  | 'absent'       // analysed, nothing found
  | 'unanalysed'   // no detection document — includes an expired image link
  | 'rejected'     // a moderator said no

export const VERDICT_LABEL: Record<StoryVerdict, string> = {
  visible: 'Stëlz zichtbaar',
  small: 'Stëlz klein in beeld',
  absent: 'Geen Stëlz',
  unanalysed: 'Nog niet geanalyseerd',
  rejected: 'Afgekeurd',
}

export type StoryRow = StoryPost & {
  verdict: StoryVerdict
  /** The detection behind the verdict, when there is one. Carries the mirrored
   *  Cloud Storage image, which outlives the post's signed CDN link. */
  detection: DetectionRow | null
  confidence: number | null
}

/** The image to render: the mirrored copy first, because the story's own
 *  coverUrl is a signed link that dies within hours of capture. */
export function storyImage(row: StoryRow): string | null {
  return row.detection?.stored_path || row.detection?.image_url || row.coverUrl || null
}

/**
 * One row per captured story, with the best available verdict.
 *
 * A story can produce several detection documents — a video contributes its
 * cover plus up to six frames. The strongest evidence wins, so a can visible
 * in one frame of a fourteen-second story counts as visible.
 */
export function joinStories(posts: StoryPost[], detections: DetectionRow[]): StoryRow[] {
  const byPost = new Map<string, DetectionRow[]>()
  for (const d of detections) {
    const key = d.post_id
    if (!key) continue
    const arr = byPost.get(key)
    if (arr) arr.push(d)
    else byPost.set(key, [d])
  }

  return posts.map((p) => {
    const group = byPost.get(p.postId) ?? []
    const best = pickBest(group)
    return {
      ...p,
      detection: best,
      confidence: best?.confidence ?? null,
      verdict: verdictFor(best),
    }
  })
}

/** Strongest evidence in the group: a rejection is decisive, then a hit, then
 *  the highest confidence among whatever is left. */
function pickBest(group: DetectionRow[]): DetectionRow | null {
  if (group.length === 0) return null
  const rejected = group.find((d) => d.is_false_positive === true)
  if (rejected) return rejected
  const hits = group.filter((d) => d.detected === true)
  const pool = hits.length > 0 ? hits : group
  return pool.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
}

function verdictFor(d: DetectionRow | null): StoryVerdict {
  if (!d) return 'unanalysed'
  if (d.is_false_positive === true) return 'rejected'
  if (d.detected !== true) return 'absent'
  // Reuses the same gate the feed and review queue use, so "zichtbaar" here
  // means what "clear" means everywhere else in the app.
  return detectionQuality(d).quality === 'clear' ? 'visible' : 'small'
}

/** Counts Stëlz as present. `small` is a real hit that the size gate demoted —
 *  excluding it would under-report the campaign, including it as "clearly
 *  visible" would over-claim, so the UI shows the split and this shows both. */
export function isStelzStory(v: StoryVerdict): boolean {
  return v === 'visible' || v === 'small'
}

export type CreatorStoryStats = {
  handle: string
  fullName: string | null
  avatarUrl: string | null
  followers: number | null
  stories: number
  withStelz: number
  visible: number
  small: number
  unanalysed: number
  pollVotes: number
  mentions: number
  links: number
  videoSeconds: number
  lastStoryAt: string | null
}

export type StoryRollup = {
  stories: number
  creatorsPosted: number
  withStelz: number
  visible: number
  small: number
  absent: number
  unanalysed: number
  rejected: number
  /** Sum of follower counts over DISTINCT creators who posted. Audience size,
   *  not views — see the file header. */
  reach: number
  reachKnownFor: number
  /** Verified floor on viewers: every one of these is a person who voted. */
  pollVotes: number
  mentions: number
  links: number
  videoSeconds: number
  byCreator: CreatorStoryStats[]
  postedAts: string[]
}

/**
 * @param roster optional handles that SHOULD have posted. Members who posted
 *   nothing stay in byCreator with zeroes — a tracked creator producing
 *   silence is information, not a gap in the table.
 */
export function storyRollup(
  rows: StoryRow[],
  profiles: Record<string, CreatorProfile> = {},
  roster: string[] = [],
): StoryRollup {
  const byCreator = new Map<string, CreatorStoryStats>()
  const blank = (handle: string): CreatorStoryStats => ({
    handle,
    fullName: profiles[handle]?.fullName ?? null,
    avatarUrl: profiles[handle]?.avatarUrl ?? null,
    followers: profiles[handle]?.followerCount ?? null,
    stories: 0, withStelz: 0, visible: 0, small: 0, unanalysed: 0,
    pollVotes: 0, mentions: 0, links: 0, videoSeconds: 0, lastStoryAt: null,
  })
  for (const h of roster) byCreator.set(h.toLowerCase(), blank(h.toLowerCase()))

  const out: StoryRollup = {
    stories: 0, creatorsPosted: 0,
    withStelz: 0, visible: 0, small: 0, absent: 0, unanalysed: 0, rejected: 0,
    reach: 0, reachKnownFor: 0, pollVotes: 0, mentions: 0, links: 0,
    videoSeconds: 0, byCreator: [], postedAts: [],
  }

  for (const r of rows) {
    const h = (r.creatorHandle || '').toLowerCase()
    if (!h) continue
    const c = byCreator.get(h) ?? blank(h)
    byCreator.set(h, c)

    out.stories += 1
    c.stories += 1
    out[r.verdict] += 1
    if (r.verdict === 'visible') c.visible += 1
    if (r.verdict === 'small') c.small += 1
    if (r.verdict === 'unanalysed') c.unanalysed += 1
    if (isStelzStory(r.verdict)) { out.withStelz += 1; c.withStelz += 1 }

    out.pollVotes += r.pollVotes
    c.pollVotes += r.pollVotes
    out.mentions += r.mentions.length
    c.mentions += r.mentions.length
    out.links += r.linkUrls.length
    c.links += r.linkUrls.length
    const secs = r.videoDuration ?? 0
    out.videoSeconds += secs
    c.videoSeconds += secs

    if (r.postedAt) {
      out.postedAts.push(r.postedAt)
      if (!c.lastStoryAt || r.postedAt > c.lastStoryAt) c.lastStoryAt = r.postedAt
    }
  }

  for (const c of byCreator.values()) {
    if (c.stories > 0) {
      out.creatorsPosted += 1
      // Counted once per creator however many stories they posted: adding a
      // creator's followers per story would multiply the audience by their
      // posting rate, which is how "reach" numbers become fiction.
      if (c.followers && c.followers > 0) {
        out.reach += c.followers
        out.reachKnownFor += 1
      }
    }
  }

  out.byCreator = [...byCreator.values()].sort(
    (a, b) => b.withStelz - a.withStelz || b.stories - a.stories || a.handle.localeCompare(b.handle),
  )
  return out
}

/** Share of captured stories with Stëlz in them, or null when nothing analysed
 *  yet — a 0% that only means "we haven't looked" is a lie in a KPI box. */
export function stelzShare(r: StoryRollup): number | null {
  const judged = r.stories - r.unanalysed
  if (judged <= 0) return null
  return (r.withStelz / judged) * 100
}
