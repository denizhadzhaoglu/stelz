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

/** The media scale.
 *
 *  Capping page width was necessary but not sufficient: at 1440 with four
 *  columns a card still rendered ~330x340, and "bizar groot" was still the
 *  verdict. A monitoring grid is read by scanning it, so the number that
 *  matters is how many posts fit above the fold, not how big each one is.
 *  These caps plus the extra column below put roughly twice as much on screen
 *  at a typical laptop width, at ~60% of the previous tile area. */
export const TILE = {
  card: 'aspect-[4/5] max-h-[260px]',   // grid cards: feed, highlights, creator gallery
  wide: 'aspect-[4/3] max-h-[340px]',   // drawer hero
  hero: 'aspect-[4/3] max-h-[400px]',   // review hero — a judgement surface earns more room
  square: 'aspect-square max-h-[220px]', // 4-up strips, "other hits"
  story: 'aspect-[9/16] max-h-[200px]',  // stories strip — parent sets the width
  thumb: 'aspect-square',                // parent sets a fixed px size (48/56px)
} as const

export type TileSize = keyof typeof TILE

// Card grids. The steps are the point: extra width becomes an extra column
// rather than fatter cards, all the way up past the 1440 container cap.
export const CARD_GRID =
  'grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-3'

/** Same steps, hairline-separated (gap-px over a border-coloured background) —
 *  the house style for dense blocks, since box-shadow is globally disabled. */
export const HAIRLINE_GRID =
  'grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-px bg-[var(--color-border)] border border-[var(--color-border)]'
