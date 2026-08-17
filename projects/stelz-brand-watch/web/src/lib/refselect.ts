// Which reference images the detector actually sees.
//
// WHY THIS EXISTS
// DETECT_PROMPT_V8 opens with "The ONLY source of truth for what the product
// looks like is the set of reference photos provided above." Every image in
// brands/{id}/referenceImages is passed to the model as a POSITIVE example —
// there is no polarity field in the schema (web/src/lib/firestore.ts:275), so
// there is no way to say "this is what it is NOT". Anything uploaded here is
// asserted to be the product.
//
// And only 8 of them are sent. The backend fetches up to 60 and picks 8
// (lib/refs.py load_references / _select_reference_docs). The Settings page
// showed all of them identically, so an operator with 26 uploads had no way to
// know which 8 were doing the work — or that a bad one was among them.
//
// This mirrors _select_reference_docs exactly. If that function changes, this
// must change with it; it is duplicated rather than derived because the
// selection happens server-side and the answer is only useful in the UI.

import type { ReferenceImage } from './firestore'

/** Matches `refs.load_references(max_count=8)`. */
export const REFERENCE_SLOTS = 8

/** Matches the `.limit(60)` candidate pool in `refs.load_references`. */
export const REFERENCE_POOL = 60

/**
 * Return the ids of the images the detector will actually be shown, in the
 * order it sees them.
 *
 * Two passes, mirroring refs.py:
 *   1. one image per product line, newest first — so no product line is invisible
 *   2. fill the remaining slots newest-first
 */
export function activeReferenceIds(items: ReferenceImage[], slots = REFERENCE_SLOTS): Set<string> {
  // Newest first; missing uploadedAt sorts oldest, same as the Python `_key`
  // which ranks (ts is not None, ts) descending.
  const ordered = [...items].sort((a, b) => {
    const at = a.uploadedAt ?? ''
    const bt = b.uploadedAt ?? ''
    if (!at && !bt) return 0
    if (!at) return 1
    if (!bt) return -1
    return bt.localeCompare(at)
  }).slice(0, REFERENCE_POOL)

  const picked: ReferenceImage[] = []
  const seenLines = new Set<string>()
  for (const d of ordered) {
    if (picked.length >= slots) break
    const line = d.productLine || '_none'
    if (!seenLines.has(line)) {
      seenLines.add(line)
      picked.push(d)
    }
  }
  for (const d of ordered) {
    if (picked.length >= slots) break
    if (!picked.includes(d)) picked.push(d)
  }
  return new Set(picked.map((d) => d.id))
}
