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

/** Pure matching rule, testable without a DOM. Exact match only: `?preview=1`
 *  and `?preview=storiesx` must not switch anything on. */
export function matchesPreview(search: string, kind: 'stories'): boolean {
  return new URLSearchParams(search).get('preview') === kind
}

/** Preview rows, or null when not in preview mode / the fixture is absent. */
export function useStoryPreview(): DetectionRow[] | null {
  const [rows, setRows] = useState<DetectionRow[] | null>(null)
  useEffect(() => {
    // Inline, not extracted — see rule 1 above.
    if (!import.meta.env.DEV) return
    if (!matchesPreview(window.location.search, 'stories')) return
    let cancelled = false
    void fetch('/preview-stories.json')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (!cancelled && Array.isArray(data)) setRows(data as DetectionRow[]) })
      .catch(() => { /* no fixture generated yet — stay on live data */ })
    return () => { cancelled = true }
  }, [])
  return rows
}
