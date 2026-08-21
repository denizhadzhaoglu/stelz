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
  | 'near'         // the model saw Stëlz; the gate or the verifier overruled it
  | 'absent'       // analysed, nothing found
  | 'unanalysed'   // no detection document — includes an expired image link
  | 'rejected'     // a moderator said no

export const VERDICT_LABEL: Record<StoryVerdict, string> = {
  visible: 'Stëlz zichtbaar',
  small: 'Stëlz klein in beeld',
  near: 'Mogelijk Stëlz',
  absent: 'Geen Stëlz',
  unanalysed: 'Nog niet geanalyseerd',
  rejected: 'Afgekeurd',
}

/**
 * Did the detector argue with itself about this image?
 *
 * WHY THIS IS A STATE AND NOT A FOOTNOTE. Every overturned hit used to land in
 * the same bucket as a photo of an empty field: "Geen Stëlz". In one Lowlands
 * story the model read STELZ off a can in someone's hand and the verifier threw
 * it out with "No beverage container is visible in the target photo" — about a
 * picture containing four cans. That rejection may still be right, but it is a
 * judgement call the screen was hiding, and hiding it is what makes a brand
 * team stop believing the number.
 *
 * Derived, not stored, for production rows: `gate` and `verify_verdict` already
 * record the same fact, so nothing has to be backfilled. `near_miss` is the
 * explicit flag the local analyser writes.
 */
export function isNearMiss(d: DetectionRow): boolean {
  if (d.detected === true) return false
  if (d.near_miss === true) return true
  if (d.verify_verdict === 'rejected') return true
  return (d.gate ?? '').startsWith('rejected') || (d.gate ?? '').startsWith('demoted')
}

export type StoryRow = StoryPost & {
  verdict: StoryVerdict
  /** The detection behind the verdict, when there is one. Carries the mirrored
   *  Cloud Storage image, which outlives the post's signed CDN link. */
  detection: DetectionRow | null
  confidence: number | null
  /** How many images the model looked at for this story — 1 for a photo, cover
   *  plus sampled frames for a video, 0 when nothing has judged it. On screen
   *  as "beoordeeld op N beelden": the difference between "we found nothing"
   *  and "we never looked" is the whole point of the verdict column, and a
   *  count is the only thing that proves which one happened. */
  framesJudged: number
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
 *
 * Pass the RAW detections, not the output of dedupeByPost. This groups by
 * post_id itself with the same rule, and the size of each group is what says
 * how many images were examined — collapsing first throws that away.
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
      framesJudged: framesJudgedIn(group),
    }
  })
}

/**
 * Which pair of arrays the page should join.
 *
 * Extracted because getting it wrong is invisible: both pages used to pass
 * `preview ? [] : detections`, which silently discarded every locally produced
 * verdict and rendered analysed stories as "nog niet geanalyseerd". Nothing
 * failed, nothing logged — the screen just quietly under-reported. A preview
 * carries BOTH halves or neither, and that rule now lives in one tested place.
 */
export function storySource(
  previewPosts: StoryPost[] | null,
  previewDetections: DetectionRow[] | null,
  posts: StoryPost[],
  detections: DetectionRow[],
): { posts: StoryPost[]; detections: DetectionRow[]; preview: boolean } {
  if (previewPosts) {
    return { posts: previewPosts, detections: previewDetections ?? [], preview: true }
  }
  return { posts, detections, preview: false }
}

/** One document per examined frame is the production shape, so the group size
 *  is the count. A row that states its own `frames_judged` overrides that: a
 *  batched call produces one document for many frames, and trusting the
 *  document count there would report "1 beeld" for a thirteen-frame video. */
function framesJudgedIn(group: DetectionRow[]): number {
  if (group.length === 0) return 0
  const stated = group.reduce((sum, d) => sum + (d.frames_judged ?? 0), 0)
  return Math.max(stated, group.length)
}

/** Strongest evidence in the group: a rejection is decisive, then a hit, then a
 *  near miss, then the highest confidence among whatever is left.
 *
 *  Near misses outrank plain misses on purpose. A video contributes one row per
 *  frame; without this rule the single frame where the model saw a can would be
 *  represented by a frame of grass, and the disagreement would vanish exactly
 *  where it matters most. */
function pickBest(group: DetectionRow[]): DetectionRow | null {
  if (group.length === 0) return null
  const rejected = group.find((d) => d.is_false_positive === true)
  if (rejected) return rejected
  const hits = group.filter((d) => d.detected === true)
  if (hits.length > 0) {
    return hits.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
  }
  const near = group.filter(isNearMiss)
  const pool = near.length > 0 ? near : group
  return pool.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
}

function verdictFor(d: DetectionRow | null): StoryVerdict {
  if (!d) return 'unanalysed'
  if (d.is_false_positive === true) return 'rejected'
  if (d.detected !== true) return isNearMiss(d) ? 'near' : 'absent'
  // Reuses the same gate the feed and review queue use, so "zichtbaar" here
  // means what "clear" means everywhere else in the app.
  return detectionQuality(d).quality === 'clear' ? 'visible' : 'small'
}

/** Counts Stëlz as present. `small` is a real hit that the size gate demoted —
 *  excluding it would under-report the campaign, including it as "clearly
 *  visible" would over-claim, so the UI shows the split and this shows both.
 *
 *  `near` is deliberately NOT counted. An overturned hit is a question, not a
 *  sighting, and putting questions in the headline number is how a dashboard
 *  starts flattering its owner. It gets its own count instead. */
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
  near: number
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
  near: number
  unanalysed: number
  rejected: number
  /** Stories a verdict was actually reached on. */
  judged: number
  /** Images the model looked at across all of them — a video contributes its
   *  cover plus every sampled frame. This is the number that answers "is er
   *  echt naar gekeken?", which one story-level count cannot. */
  imagesSeen: number
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
    stories: 0, withStelz: 0, visible: 0, small: 0, near: 0, unanalysed: 0,
    pollVotes: 0, mentions: 0, links: 0, videoSeconds: 0, lastStoryAt: null,
  })
  for (const h of roster) byCreator.set(h.toLowerCase(), blank(h.toLowerCase()))

  const out: StoryRollup = {
    stories: 0, creatorsPosted: 0,
    withStelz: 0, visible: 0, small: 0, absent: 0, near: 0, unanalysed: 0, rejected: 0,
    judged: 0, imagesSeen: 0,
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
    out.imagesSeen += r.framesJudged
    if (r.verdict !== 'unanalysed') out.judged += 1
    if (r.verdict === 'visible') c.visible += 1
    if (r.verdict === 'small') c.small += 1
    if (r.verdict === 'near') c.near += 1
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
  if (r.judged <= 0) return null
  return (r.withStelz / r.judged) * 100
}
