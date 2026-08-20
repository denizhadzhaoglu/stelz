// The generated campaign data, joined the way the page joins it.
//
// Unit tests pin the rules; this pins the actual bytes the dev server serves.
// The bug class it exists for is invisible to both a typecheck and a unit test:
// two files that are individually well-formed but do not join, so the page
// renders "nog niet geanalyseerd" over a complete set of verdicts.
//
// Skips when the fixtures are absent — they are generated and gitignored. A
// skipped test says "not checked"; a passing test over an empty array would say
// "checked and fine", which is worse than not running at all.
import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { joinCampaign, campaignRollup, metricFor, SURFACES } from './campaign'
import type { CampaignItem } from './campaign'
import type { DetectionRow } from './types'

const TMP = resolve(__dirname, '../../../../../.tmp')
const ITEMS = resolve(TMP, 'preview-campaign.json')
const DETS = resolve(TMP, 'preview-campaign-detections.json')
const present = existsSync(ITEMS) && existsSync(DETS)
const read = <T>(p: string): T[] => JSON.parse(readFileSync(p, 'utf8')) as T[]

describe.skipIf(!present)('the generated campaign fixture', () => {
  const items = present ? read<CampaignItem>(ITEMS) : []
  const dets = present ? read<DetectionRow>(DETS) : []
  const rows = joinCampaign(items, dets)
  const rollup = campaignRollup(rows)

  it('joins every verdict onto its item', () => {
    expect(rows).toHaveLength(items.length)
    expect(rollup.judged).toBe(dets.length)
  })

  it('covers more than one platform', () => {
    // The entire point of the page. If this ever drops to one surface the
    // harvest silently stopped covering the other.
    const surfaces = new Set(rows.map((r) => r.surface))
    expect(surfaces.size).toBeGreaterThan(1)
    expect(rows.some((r) => r.platform === 'tiktok')).toBe(true)
    expect(rows.some((r) => r.platform === 'instagram')).toBe(true)
  })

  it('never gives a story a view count', () => {
    // Instagram publishes story views to the account holder and to nobody
    // else. A number here would have to have been invented.
    for (const r of rows.filter((r) => r.surface === 'story')) {
      expect(r.views, `story ${r.itemId} has a view count`).toBeNull()
    }
  })

  it('gives TikToks a real one', () => {
    const tt = rows.filter((r) => r.surface === 'tiktok')
    if (tt.length === 0) return
    expect(tt.some((r) => (r.views ?? 0) > 0)).toBe(true)
    expect(rollup.tiktokViews).toBeGreaterThan(0)
  })

  it('keeps the three metrics apart', () => {
    const perSurface = SURFACES.map((s) => rollup.bySurface[s].metric ?? 0)
    const sum = perSurface.reduce((a, b) => a + b, 0)
    // Nothing on the rollup equals the sum of all three — that number would be
    // a "total reach" describing plays, votes and likes as one thing.
    if (perSurface.filter((v) => v > 0).length > 1) {
      expect(Object.values(rollup).includes(sum)).toBe(false)
    }
  })

  it('resolves one person per row, not one account', () => {
    // Rein is @rvdofficial on Instagram and @rinnavandoffoe on TikTok. If the
    // identity map breaks, the roster of 28 reports 40-odd creators and the
    // "who delivered nothing" column stops meaning anything.
    const tiktokOnly = new Set(['rinnavandoffoe', 'pleun.bierbooms', 'isadeejans'])
    for (const r of rows) {
      expect(tiktokOnly.has(r.creatorHandle),
        `${r.creatorHandle} is a TikTok account, not a person`).toBe(false)
    }
  })

  it('serves its media from the archives, not from expiring CDN links', () => {
    const local = rows.filter((r) => (r.coverUrl ?? '').startsWith('/preview-media/'))
    expect(local.length).toBeGreaterThan(0)
  })

  it('gives every judged item the model\'s own description', () => {
    const judged = rows.filter((r) => r.verdict !== 'unanalysed')
    expect(judged.length).toBeGreaterThan(0)
    expect(judged.every((r) => (r.detection?.context ?? '').length > 5)).toBe(true)
  })

  it('reports images looked at, never fewer than items judged', () => {
    expect(rollup.imagesSeen).toBeGreaterThanOrEqual(rollup.judged)
    for (const r of rows) {
      if (r.verdict === 'unanalysed') expect(r.framesJudged).toBe(0)
      else expect(r.framesJudged).toBeGreaterThan(0)
    }
  })

  it('has a metric or an explicit blank for every row', () => {
    for (const r of rows) {
      const m = metricFor(r)
      expect(m === null || typeof m === 'number').toBe(true)
    }
  })
})
