// Tests for project rollups.
//
// The subtle one is splitCreatorId: composite ids are `${platform}_${handle}`
// and HANDLES CONTAIN UNDERSCORES ("de_bierman"). A split on every underscore
// would mangle the handle, the rollup would match nothing, and a project full
// of creators would render as all-zeros — which reads as "tracking is broken".

import { describe, expect, it } from 'vitest'
import { creatorIdFor, rollupProject, splitCreatorId } from './projects'
import type { DetectionRow } from './types'

const row = (p: Partial<DetectionRow>): DetectionRow => ({
  detection_id: Math.random().toString(36).slice(2),
  detected: true,
  platform: 'instagram',
  ...p,
} as DetectionRow)

describe('splitCreatorId', () => {
  it('splits on the FIRST underscore only', () => {
    expect(splitCreatorId('instagram_de_bierman')).toEqual({ platform: 'instagram', handle: 'de_bierman' })
  })

  it('round-trips with creatorIdFor', () => {
    const d = { platform: 'tiktok', creator_handle: 'anna_b' }
    expect(splitCreatorId(creatorIdFor(d))).toEqual({ platform: 'tiktok', handle: 'anna_b' })
  })

  it('lowercases the handle in creatorIdFor — doc ids are lowercased server-side', () => {
    expect(creatorIdFor({ platform: 'instagram', creator_handle: 'Anna_B' })).toBe('instagram_anna_b')
  })

  it('survives an id with no underscore', () => {
    expect(splitCreatorId('weird')).toEqual({ platform: 'instagram', handle: 'weird' })
  })
})

describe('rollupProject', () => {
  const project = { creatorIds: ['instagram_anna', 'tiktok_de_bierman', 'instagram_stil'] }
  const rows = [
    row({ creator_handle: 'anna', likes_count: 100, follower_count: 5000, posted_at: '2026-08-01T10:00:00Z', sentiment: 'positive' }),
    row({ creator_handle: 'anna', likes_count: 40, posted_at: '2026-08-03T10:00:00Z', sentiment: null }),
    row({ creator_handle: 'de_bierman', platform: 'tiktok', follower_count: 12000, posted_at: '2026-08-02T10:00:00Z' }),
    row({ creator_handle: 'buitenstaander', likes_count: 999 }),   // not in project
    row({ creator_handle: 'anna', detected: false }),              // miss — excluded
  ]

  it('counts only project members', () => {
    const r = rollupProject(project, rows)
    expect(r.hits).toBe(3)
    expect(r.creators.find((c) => c.handle === 'buitenstaander')).toBeUndefined()
  })

  it('matches handles containing underscores', () => {
    const r = rollupProject(project, rows)
    expect(r.creators.find((c) => c.handle === 'de_bierman')?.hits).toBe(1)
  })

  it('keeps zero-hit members visible — silence is information', () => {
    const stil = rollupProject(project, rows).creators.find((c) => c.handle === 'stil')
    expect(stil).toBeDefined()
    expect(stil!.hits).toBe(0)
  })

  it('sums reach over known followers only, and says for how many', () => {
    const r = rollupProject(project, rows)
    expect(r.reach).toBe(17000)
    expect(r.reachKnownFor).toBe(2)
  })

  it('tracks lastHitAt per creator', () => {
    const anna = rollupProject(project, rows).creators.find((c) => c.handle === 'anna')!
    expect(anna.lastHitAt).toBe('2026-08-03T10:00:00Z')
  })

  it('treats unscored sentiment as unscored, never neutral', () => {
    const r = rollupProject(project, rows)
    expect(r.sentiment.positive).toBe(1)
    expect(r.sentiment.unscored).toBe(2)
    expect(r.sentiment.neutral).toBe(0)
  })

  it('handles an empty project', () => {
    const r = rollupProject({ creatorIds: [] }, rows)
    expect(r.hits).toBe(0)
    expect(r.creators).toEqual([])
  })
})
