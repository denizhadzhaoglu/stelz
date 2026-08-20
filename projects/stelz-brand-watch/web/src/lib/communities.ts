// Community profiles — "what kind of people is this brand actually reaching".
//
// A bar chart of scene names answers "where"; it does not answer the question a
// brand manager actually asks, which is closer to "who are these people and
// what is going on in their life". This module assembles, per scene, the
// portrait the data can honestly support.
//
// WHAT WE CAN AND CANNOT SAY
// --------------------------
// We can say: which scenes people belong to, what else they post about, what
// music they use, what they are doing in the photos, indoors or out, which
// cities show up, when they post, how the captions talk about the brand, and
// how big and engaged their following is.
//
// We CANNOT say age or gender. Nothing in the pipeline collects either, and
// neither can be read off a photo or a handle without guessing about real
// people and presenting the guess as data. Where a bio literally states an age
// ("21 | Amsterdam") we read that and label it as self-reported; where it does
// not, the profile omits age entirely rather than inferring one. That is a
// deliberate limit, not an oversight — see AGE_IN_BIO below.
//
// EVERY FIELD IS OPTIONAL. Instagram posts carried no owner data at all until
// recently and TikTok location is sparse, so a profile renders whatever it has
// and stays silent about the rest. Silence is the honest rendering of absence;
// a zero is not.

import { classifySignal, isBrandTag, BRAND_OWNED_HANDLES } from './signal'
import { sceneKeyFor } from './scenes'
import type { CreatorSceneMap } from './scenes'
import type { DetectionRow } from './types'

export type Ranked = { label: string; count: number }

export type CommunityProfile = {
  key: string
  label: string
  /** Posts from creators in this scene. */
  hits: number
  /** Of those, posts carrying no brand hashtag, mention or brand account. */
  untagged: number
  untaggedPct: number
  /** Distinct creators contributing. */
  creators: number
  /** Median follower count among creators where we know it, else null. */
  medianFollowers: number | null
  /** Followers are known for this many of the scene's creators. */
  followersKnownFor: number
  /** Median likes per post, a reach-independent read on engagement. */
  medianLikes: number | null
  /** What else they post about — brand tags excluded. */
  topHashtags: Ranked[]
  /** Sounds used on their videos. */
  topSounds: Ranked[]
  /** What is happening in the photos. */
  topActivities: Ranked[]
  /** Where the cans show up: cafe, festival, kitchen… */
  topSettings: Ranked[]
  /** Cities, where the post carried a location. */
  topCities: Ranked[]
  /** Busiest posting day, as an index 0=Sun..6=Sat, plus its share. */
  peakDay: { day: number; pct: number } | null
  /** Caption sentiment across the scene, scored posts only. */
  sentiment: { positive: number; neutral: number; negative: number; promotional: number; scored: number }
  /** Self-reported ages found in bios. Never inferred — see AGE_IN_BIO. */
  selfReportedAges: number[]
  /** A few creators to put faces to the scene. */
  sampleCreators: { handle: string; avatar: string | null; hits: number; followers: number | null }[]
}

/**
 * Ages people put in their own bio: "21", "21yo", "'03", "est. 2003".
 *
 * Only forms where a human plainly wrote their age or birth year count. We do
 * NOT try to infer age from writing style, music taste, school references or a
 * photo. The distinction matters: a stated age is a fact the person published;
 * an inferred one is a guess about a real individual that would then be shown
 * to a client as though it were measured.
 *
 * Even so this is reported as a range with a sample size attached, never as
 * "the average follower is 23".
 */
const AGE_IN_BIO = [
  /\b(1[6-9]|[2-4][0-9])\s*(?:yo|y\/o|years? old|jaar)\b/i,
  /\b(?:age|leeftijd)[:\s]+(1[6-9]|[2-4][0-9])\b/i,
]

export function selfReportedAge(bio: string | null | undefined): number | null {
  if (!bio) return null
  for (const re of AGE_IN_BIO) {
    const m = bio.match(re)
    if (m) {
      const n = parseInt(m[1], 10)
      if (n >= 16 && n <= 49) return n
    }
  }
  return null
}

function topN(counts: Map<string, number>, n: number): Ranked[] {
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
    .slice(0, n)
}

function median(xs: number[]): number | null {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2)
}

/**
 * Build one profile per scene.
 *
 * `creatorScenes` maps handle → subcultures. When it is empty — a brand that
 * has never run the seeding step — scenes fall back to per-photo grouping so
 * the section still says something.
 *
 * MEDIANS, NOT MEANS, for followers and likes. One creator with 400k followers
 * in a scene of twenty students would drag a mean into a number that describes
 * nobody in the room.
 */
export type CreatorInfo = { followerCount?: number | null; bio?: string | null; avatarUrl?: string | null }

export function communityProfiles(
  rows: DetectionRow[],
  creatorScenes: CreatorSceneMap,
  labels: Record<string, string> = {},
  opts: { minHits?: number; limit?: number; creators?: Record<string, CreatorInfo> } = {},
): CommunityProfile[] {
  const { minHits = 3, limit = 8, creators: creatorInfo = {} } = opts
  const useSubcultures = Object.values(creatorScenes).some((v) => v.length > 0)

  type Acc = {
    hits: number; untagged: number
    creators: Map<string, { hits: number; followers: number | null; avatar: string | null; ageCounted?: boolean }>
    hashtags: Map<string, number>; sounds: Map<string, number>
    activities: Map<string, number>; settings: Map<string, number>; cities: Map<string, number>
    likes: number[]; days: number[]
    sentiment: Record<string, number>; scored: number
    ages: number[]
  }
  const acc = new Map<string, Acc>()
  const blank = (): Acc => ({
    hits: 0, untagged: 0, creators: new Map(),
    hashtags: new Map(), sounds: new Map(), activities: new Map(),
    settings: new Map(), cities: new Map(), likes: [], days: [],
    sentiment: { positive: 0, neutral: 0, negative: 0, promotional: 0 }, scored: 0,
    ages: [],
  })

  const bump = (key: string, d: DetectionRow) => {
    const e = acc.get(key) ?? blank()
    e.hits += 1
    if ((d.signal?.signal ?? classifySignal(d).signal) === 'visual_only') e.untagged += 1

    const handle = (d.creator_handle ?? '').toLowerCase()
    const author = d.extras?.author ?? null
    // The creator RECORD wins over the detection snapshot. A detection freezes
    // whatever was known when the post was analysed, and for Instagram that was
    // nothing at all until the profile refresh existed — so preferring the
    // record is the difference between a follower count and a blank.
    const info = creatorInfo[handle]
    const c = e.creators.get(handle) ?? { hits: 0, followers: null, avatar: null }
    c.hits += 1
    const followers = info?.followerCount ?? d.follower_count
    if (followers && followers > 0) c.followers = Math.max(c.followers ?? 0, followers)
    if (!c.avatar) c.avatar = info?.avatarUrl ?? author?.avatar ?? null
    e.creators.set(handle, c)

    for (const t of d.post_hashtags ?? []) {
      const k = t.toLowerCase().replace(/^#/, '')
      // Brand tags are excluded on purpose: "they also post #stelz" is not a
      // fact about their life, and it would top every scene's list.
      if (!k || isBrandTag(k)) continue
      e.hashtags.set(k, (e.hashtags.get(k) ?? 0) + 1)
    }

    const m = d.music
    if (m && (m.musicId || (m.title || '').trim())) {
      const label = m.title?.trim() || 'Original sound'
      e.sounds.set(label, (e.sounds.get(label) ?? 0) + 1)
    }

    const activity = (d.activity ?? '').trim().toLowerCase()
    if (activity && !['none', 'unclear', 'unknown', 'n/a'].includes(activity)) {
      e.activities.set(activity, (e.activities.get(activity) ?? 0) + 1)
    }
    const surface = (d.surface_type ?? '').trim().toLowerCase()
    if (surface && surface !== 'other') {
      const pretty = surface.replace(/_/g, ' ')
      e.settings.set(pretty, (e.settings.get(pretty) ?? 0) + 1)
    }
    const city = d.extras?.location?.city?.trim()
    if (city) e.cities.set(city, (e.cities.get(city) ?? 0) + 1)

    if (d.likes_count && d.likes_count > 0) e.likes.push(d.likes_count)
    if (d.posted_at) {
      const dow = new Date(d.posted_at).getDay()
      if (!Number.isNaN(dow)) e.days.push(dow)
    }
    if (d.sentiment) {
      e.sentiment[d.sentiment] = (e.sentiment[d.sentiment] ?? 0) + 1
      e.scored += 1
    }
    // Bio comes from the creator record on Instagram and from the post's author
    // block on TikTok. Only one age per creator, not one per post, or a prolific
    // poster would appear in the range a dozen times.
    if (!e.creators.get(handle)?.ageCounted) {
      const age = selfReportedAge(info?.bio ?? author?.signature)
      if (age) {
        e.ages.push(age)
        const cc = e.creators.get(handle)!
        cc.ageCounted = true
        e.creators.set(handle, cc)
      }
    }

    acc.set(key, e)
  }

  for (const d of rows) {
    // THE BRAND'S OWN ACCOUNT IS NOT A COMMUNITY MEMBER.
    //
    // @drinkstelz alone accounts for a couple of hundred hits, and it belongs
    // to every scene at once — so it appeared as a "face" in all six portraits
    // and dragged each one toward the same hashtags (#hardseltzer), the same
    // rhythm and the same activities. Six portraits described the marketing
    // account six times over, and the differences between real scenes — which
    // is the entire point of this section — were invisible underneath it.
    //
    // Excluded here rather than upstream: the brand's own posts are still real
    // detections and still belong in the feed and the totals. They just are not
    // evidence about anybody's audience.
    if (BRAND_OWNED_HANDLES.has((d.creator_handle ?? '').toLowerCase())) continue
    if (useSubcultures) {
      const scenes = creatorScenes[(d.creator_handle ?? '').toLowerCase()]
      if (!scenes || scenes.length === 0) { bump('other', d); continue }
      for (const s of scenes) bump(s.slug, d)
    } else {
      bump(sceneKeyFor(d).key, d)
    }
  }

  return [...acc.entries()]
    // A scene with two posts in it is an anecdote. Showing it beside a scene
    // with two hundred invites the reader to compare them as equals.
    .filter(([key, e]) => key !== 'other' && e.hits >= minHits)
    .map(([key, e]) => {
      const followers = [...e.creators.values()].map((c) => c.followers).filter((f): f is number => !!f && f > 0)
      const dayCounts = new Map<number, number>()
      for (const d of e.days) dayCounts.set(d, (dayCounts.get(d) ?? 0) + 1)
      const peak = [...dayCounts.entries()].sort((a, b) => b[1] - a[1])[0]
      return {
        key,
        label: labels[key] ?? key.replace(/_/g, ' '),
        hits: e.hits,
        untagged: e.untagged,
        untaggedPct: e.hits ? Math.round((e.untagged / e.hits) * 100) : 0,
        creators: e.creators.size,
        medianFollowers: median(followers),
        followersKnownFor: followers.length,
        medianLikes: median(e.likes),
        topHashtags: topN(e.hashtags, 6),
        topSounds: topN(e.sounds, 3),
        topActivities: topN(e.activities, 4),
        topSettings: topN(e.settings, 4),
        topCities: topN(e.cities, 4),
        peakDay: peak && e.days.length >= 5
          ? { day: peak[0], pct: Math.round((peak[1] / e.days.length) * 100) }
          : null,
        sentiment: {
          positive: e.sentiment.positive ?? 0,
          neutral: e.sentiment.neutral ?? 0,
          negative: e.sentiment.negative ?? 0,
          promotional: e.sentiment.promotional ?? 0,
          scored: e.scored,
        },
        selfReportedAges: e.ages,
        sampleCreators: [...e.creators.entries()]
          .sort((a, b) => b[1].hits - a[1].hits)
          .slice(0, 5)
          .map(([handle, c]) => ({ handle, avatar: c.avatar, hits: c.hits, followers: c.followers })),
      }
    })
    .sort((a, b) => b.untagged - a.untagged || b.hits - a.hits)
    .slice(0, limit)
}

/** "Mostly Fridays", "Weekend-heavy" — a sentence, not a chart. */
export const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

/**
 * The scene in one line, for a card header.
 *
 * Built only from parts that exist, and it says "no" rather than inventing
 * connective tissue: with nothing to report it returns null and the card simply
 * shows its numbers.
 */
export function oneLineSummary(p: CommunityProfile): string | null {
  const bits: string[] = []
  if (p.topActivities.length) bits.push(p.topActivities[0].label)
  if (p.peakDay && p.peakDay.pct >= 25) bits.push(`mostly ${DAY_NAMES[p.peakDay.day]}s`)
  if (p.topCities.length) bits.push(`often ${p.topCities[0].label}`)
  if (p.medianFollowers) bits.push(`typically ~${p.medianFollowers.toLocaleString()} followers`)
  if (!bits.length) return null
  return bits.join(' · ')
}
