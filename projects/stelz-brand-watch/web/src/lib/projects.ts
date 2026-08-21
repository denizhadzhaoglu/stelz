// Project rollups — what a tracked group of creators is actually doing.
//
// A project is a brand-shared list of creator ids (Project in firestore.ts;
// writes go through api_projects because membership changes scan cadence =
// spend). This module answers the read side: given the deduped detection rows
// the app already fetched, what did this project's creators produce?
//
// Pure functions over rows already in memory — zero extra Firestore reads,
// same pattern as sounds.ts / communities.ts.

import type { DetectionRow } from './types'
import type { Project } from './firestore'

/** How many distinct creators may be tracked across ALL live projects at once.
 *
 *  Mirrors handlers/projects.TOTAL_TRACKED_CAP, and test_events.py fails if the
 *  two drift. Mirrored rather than fetched because it is needed before the
 *  first write: the server enforces it at import time and returns an error, so
 *  a roster of 28 that would breach it should say so while it is still being
 *  planned rather than after the button.
 *
 *  It is a SPEND ceiling, not a per-project one. Tracking flips a creator to a
 *  6h/12h scan cadence — up to 8x the default, drawn from the same daily
 *  budget as every hashtag scan — so four events of 28 people is 112 of it. */
export const TOTAL_TRACKED_CAP = 150

/** The same, for the expensive 6h cadence. Mirrors TIER1_TRACKED_CAP. */
export const TIER1_TRACKED_CAP = 25

/** Distinct creators currently tracked, across every live project. */
export function trackedCreators(projects: Project[]): Set<string> {
  return new Set(projects.filter((p) => !p.archived).flatMap((p) => p.creatorIds))
}

/** Creator doc ids are composite `${platform}_${handle}` (fs.composite_id).
 * Handles can themselves contain underscores, so split on the FIRST one only:
 * "instagram_de_bierman" → platform "instagram", handle "de_bierman". */
export function splitCreatorId(creatorId: string): { platform: string; handle: string } {
  const i = creatorId.indexOf('_')
  if (i < 0) return { platform: 'instagram', handle: creatorId }
  return { platform: creatorId.slice(0, i), handle: creatorId.slice(i + 1) }
}

export function creatorIdFor(d: Pick<DetectionRow, 'platform' | 'creator_handle'>): string {
  return `${d.platform || 'instagram'}_${(d.creator_handle || '').toLowerCase()}`
}

export type ProjectCreator = {
  creatorId: string
  platform: string
  handle: string
  hits: number
  followers: number | null
  avatar: string | null
  lastHitAt: string | null
  likes: number
}

export type ProjectRollup = {
  hits: number
  /** Every project member, including the ones with zero hits so far — a
   * tracked creator who produced nothing is information, not a rendering gap. */
  creators: ProjectCreator[]
  /** Sum of known follower counts across distinct members. Members with an
   * unknown count contribute nothing; `reachKnownFor` says how many counted. */
  reach: number
  reachKnownFor: number
  sentiment: { positive: number; neutral: number; negative: number; promotional: number; unscored: number }
  /** posted_at ISO strings for the caller's trend chart. */
  postedAts: string[]
}

export function rollupProject(project: Pick<Project, 'creatorIds'>, rows: DetectionRow[]): ProjectRollup {
  const memberIds = new Set(project.creatorIds)
  const byId = new Map<string, ProjectCreator>()
  for (const cid of project.creatorIds) {
    const { platform, handle } = splitCreatorId(cid)
    byId.set(cid, {
      creatorId: cid, platform, handle,
      hits: 0, followers: null, avatar: null, lastHitAt: null, likes: 0,
    })
  }

  const sentiment = { positive: 0, neutral: 0, negative: 0, promotional: 0, unscored: 0 }
  const postedAts: string[] = []
  let hits = 0

  for (const d of rows) {
    if (d.detected !== true) continue
    const cid = creatorIdFor(d)
    const c = byId.get(cid)
    if (!c || !memberIds.has(cid)) continue
    hits += 1
    c.hits += 1
    c.likes += d.likes_count ?? 0
    if (d.follower_count && d.follower_count > (c.followers ?? 0)) c.followers = d.follower_count
    c.avatar = c.avatar || d.extras?.author?.avatar || null
    if (d.posted_at) {
      postedAts.push(d.posted_at)
      if (!c.lastHitAt || d.posted_at > c.lastHitAt) c.lastHitAt = d.posted_at
    }
    if (d.sentiment) sentiment[d.sentiment] += 1
    else sentiment.unscored += 1
  }

  const creators = [...byId.values()].sort((a, b) => b.hits - a.hits || a.handle.localeCompare(b.handle))
  const known = creators.filter((c) => c.followers != null)
  return {
    hits,
    creators,
    reach: known.reduce((s, c) => s + (c.followers ?? 0), 0),
    reachKnownFor: known.length,
    sentiment,
    postedAts,
  }
}
