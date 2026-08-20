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

  it('reads local fixtures only — never a remote host', () => {
    // There is one fetch, and every path handed to it is root-relative. A
    // preview that could pull from a URL would be a data-exfiltration switch
    // sitting in a client dashboard, whatever the DEV gate says.
    expect(src.match(/\bfetch\(/g) ?? []).toHaveLength(1)
    const paths = [...src.matchAll(/'(\/[\w-]*\.json)'/g)].map((m) => m[1])
    expect(paths.length).toBeGreaterThan(0)
    for (const p of paths) {
      expect(p, `${p} must be root-relative`).toMatch(/^\/[\w-]+\.json$/)
    }
  })

  it('wraps every fixture path in a DEV ternary so the build drops it', () => {
    // Not decoration. Passing the path straight into usePreviewFixture leaves
    // the literal in dist/: the minifier folds the gate inside the hook but
    // cannot reach the call site to delete its argument. This shipped twice
    // before being caught by grepping the built bundle.
    // `return ...` anchors this to call sites; without it the regex also
    // matched the function's own declaration and read its parameter list.
    const calls = [...src.matchAll(/return usePreviewFixture<[^>]+>\(([^\n]*)\)/g)].map((m) => m[1])
    expect(calls.length).toBeGreaterThan(0)
    for (const c of calls) {
      expect(c, `argument must be DEV-gated: ${c}`).toContain("import.meta.env.DEV ? '/")
      expect(c, `non-DEV branch must be empty: ${c}`).toContain(": ''")
    }
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
