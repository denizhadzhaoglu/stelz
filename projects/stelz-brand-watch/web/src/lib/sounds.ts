// Sound/music aggregation — ONE key, used everywhere.
//
// WHY THIS MODULE EXISTS
// The same music data was being aggregated in three places with two different
// keys: the dashboard card keyed by `musicId || title|artist`, while the
// community profiles keyed by title alone — so two distinct original sounds
// (both titled "original sound", different musicId) merged into one row there,
// and the numbers on the two surfaces could never match. A drill-down page on
// top of that would have made the mismatch a client-visible bug ("the card
// says 12, the page says 9"). Every aggregation now goes through soundKey().
//
// KEY SEMANTICS
//   musicId            when present — the only stable identity (TikTok only)
//   "title|artist"     otherwise (IG reels carry no musicId)
//   null               unidentifiable (no id AND no title) — excluded from all
//                      aggregation. The old key for these was the literal
//                      string "|", which is not blank, so every unreadable
//                      track pooled into one bucket that topped the chart as
//                      "(untitled)" with 306 hits. See Home.tsx history.
//
// HONESTY NOTE for anything built on this: `musicId` is TikTok-only, IG-reel
// rows carry only title/artist, and IG posts found via creator deep-scans
// before the parity fix carry no music at all. "Trend" here means trend within
// our own hits — not platform-wide trending, which nothing here measures.

import type { DetectionMusic, DetectionRow } from './types'

export function soundKey(m: DetectionMusic | null | undefined): string | null {
  if (!m) return null
  if (m.musicId) return m.musicId
  const title = (m.title || '').trim()
  if (!title) return null
  return `${title}|${(m.artist || '').trim()}`
}

export function soundLabel(m: DetectionMusic | null | undefined): string {
  return m?.title?.trim() || 'Original sound'
}

/** Route helper — keys contain arbitrary characters ("title|artist"). */
export function soundHref(key: string): string {
  return `/sounds/${encodeURIComponent(key)}`
}

export type SoundTally = {
  key: string
  label: string
  artist: string | null
  url: string | null
  original: boolean
  hits: number
  /** Distinct creators — the collab-scouting number. */
  creators: number
}

/** Aggregate deduped detection rows into a sound leaderboard, most hits first. */
export function tallySounds(rows: DetectionRow[]): SoundTally[] {
  const by = new Map<string, SoundTally & { _handles: Set<string> }>()
  for (const d of rows) {
    if (d.detected !== true) continue
    const key = soundKey(d.music)
    if (!key) continue
    const m = d.music!
    let cur = by.get(key)
    if (!cur) {
      cur = {
        key,
        label: soundLabel(m),
        artist: m.artist?.trim() || null,
        url: m.url || null,
        original: !!m.original,
        hits: 0,
        creators: 0,
        _handles: new Set<string>(),
      }
      by.set(key, cur)
    }
    cur.hits += 1
    if (d.creator_handle) cur._handles.add(d.creator_handle)
    // First non-null wins for url; rows of one sound may differ in coverage.
    if (!cur.url && m.url) cur.url = m.url
  }
  return [...by.values()]
    .map(({ _handles, ...t }) => ({ ...t, creators: _handles.size }))
    .sort((a, b) => b.hits - a.hits || b.creators - a.creators)
}

export type SoundCreator = {
  handle: string
  hits: number
  nickName: string | null
  avatar: string | null
  followers: number | null
  /** Sum of likes on this creator's posts with this sound — proxy for pull. */
  likes: number
}

export type SoundRollup = {
  key: string
  label: string
  artist: string | null
  original: boolean
  url: string | null
  coverUrl: string | null
  playUrl: string | null
  hits: number
  platforms: { instagram: number; tiktok: number }
  creators: SoundCreator[]
  /** posted_at ISO strings for the caller to bucket into a trend chart. */
  postedAts: string[]
  sentiment: { positive: number; neutral: number; negative: number; promotional: number; unscored: number }
}

/** Everything about one sound, for the drill-down page. Returns null when no
 * row matches — the page renders a not-found state, not an empty shell. */
export function rollupSound(rows: DetectionRow[], key: string): SoundRollup | null {
  const mine = rows.filter((d) => d.detected === true && soundKey(d.music) === key)
  if (!mine.length) return null

  const byCreator = new Map<string, SoundCreator>()
  const sentiment = { positive: 0, neutral: 0, negative: 0, promotional: 0, unscored: 0 }
  const platforms = { instagram: 0, tiktok: 0 }
  const postedAts: string[] = []
  let url: string | null = null
  let coverUrl: string | null = null
  let playUrl: string | null = null

  for (const d of mine) {
    const m = d.music!
    url = url || m.url || null
    coverUrl = coverUrl || m.coverUrl || null
    playUrl = playUrl || m.playUrl || null
    if (d.platform === 'tiktok') platforms.tiktok += 1
    else platforms.instagram += 1
    if (d.posted_at) postedAts.push(d.posted_at)
    // Null is "not scored yet", never neutral — same rule as everywhere else.
    if (d.sentiment) sentiment[d.sentiment] += 1
    else sentiment.unscored += 1

    const h = d.creator_handle
    if (!h) continue
    let c = byCreator.get(h)
    if (!c) {
      c = { handle: h, hits: 0, nickName: null, avatar: null, followers: null, likes: 0 }
      byCreator.set(h, c)
    }
    c.hits += 1
    c.likes += d.likes_count ?? 0
    c.nickName = c.nickName || d.extras?.author?.nickName || null
    c.avatar = c.avatar || d.extras?.author?.avatar || null
    c.followers = c.followers ?? d.follower_count ?? null
  }

  const first = mine[0].music!
  return {
    key,
    label: soundLabel(first),
    artist: first.artist?.trim() || null,
    original: mine.some((d) => !!d.music?.original),
    url, coverUrl, playUrl,
    hits: mine.length,
    platforms,
    creators: [...byCreator.values()].sort((a, b) => b.hits - a.hits || b.likes - a.likes),
    postedAts,
    sentiment,
  }
}
