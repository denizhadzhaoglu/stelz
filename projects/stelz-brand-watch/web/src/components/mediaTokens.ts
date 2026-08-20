// Layout invariants, in one object, because they decayed once already.
//
// Every image in the app used to size itself: each call site picked its own
// aspect ratio (the same detection rendered 4:5 in the feed and 4:3 in the
// highlights row) and nothing capped page width. An aspect-ratio box inside a
// w-full grid inside a w-full page scales forever — on a 2560px screen a feed
// card rendered 685px tall, on an ultrawide 960px: one card taller than the
// viewport. That is not a styling nit for a dashboard the client is shown.
//
// So: page width is capped here, tile heights are capped here, and grids add
// COLUMNS past 1440 instead of widening the ones they have. mediaTokens.test.ts
// asserts those invariants hold, which is the only way to defend a layout rule
// without a browser (Playwright cannot run in this environment).

/** Page shells. `narrow` is for judgement surfaces (Review) and empty states. */
export const PAGE_WIDTH = {
  default: 'w-full max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8 xl:px-10 py-6 lg:py-8',
  narrow: 'w-full max-w-[880px] mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8',
} as const

export type PageWidth = keyof typeof PAGE_WIDTH

/** The media scale. `max-h` is what stops the 1440–1536 band, where the page
 *  cap has not engaged yet and the grid still has four columns. */
export const TILE = {
  card: 'aspect-[4/5] max-h-[340px]',   // grid cards: feed, highlights, creator gallery
  wide: 'aspect-[4/3] max-h-[420px]',   // drawer hero
  hero: 'aspect-[4/3] max-h-[460px]',   // review hero — a judgement surface earns more room
  square: 'aspect-square max-h-[320px]', // 4-up strips, "other hits"
  thumb: 'aspect-square',                // parent sets a fixed px size (48/56px)
} as const

export type TileSize = keyof typeof TILE

// Card grids. The 2xl step is the point: past 1440 the container is capped, so
// extra width becomes an extra column rather than fatter cards.
export const CARD_GRID =
  'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4'

/** Same steps, hairline-separated (gap-px over a border-coloured background) —
 *  the house style for dense blocks, since box-shadow is globally disabled. */
export const HAIRLINE_GRID =
  'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-px bg-[var(--color-border)] border border-[var(--color-border)]'
