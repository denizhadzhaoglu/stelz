// The preview data, joined the way the page joins it.
//
// Unit tests pin the rules; this pins the actual bytes the dev server will
// serve. The bug that made this file necessary was invisible to both a unit
// test and a typecheck: the verdicts were on disk, correctly shaped, and the
// page simply did not pass them in. Anything that reads "69 analysed" in a
// tool's output and "nog niet geanalyseerd" on screen has to be catchable
// somewhere, and this is that somewhere.
//
// Skips when the fixtures are absent — they are generated, gitignored, and a
// fresh checkout has none. A skipped test says "not checked"; a passing test
// on an empty array would say "checked and fine", which is worse than nothing.
import { describe, expect, it } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { joinStories, storyRollup, storySource, stelzShare } from './storyStats'
import type { StoryPost } from './firestore'
import type { DetectionRow } from './types'

const ARCHIVE = resolve(__dirname, '../../../../../.tmp/stories-archive')
const POSTS = resolve(ARCHIVE, 'preview-story-posts.json')
const DETS = resolve(ARCHIVE, 'preview-stories.json')
const present = existsSync(POSTS) && existsSync(DETS)
const read = <T>(p: string): T[] => JSON.parse(readFileSync(p, 'utf8')) as T[]

describe.skipIf(!present)('the generated story preview', () => {
  const posts = present ? read<StoryPost>(POSTS) : []
  const dets = present ? read<DetectionRow>(DETS) : []
  const src = storySource(posts, dets, [], [])
  const rows = joinStories(src.posts, src.detections)
  const rollup = storyRollup(rows)

  it('joins every verdict onto its story', () => {
    // post_id vs postId is the join, and it broke once already when the story
    // document id gained a third underscore segment.
    expect(rows).toHaveLength(posts.length)
    expect(rollup.judged).toBe(dets.length)
  })

  it('reports images looked at, not just stories judged', () => {
    // A video is one story and up to thirteen images. If this ever equals the
    // story count, the frame evidence has been collapsed away again.
    expect(rollup.imagesSeen).toBeGreaterThanOrEqual(rollup.judged)
    for (const r of rows) {
      if (r.verdict === 'unanalysed') expect(r.framesJudged).toBe(0)
      else expect(r.framesJudged).toBeGreaterThan(0)
    }
  })

  it('gives every judged story the model\'s own description', () => {
    // The one thing an empty state cannot fake. If these are blank the panel
    // has nothing to show and "geanalyseerd" is an unsupported claim.
    const judged = rows.filter((r) => r.verdict !== 'unanalysed')
    expect(judged.length).toBeGreaterThan(0)
    expect(judged.every((r) => (r.detection?.context ?? '').length > 10)).toBe(true)
  })

  it('states a share once anything has been judged', () => {
    expect(stelzShare(rollup)).not.toBeNull()
  })

  it('carries media the dev server can actually serve', () => {
    // Archived files beat signed CDN links, which expire within hours. A
    // fixture full of dead https:// links renders as a page of grey boxes —
    // which is indistinguishable, to the person looking at it, from nothing
    // having been captured.
    const local = rows.filter((r) => (r.coverUrl ?? '').startsWith('/preview-media/'))
    expect(local.length).toBeGreaterThan(0)
  })
})
