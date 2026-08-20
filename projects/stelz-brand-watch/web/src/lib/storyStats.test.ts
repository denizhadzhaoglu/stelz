// The claims this page makes to a client, pinned.
//
// Two of them are the ones that would quietly become false: a story we could
// not analyse must never read as "no Stëlz", and follower counts must never be
// added up per story instead of per creator.
import { describe, expect, it } from 'vitest'
import {
  joinStories, storyRollup, stelzShare, isStelzStory, storyImage, VERDICT_LABEL,
} from './storyStats'
import type { StoryPost } from './firestore'
import type { DetectionRow } from './types'

const post = (over: Partial<StoryPost> & { postId: string; creatorHandle: string }): StoryPost => ({
  creatorTier: 'tier_2', url: null, coverUrl: 'https://cdn/cover.jpg', videoUrl: null,
  mediaType: 'image', videoDuration: null, postedAt: '2026-08-20T10:00:00Z',
  postedAtEstimated: false, expiresAt: '2026-08-21T10:00:00Z',
  hashtags: [], mentions: [], pollVotes: 0, pollCount: 0, pollQuestions: [],
  linkUrls: [], music: null, isPaidPartnership: false, ...over,
})

const det = (over: Partial<DetectionRow> & { post_id: string }): DetectionRow => ({
  detection_id: `d_${over.post_id}`, creator_id: null, creator_handle: 'anna',
  creator_category: null, platform: 'instagram', product_line: null,
  confidence: 0.95, size_in_frame: 'medium', is_primary_subject: true,
  image_url: null, stored_path: null, post_url: null, post_caption: null,
  posted_at: '2026-08-20T10:00:00Z', likes_count: null, comments_count: null,
  views_count: null, follower_count: null, creator_tier: 'tier_2', verified: null,
  context: null, post_hashtags: null, post_mentions: null, music: null, extras: null,
  surface_type: null, visible_text: null, false_positive_risk: null,
  people_count: null, setting: null, activity: null, gate: null,
  verify_verdict: null, verify_brand: null, verify_reason: null,
  sentiment: null, sentiment_score: null, sentiment_rationale: null,
  brand_id: 'stelz', detected: true, is_false_positive: null, ...over,
})

describe('verdicts', () => {
  it('a story with no detection is "not analysed", never "no Stëlz"', () => {
    // The load-bearing one. detect_image writes NOTHING when the image fetch
    // fails, and story CDN links expire fast — so this is the common path, and
    // calling it "geen Stëlz" would report a miss we never actually looked for.
    const [row] = joinStories([post({ postId: 'p1', creatorHandle: 'anna' })], [])
    expect(row.verdict).toBe('unanalysed')
    expect(VERDICT_LABEL[row.verdict]).toBe('Nog niet geanalyseerd')
    expect(isStelzStory(row.verdict)).toBe(false)
  })

  it('separates a clear hit from one the size gate demoted', () => {
    const clear = joinStories(
      [post({ postId: 'p1', creatorHandle: 'anna' })],
      [det({ post_id: 'p1', confidence: 0.95, size_in_frame: 'medium' })],
    )[0]
    expect(clear.verdict).toBe('visible')

    const demoted = joinStories(
      [post({ postId: 'p2', creatorHandle: 'anna' })],
      [det({ post_id: 'p2', confidence: 0.7, gate: 'capped_small_object', size_in_frame: 'small' })],
    )[0]
    expect(demoted.verdict).toBe('small')
    // Still a real hit: excluding it under-reports the campaign.
    expect(isStelzStory(demoted.verdict)).toBe(true)
  })

  it('reports an analysed miss as absent', () => {
    const [row] = joinStories(
      [post({ postId: 'p1', creatorHandle: 'anna' })],
      [det({ post_id: 'p1', detected: false, confidence: 0.1 })],
    )
    expect(row.verdict).toBe('absent')
  })

  it('a moderator rejection outranks a model hit', () => {
    const [row] = joinStories(
      [post({ postId: 'p1', creatorHandle: 'anna' })],
      [det({ post_id: 'p1' }), det({ post_id: 'p1', detection_id: 'x', is_false_positive: true })],
    )
    expect(row.verdict).toBe('rejected')
  })

  it('takes the strongest frame of a video story', () => {
    // Six frames, one of which caught the can. That is a hit.
    const [row] = joinStories(
      [post({ postId: 'p1', creatorHandle: 'anna', mediaType: 'video' })],
      [
        det({ post_id: 'p1', detection_id: 'f0', detected: false, confidence: 0.05 }),
        det({ post_id: 'p1', detection_id: 'f3', detected: true, confidence: 0.93 }),
      ],
    )
    expect(row.verdict).toBe('visible')
    expect(row.confidence).toBeCloseTo(0.93)
  })
})

describe('storyImage', () => {
  it('prefers the mirrored copy over the expiring CDN link', () => {
    const [row] = joinStories(
      [post({ postId: 'p1', creatorHandle: 'anna', coverUrl: 'https://cdn/signed.jpg' })],
      [det({ post_id: 'p1', stored_path: 'https://storage/mirror.jpg' })],
    )
    expect(storyImage(row)).toBe('https://storage/mirror.jpg')
  })

  it('falls back to the story cover when nothing was mirrored', () => {
    const [row] = joinStories([post({ postId: 'p1', creatorHandle: 'anna' })], [])
    expect(storyImage(row)).toBe('https://cdn/cover.jpg')
  })
})

describe('storyRollup', () => {
  const profiles = {
    anna: { handle: 'anna', platform: 'instagram', followerCount: 10_000, bio: null, avatarUrl: null, fullName: 'Anna', category: null, tier: 'tier_2' },
    bob: { handle: 'bob', platform: 'instagram', followerCount: 5_000, bio: null, avatarUrl: null, fullName: 'Bob', category: null, tier: 'tier_2' },
  }

  it('counts a creator\'s followers ONCE however many stories they posted', () => {
    // Adding followers per story multiplies the audience by the posting rate.
    // Anna posting five times does not give Stëlz 50,000 people.
    const rows = joinStories(
      ['a', 'b', 'c', 'd', 'e'].map((i) => post({ postId: `p${i}`, creatorHandle: 'anna' })),
      [],
    )
    const r = storyRollup(rows, profiles)
    expect(r.stories).toBe(5)
    expect(r.creatorsPosted).toBe(1)
    expect(r.reach).toBe(10_000)
    expect(r.reachKnownFor).toBe(1)
  })

  it('says how many follower counts it actually knew', () => {
    const rows = joinStories([
      post({ postId: 'p1', creatorHandle: 'anna' }),
      post({ postId: 'p2', creatorHandle: 'carla' }),   // no profile on file
    ], [])
    const r = storyRollup(rows, profiles)
    expect(r.reach).toBe(10_000)
    expect(r.reachKnownFor).toBe(1)
    expect(r.creatorsPosted).toBe(2)
  })

  it('keeps silent roster members in the table with zeroes', () => {
    // A tracked creator producing nothing is the finding, not a missing row.
    const rows = joinStories([post({ postId: 'p1', creatorHandle: 'anna' })], [])
    const r = storyRollup(rows, profiles, ['anna', 'bob'])
    expect(r.byCreator.map((c) => c.handle).sort()).toEqual(['anna', 'bob'])
    expect(r.byCreator.find((c) => c.handle === 'bob')!.stories).toBe(0)
    // ...and they must not inflate reach.
    expect(r.reach).toBe(10_000)
    expect(r.creatorsPosted).toBe(1)
  })

  it('totals the public engagement numbers', () => {
    const rows = joinStories([
      post({ postId: 'p1', creatorHandle: 'anna', pollVotes: 18_412, pollCount: 1, mentions: ['stelz'], linkUrls: ['drinkstelz.com'] }),
      post({ postId: 'p2', creatorHandle: 'bob', mediaType: 'video', videoDuration: 14.5 }),
    ], [])
    const r = storyRollup(rows, profiles)
    expect(r.pollVotes).toBe(18_412)
    expect(r.mentions).toBe(1)
    expect(r.links).toBe(1)
    expect(r.videoSeconds).toBeCloseTo(14.5)
  })

  it('ranks creators by Stëlz first, then volume', () => {
    const rows = joinStories(
      [
        post({ postId: 'p1', creatorHandle: 'anna' }),
        post({ postId: 'p2', creatorHandle: 'anna' }),
        post({ postId: 'p3', creatorHandle: 'bob' }),
      ],
      [det({ post_id: 'p3' })],
    )
    const r = storyRollup(rows, profiles)
    expect(r.byCreator[0].handle).toBe('bob')   // 1 hit beats 2 stories, 0 hits
  })
})

describe('stelzShare', () => {
  it('is null while nothing has been analysed', () => {
    // A 0% that only means "we have not looked yet" is a lie in a KPI box.
    const rows = joinStories([post({ postId: 'p1', creatorHandle: 'anna' })], [])
    expect(stelzShare(storyRollup(rows))).toBeNull()
  })

  it('divides by what was analysed, not by everything captured', () => {
    const rows = joinStories(
      [
        post({ postId: 'p1', creatorHandle: 'anna' }),
        post({ postId: 'p2', creatorHandle: 'anna' }),
        post({ postId: 'p3', creatorHandle: 'anna' }),   // never analysed
      ],
      [det({ post_id: 'p1' }), det({ post_id: 'p2', detected: false })],
    )
    // 1 hit out of 2 analysed = 50%, not 33% of all three.
    expect(stelzShare(storyRollup(rows))).toBeCloseTo(50)
  })
})
