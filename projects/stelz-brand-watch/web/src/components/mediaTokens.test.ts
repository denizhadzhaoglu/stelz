// Layout invariants have no other guard: Playwright/Chrome cannot run in this
// environment, so nothing can measure a rendered pixel. These assertions are
// what stop the "bizarrely large images" regression from coming back — it got
// in once precisely because a page-width cap was never there to begin with.
import { describe, expect, it } from 'vitest'
import { CARD_GRID, HAIRLINE_GRID, PAGE_WIDTH, TILE } from './mediaTokens'

describe('page width', () => {
  it('every shell caps its width and centres itself', () => {
    for (const [name, cls] of Object.entries(PAGE_WIDTH)) {
      expect(cls, `${name} must cap width`).toMatch(/max-w-\[\d+px\]/)
      expect(cls, `${name} must centre`).toContain('mx-auto')
    }
  })
})

describe('media tiles', () => {
  it('every grid tile caps its height', () => {
    // thumb is exempt: its parent sets a fixed px box (48/56px).
    for (const [name, cls] of Object.entries(TILE)) {
      if (name === 'thumb') continue
      expect(cls, `TILE.${name} must have a max-h`).toMatch(/max-h-\[\d+px\]/)
    }
  })

  it('grid cards stay under 300px — twice was not enough', () => {
    // Capping the page at 1440 was necessary and not sufficient: four columns
    // of 330x340 still read as "bizar groot". A monitoring grid is scanned, so
    // what matters is how many posts clear the fold, not how big one is.
    // hero/wide are judgement surfaces (review, drawer) and get more room.
    const GRID_TILES = ['card', 'square', 'story'] as const
    for (const name of GRID_TILES) {
      const m = TILE[name].match(/max-h-\[(\d+)px\]/)
      expect(m, `TILE.${name} must have a max-h`).not.toBeNull()
      expect(Number(m![1]), `TILE.${name}`).toBeLessThanOrEqual(300)
    }
  })

  it('caps stay under 500px — a card taller than that stops being a card', () => {
    for (const [name, cls] of Object.entries(TILE)) {
      const m = cls.match(/max-h-\[(\d+)px\]/)
      if (m) expect(Number(m[1]), `TILE.${name}`).toBeLessThanOrEqual(500)
    }
  })

  it('the story tile is portrait — a story cropped square is a different photo', () => {
    expect(TILE.story).toContain('aspect-[9/16]')
  })
})

describe('card grids', () => {
  it('keep adding columns instead of widening the ones they have', () => {
    for (const [name, grid] of [['CARD_GRID', CARD_GRID], ['HAIRLINE_GRID', HAIRLINE_GRID]] as const) {
      expect(grid, `${name} needs a 2xl step`).toMatch(/2xl:grid-cols-\d/)
      expect(grid, `${name} needs an xl step`).toMatch(/xl:grid-cols-\d/)
      // Five across at a laptop width. Four was the shipped setting that drew
      // the complaint, so the floor is written down rather than left to taste.
      // (?:^|\s) so this reads the xl step, not the "xl" inside "2xl".
      const xl = Number(grid.match(/(?:^|\s)xl:grid-cols-(\d)/)![1])
      expect(xl, `${name} xl step`).toBeGreaterThanOrEqual(5)
    }
  })
})

describe('no call site re-invents its own aspect ratio', () => {
  // The 4:3-vs-4:5 divergence (the same detection cropped differently in the
  // feed and the highlights row) came from thirteen hand-rolled aspect boxes.
  // Read through Vite's glob rather than node:fs — this project has no @types/node.
  const SOURCES = import.meta.glob('../**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
  // Landing is marketing chrome with decorative boxes, not detection media.
  const ALLOWED = /(MediaTile\.tsx|mediaTokens\.(ts|test\.ts)|Landing\.tsx)$/

  it('aspect-* classes live in MediaTile only', () => {
    const offenders = Object.entries(SOURCES)
      .filter(([path]) => !ALLOWED.test(path))
      .filter(([, src]) => /className[^\n]*\baspect-/.test(src))
      .map(([path]) => path.replace('../', ''))
    expect(offenders, 'use <MediaTile size="…"> instead of a raw aspect class').toEqual([])
  })
})
