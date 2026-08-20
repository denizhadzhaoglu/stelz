// Local preview data, dev server only.
//
// The stories UI cannot be seen working until scan_stories is deployed, and
// deploying needs credentials this machine does not have. Rather than judge a
// panel from its source code, `?preview=stories` loads real scraped stories
// from a local fixture and renders them through the real components.
//
// Two hard rules, because a preview switch in a client-facing dashboard is a
// liability:
//
//   1. It must not exist in a production build. Vite replaces
//      `import.meta.env.DEV` with the literal `false`, so the checks below sit
//      INLINE in the code they guard rather than behind a helper call — a
//      minifier can fold `if (!false) return` and drop everything after it,
//      but it will not do that across a function boundary. The first version
//      of this file guarded via a helper and the fixture path survived into
//      dist/; verified by grepping the built bundle, not by assuming.
//
//   2. Every surface that shows preview rows must SAY it is preview data. A
//      dashboard that cannot be trusted to distinguish real from fake is worth
//      less than one with no preview at all.
//
// Generate the fixture with tools/stelz_brand_watch/61_stories_preview_fixture.py.

import { useEffect, useState } from 'react'
import type { DetectionRow } from './types'
import type { StoryPost } from './firestore'
import type { CampaignItem } from './campaign'

export type PreviewKind = 'stories' | 'campaign'

/** Pure matching rule, testable without a DOM. Exact match only: `?preview=1`
 *  and `?preview=storiesx` must not switch anything on. */
export function matchesPreview(search: string, kind: PreviewKind): boolean {
  return new URLSearchParams(search).get('preview') === kind
}

function usePreviewFixture<T>(file: string, kind: PreviewKind): T[] | null {
  const [rows, setRows] = useState<T[] | null>(null)
  useEffect(() => {
    // Inline, not extracted — see rule 1 above. Both checks have to sit in the
    // block they guard for the minifier to fold them away.
    if (!import.meta.env.DEV) return
    if (!file) return
    if (!matchesPreview(window.location.search, kind)) return
    let cancelled = false
    void fetch(file)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (!cancelled && Array.isArray(data)) setRows(data as T[]) })
      .catch(() => { /* no fixture generated yet — stay on live data */ })
    return () => { cancelled = true }
  }, [file, kind])
  return rows
}

// The path literals sit INSIDE a DEV ternary, not in the argument position of a
// helper call. Second time this bit: a plain `usePreviewFixture('/x.json')`
// keeps the string in the production bundle, because the minifier folds the
// gate inside the hook but cannot reach back out to the call site to delete its
// argument. With `DEV ? path : ''` the whole literal folds to '' in the build.
// Verified by grepping dist/, both times — not by reasoning about it.

/** Story detections for the strip, or null outside preview mode. */
export function useStoryPreview(): DetectionRow[] | null {
  return usePreviewFixture<DetectionRow>(
    import.meta.env.DEV ? '/preview-stories.json' : '', 'stories')
}

/** Story POSTS for the /stories page — the page is driven by posts, so the
 *  preview has to supply posts or it exercises a different path than prod. */
export function useStoryPostsPreview(): StoryPost[] | null {
  return usePreviewFixture<StoryPost>(
    import.meta.env.DEV ? '/preview-story-posts.json' : '', 'stories')
}

/** Campaign items — IG stories, IG posts and TikToks in one list. */
export function useCampaignPreview(): CampaignItem[] | null {
  return usePreviewFixture<CampaignItem>(
    import.meta.env.DEV ? '/preview-campaign.json' : '', 'campaign')
}

/** The verdicts that go with them. Both halves or neither — see
 *  storyStats.storySource for what happens when only one arrives. */
export function useCampaignDetectionsPreview(): DetectionRow[] | null {
  return usePreviewFixture<DetectionRow>(
    import.meta.env.DEV ? '/preview-campaign-detections.json' : '', 'campaign')
}
