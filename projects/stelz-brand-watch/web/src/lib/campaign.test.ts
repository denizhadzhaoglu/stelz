// The rules this page cannot be allowed to break.
//
// The load-bearing one is the metric rule: TikTok plays, poll votes and post
// likes are three different events, and a single "reach" that adds them is the
// kind of number that survives all the way into a client deck before anyone
// asks what it means.
import { describe, expect, it } from 'vitest'
import {
  joinCampaign, campaignRollup, stelzShare, metricFor, SURFACE_LABEL, SURFACES,
  type CampaignItem,
} from './campaign'
import type { DetectionRow } from './types'

const item = (over: Partial<CampaignItem> & { itemId: string; creatorHandle: string }): CampaignItem => ({
  platform: 'instagram', surface: 'story', url: null, coverUrl: null, videoUrl: null,
  mediaType: 'image', postedAt: '2026-08-20T10:00:00Z', caption: null,
  hashtags: [], mentions: [], videoDuration: null,
  views: null, likes: null, comments: null, shares: null, pollVotes: null,
  isPaidPartnership: false, ...over,
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

describe('metrics per surface', () => {
  it('never adds a TikTok view to a poll vote', () => {
    // The whole reason bySurface exists. If these ever land in one field the
    // page is reporting an audience number that describes nothing.
    const rows = joinCampaign([
      item({ itemId: 'a', creatorHandle: 'anna', surface: 'tiktok', platform: 'tiktok', views: 10_000 }),
      item({ itemId: 'b', creatorHandle: 'anna', surface: 'story', pollVotes: 300 }),
      item({ itemId: 'c', creatorHandle: 'anna', surface: 'post', likes: 50 }),
    ], [])
    const r = campaignRollup(rows)
    expect(r.tiktokViews).toBe(10_000)
    expect(r.pollVotes).toBe(300)
    expect(r.postLikes).toBe(50)
    expect(r.bySurface.tiktok.metric).toBe(10_000)
    expect(r.bySurface.story.metric).toBe(300)
    expect(r.bySurface.post.metric).toBe(50)
    // And no field anywhere holds 10,350.
    const total = 10_000 + 300 + 50
    expect(Object.values(r).some((v) => v === total)).toBe(false)
  })

  it('reports null, not zero, for a surface that publishes no such number', () => {
    // Instagram gives story views to the account holder alone. A 0 would read
    // as "nobody watched" for a figure that does not exist.
    const rows = joinCampaign([item({ itemId: 'a', creatorHandle: 'anna', surface: 'story' })], [])
    expect(metricFor(rows[0])).toBeNull()
    expect(campaignRollup(rows).bySurface.story.metric).toBeNull()
  })

  it('names every surface and its metric', () => {
    for (const s of SURFACES) {
      expect(SURFACE_LABEL[s]).toBeTruthy()
    }
  })
})

describe('verdicts across surfaces', () => {
  it('joins detections onto items by id', () => {
    const rows = joinCampaign(
      [item({ itemId: 'tiktok_video1', creatorHandle: 'anna', surface: 'tiktok', platform: 'tiktok' })],
      [det({ post_id: 'tiktok_video1' })],
    )
    expect(rows[0].verdict).toBe('visible')
  })

  it('keeps an overturned hit as "near", not as "absent"', () => {
    // The state that exists because a rejected hit used to be indistinguishable
    // from an empty field.
    const rows = joinCampaign(
      [item({ itemId: 'p1', creatorHandle: 'anna' })],
      [det({ post_id: 'p1', detected: false, confidence: 0.8,
             gate: 'rejected_by_verifier', verify_verdict: 'rejected' })],
    )
    expect(rows[0].verdict).toBe('near')
    expect(campaignRollup(rows).near).toBe(1)
    // A question is not a sighting.
    expect(campaignRollup(rows).withStelz).toBe(0)
  })

  it('an item with no detection is unanalysed, never a miss', () => {
    const rows = joinCampaign([item({ itemId: 'p1', creatorHandle: 'anna' })], [])
    expect(rows[0].verdict).toBe('unanalysed')
    const r = campaignRollup(rows)
    expect(r.unanalysed).toBe(1)
    expect(r.judged).toBe(0)
    expect(stelzShare(r)).toBeNull()
  })

  it('flags a verdict reached on the cover alone', () => {
    // A thumbnail is a chosen frame. "Nothing found" on one is a much weaker
    // claim than "nothing found" across the whole clip, and the page says so.
    const rows = joinCampaign(
      [item({ itemId: 'v1', creatorHandle: 'anna', surface: 'tiktok', platform: 'tiktok', mediaType: 'video' })],
      [det({ post_id: 'v1', detected: false, cover_only: true })],
    )
    expect(rows[0].coverOnly).toBe(true)
    expect(campaignRollup(rows).bySurface.tiktok.coverOnly).toBe(1)
  })

  it('counts images looked at, not items', () => {
    const rows = joinCampaign(
      [item({ itemId: 'v1', creatorHandle: 'anna', surface: 'tiktok', platform: 'tiktok' })],
      [det({ post_id: 'v1', detected: false, frames_judged: 9 })],
    )
    expect(rows[0].framesJudged).toBe(9)
    expect(campaignRollup(rows).imagesSeen).toBe(9)
  })
})

describe('who delivered', () => {
  it('keeps a roster member who posted nothing, at zero', () => {
    // Silence from someone being paid to post is the finding, not a gap.
    const rows = joinCampaign([item({ itemId: 'a', creatorHandle: 'anna' })], [])
    const r = campaignRollup(rows, {}, ['anna', 'bo', 'cas'])
    expect(r.rosterSize).toBe(3)
    expect(r.delivered).toBe(1)
    expect(r.silent).toBe(2)
    const bo = r.creators.find((c) => c.handle === 'bo')!
    expect(bo.silent).toBe(true)
    expect(bo.items).toBe(0)
  })

  it('splits one creator across the three surfaces', () => {
    const rows = joinCampaign([
      item({ itemId: 's1', creatorHandle: 'anna', surface: 'story' }),
      item({ itemId: 's2', creatorHandle: 'anna', surface: 'story' }),
      item({ itemId: 'p1', creatorHandle: 'anna', surface: 'post' }),
      item({ itemId: 't1', creatorHandle: 'anna', surface: 'tiktok', platform: 'tiktok', views: 900 }),
    ], [])
    const anna = campaignRollup(rows).creators[0]
    expect(anna.bySurface.story.items).toBe(2)
    expect(anna.bySurface.post.items).toBe(1)
    expect(anna.bySurface.tiktok.items).toBe(1)
    expect(anna.bySurface.tiktok.metric).toBe(900)
    // Counting content is fine — these are things, not audience measurements.
    expect(anna.items).toBe(4)
  })

  it('sorts creators who showed Stëlz first', () => {
    const rows = joinCampaign(
      [item({ itemId: 'a', creatorHandle: 'anna' }), item({ itemId: 'b', creatorHandle: 'bo' })],
      [det({ post_id: 'b' })],
    )
    expect(campaignRollup(rows).creators[0].handle).toBe('bo')
  })
})

describe('Stëlz that is not on a can', () => {
  // A festival sponsorship is bought partly as signage: a branded bar front, a
  // parasol, a cooler, an inflatable, a cap. The verifier used to answer
  // "not_a_container" for every one of those and the detection was deleted —
  // 22 of 41 rejections on the Lowlands archive. They are hits, but they are a
  // different KIND of hit, and a report that flattens them into one number
  // loses the distinction a sponsor is actually buying.
  const rows = () => joinCampaign([
    item({ itemId: 'bar', creatorHandle: 'sterre', surface: 'post' }),
    item({ itemId: 'ring', creatorHandle: 'daan', surface: 'post' }),
    item({ itemId: 'can', creatorHandle: 'daan', surface: 'post' }),
  ], [
    det({ post_id: 'bar', verify_placement: 'signage', verify_verdict: 'confirmed' }),
    det({ post_id: 'ring', verify_placement: 'merchandise', verify_verdict: 'confirmed' }),
    det({ post_id: 'can' }),
  ])

  it('counts a placement as a sighting', () => {
    const r = campaignRollup(rows())
    expect(r.withStelz).toBe(3)
  })

  it('counts off-container placements as a SUBSET, never an addition', () => {
    const r = campaignRollup(rows())
    expect(r.offContainer).toBe(2)
    expect(r.offContainer).toBeLessThanOrEqual(r.withStelz)
    expect(r.bySurface.post.offContainer).toBe(2)
  })

  it('carries the placement onto the row so the panel can name it', () => {
    const byId = Object.fromEntries(rows().map((r) => [r.itemId, r]))
    expect(byId.bar.placement).toBe('signage')
    expect(byId.ring.placement).toBe('merchandise')
    expect(byId.can.placement).toBeNull()
  })

  it('never counts a placement on something that is not a sighting', () => {
    // A rejected row carrying a stale placement must not inflate the count.
    const r = campaignRollup(joinCampaign(
      [item({ itemId: 'x', creatorHandle: 'anna', surface: 'post' })],
      [det({ post_id: 'x', detected: false, verify_placement: 'signage' })],
    ))
    expect(r.withStelz).toBe(0)
    expect(r.offContainer).toBe(0)
  })
})

describe('the gap between this page and the deployed backend', () => {
  // The page is generated from an archive that can be analysed at the images'
  // own resolution. The deployed function downscales everything to 512px
  // first, and on the Lowlands archive that costs 13 of 46 sightings —
  // several of them confirmed by eye. Left unstated, the count would simply
  // drop after a deploy and read as a scraping failure.
  it('flags a sighting the deploy would miss', () => {
    const rows = joinCampaign(
      [item({ itemId: 'a', creatorHandle: 'niek', surface: 'tiktok', platform: 'tiktok' })],
      [det({ post_id: 'a', found_at_prod_res: false })],
    )
    expect(rows[0].missedByDeploy).toBe(true)
    expect(campaignRollup(rows).missedByDeploy).toBe(1)
  })

  it('says nothing when the deploy would find it too', () => {
    const rows = joinCampaign(
      [item({ itemId: 'a', creatorHandle: 'lize', surface: 'post' })],
      [det({ post_id: 'a', found_at_prod_res: true })],
    )
    expect(rows[0].missedByDeploy).toBe(false)
    expect(campaignRollup(rows).missedByDeploy).toBe(0)
  })

  it('stays silent rather than guessing when the field is absent', () => {
    // Production detections never carry it — a deployed detection IS at
    // production resolution. Undefined must not render as "not live".
    const rows = joinCampaign(
      [item({ itemId: 'a', creatorHandle: 'lize', surface: 'post' })],
      [det({ post_id: 'a' })],
    )
    expect(rows[0].missedByDeploy).toBe(false)
  })

  it('never counts a miss on something that was not a sighting', () => {
    const rows = joinCampaign(
      [item({ itemId: 'a', creatorHandle: 'lize', surface: 'post' })],
      [det({ post_id: 'a', detected: false, found_at_prod_res: false })],
    )
    expect(campaignRollup(rows).missedByDeploy).toBe(0)
  })
})
