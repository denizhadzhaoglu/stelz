// Every event Stëlz runs, as data. One file per event; this module is the list.
//
// WHY JSON AND NOT TYPESCRIPT. The roster used to live in a TS template literal
// (data/lowlandsSeed.ts) that FOUR Python scripts read by splitting the file on
// backticks — `read_text().split("`", 1)[1].rsplit("`", 1)[0]`, copied verbatim
// into 62, 70, 71 and 72, each then re-parsing the TSV and each independently
// re-discovering that "Geen" means "this person has no TikTok". The hashtags
// lived in a fifth place, hard-coded in 73. Six copies of one fact is how a
// roster change lands in the scrape but not the dashboard.
//
// JSON is the only format both languages read without a parser of our own.
// Vite handles the import natively (resolveJsonModule in tsconfig.app.json);
// Python has json.load. tools/stelz_brand_watch/_events.py is the other half.
//
// THE FIELDS THAT ARE NOT OBVIOUS
//
//   projectId   The existing Firestore project doc. fs.composite_id keeps
//               spaces, so "Stelz Lowlands" is the doc id "stelz lowlands".
//               Not derivable from `id` — don't try.
//   window      start/end are the festival. preDays/postDays widen it into the
//               period a brand actually buys: people post the packing video
//               three days out and the recap a week later. 2026-08-20..23 with
//               3/7 gives 17 t/m 30 aug.
//   tiktok      null, not the string "Geen". Three people on this roster have
//               no TikTok and that is a fact about them, not a parse failure.
//   family      Drives the scrape budget, and it is measured, not guessed:
//               lib/hashtags.py puts brand tags at 55.6% post-level conversion
//               and event tags at roughly 0%. So brand tags are taken whole and
//               event tags are sampled — see discovery.perTag / perBrandTag.
//
// Dates are 'YYYY-MM-DD' strings on purpose. Every comparison in this codebase
// is already lexicographic on ISO text, and a Date here would only add a
// timezone to something that has none: a festival day is a calendar day.

import lowlands2026 from './lowlands-2026.json'

export type HashtagFamily = 'brand' | 'event'

export type EventRosterMember = {
  name: string
  instagram: string
  /** null = this person has no TikTok. Not "unknown", not "not yet filled in". */
  tiktok: string | null
}

export type EventHashtag = { tag: string; family: HashtagFamily }

export type EventWindow = {
  /** First day of the event itself, 'YYYY-MM-DD'. */
  start: string
  /** Last day of the event itself, inclusive. */
  end: string
  /** Days before `start` that still count as this event (the run-up). */
  preDays: number
  /** Days after `end` that still count (recaps, edits posted later). */
  postDays: number
}

export type StelzEvent = {
  id: string
  name: string
  projectId: string
  venue: string
  window: EventWindow
  roster: EventRosterMember[]
  hashtags: EventHashtag[]
  discovery: {
    perTag: number
    perBrandTag: number
    /** IG hashtag scraping is billed per result; event tags there are huge and
     *  convert at ~0%, so they stay off unless someone turns them on. */
    instagramEventTags: boolean
  }
}

export const EVENTS: StelzEvent[] = [lowlands2026 as StelzEvent]

export function getEvent(id: string | undefined): StelzEvent | null {
  if (!id) return null
  return EVENTS.find((e) => e.id === id) ?? null
}
