// A preview switch inside a client-facing dashboard is a liability, so the two
// properties that keep it safe are asserted rather than trusted.
//
// Vitest runs with DEV true, so a runtime test cannot prove the production
// behaviour — what it CAN prove is that the gate is still written the way that
// makes elimination possible. Vite substitutes a literal `false` for
// import.meta.env.DEV, and a minifier folds `if (!false) return` and drops the
// rest of the block; it will NOT do that across a function boundary. The first
// version of this file guarded via a helper call and "/preview-stories.json"
// survived into dist/. Hence: the check must sit inline, ahead of the fetch.
import { describe, expect, it } from 'vitest'
import { matchesPreview } from './devPreview'

const SOURCE = import.meta.glob('./devPreview.ts', {
  query: '?raw', import: 'default', eager: true,
}) as Record<string, string>
const src = Object.values(SOURCE)[0]

describe('preview mode is dev-only', () => {
  it('checks DEV inline, before the fetch it guards', () => {
    const gate = src.indexOf('if (!import.meta.env.DEV) return')
    const call = src.indexOf('fetch(')
    expect(gate, 'the inline DEV gate is gone').toBeGreaterThan(-1)
    expect(call, 'no fetch found — did the file change shape?').toBeGreaterThan(-1)
    expect(gate, 'the gate must precede the fetch in the same block').toBeLessThan(call)
    // Behind a helper call the minifier cannot fold it, and the fixture path
    // ships. Verified once by grepping dist/; kept honest here.
    expect(src).not.toMatch(/if \(!previewRequested\(/)
  })

  it('reads a local fixture only — never a remote host', () => {
    const urls = src.match(/fetch\(\s*'([^']+)'/g) ?? []
    expect(urls).toHaveLength(1)
    expect(urls[0]).toContain("'/preview-stories.json'")
  })
})

describe('matchesPreview', () => {
  it('is off unless explicitly asked for', () => {
    expect(matchesPreview('', 'stories')).toBe(false)
    expect(matchesPreview('?tab=feed', 'stories')).toBe(false)
    // Not a prefix or truthiness match: only the exact kind turns it on.
    expect(matchesPreview('?preview=1', 'stories')).toBe(false)
    expect(matchesPreview('?preview=storiesx', 'stories')).toBe(false)
    expect(matchesPreview('?preview=STORIES', 'stories')).toBe(false)
  })

  it('is on for the exact kind, wherever it sits in the query', () => {
    expect(matchesPreview('?preview=stories', 'stories')).toBe(true)
    expect(matchesPreview('?tab=feed&preview=stories', 'stories')).toBe(true)
  })
})
