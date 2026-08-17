// Algorithmic helpers for the Today briefing.
// All pure functions over the detection list — no Supabase, no React.

import type { DetectionRow } from './types'
import { isBrandTag } from './signal'

const SIZE_PTS: Record<string, number> = { dominant: 30, large: 24, medium: 16, small: 6 }

// "Worth a look" score: tier + size + primary + confidence + recency + novelty
// + discovery value. Returns 0-100 ish, used for ranking only.
export function worthScore(d: DetectionRow, knownHandles: Set<string>): number {
  const tier = d.creator_tier === 'tier_1' ? 35 : d.creator_tier === 'tier_2' ? 20 : 8
  const size = SIZE_PTS[d.size_in_frame ?? ''] ?? 0
  const primary = d.is_primary_subject ? 12 : 0
  const conf = (d.confidence ?? 0) * 15
  const novelty = knownHandles.has(d.creator_handle) ? 0 : 18 // new creator bonus
  const recency = d.posted_at ? recencyBoost(d.posted_at) : 0

  // Discovery value — see lib/signal.ts. The other terms cap out near 125
  // (tier 35 + size 30 + primary 12 + conf 15 + novelty 18 + recency 15), so
  // +40 deliberately makes this the single largest term, ahead of creator tier.
  // That is the correct encoding of what the tool is for: an untagged post from
  // a nano-creator beats a tagged post from a tier-1, because the brand already
  // knows about the tagged one. -60 keeps the brand's OWN posts out of the
  // hero — showing @drinkstelz its own content under "Worth a look" is noise.
  const sig = d.signal?.signal
  const unfindable = sig === 'visual_only' ? 40 : sig === 'brand_owned' ? -60 : 0

  return tier + size + primary + conf + novelty + recency + unfindable
}

function recencyBoost(iso: string): number {
  const hours = (Date.now() - new Date(iso).getTime()) / 3600_000
  if (hours < 6) return 15
  if (hours < 24) return 10
  if (hours < 72) return 4
  return 0
}

// Pick top N detections worth a look. Diversifies by creator (one per creator).
export function pickWorthALook(rows: DetectionRow[], n = 6): DetectionRow[] {
  // Build "known" set: creators with hits older than 7 days
  const cutoff = Date.now() - 7 * 24 * 3600_000
  const known = new Set(
    rows.filter((d) => d.posted_at && new Date(d.posted_at).getTime() < cutoff).map((d) => d.creator_handle),
  )
  const scored = rows
    .map((d) => ({ d, s: worthScore(d, known) }))
    .sort((a, b) => b.s - a.s)
  const picked: DetectionRow[] = []
  const seen = new Set<string>()
  for (const { d } of scored) {
    if (seen.has(d.creator_handle)) continue
    seen.add(d.creator_handle)
    picked.push(d)
    if (picked.length >= n) break
  }
  return picked
}

// Biggest fan today (or last 24h): creator with most hits in that window.
export function biggestFanToday(rows: DetectionRow[]): {
  handle: string
  hits: number
  tier: string | null
  spark: { d: string; n: number }[]
  topDetection: DetectionRow | null
} | null {
  const cutoff = Date.now() - 24 * 3600_000
  const today = rows.filter((d) => d.posted_at && new Date(d.posted_at).getTime() >= cutoff)
  if (!today.length) return null

  const counts = new Map<string, { handle: string; hits: number; tier: string | null; tops: DetectionRow[] }>()
  for (const d of today) {
    if (!d.creator_handle) continue
    const c = counts.get(d.creator_handle) ?? { handle: d.creator_handle, hits: 0, tier: d.creator_tier, tops: [] }
    c.hits++
    c.tops.push(d)
    counts.set(d.creator_handle, c)
  }
  const top = [...counts.values()].sort((a, b) => b.hits - a.hits)[0]
  if (!top) return null

  // 14-day sparkline for this creator
  const days = 14
  const buckets = new Map<string, number>()
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  for (let i = days - 1; i >= 0; i--) {
    const dt = new Date(start)
    dt.setDate(start.getDate() - i)
    buckets.set(dt.toISOString().slice(0, 10), 0)
  }
  for (const d of rows.filter((r) => r.creator_handle === top.handle)) {
    if (!d.posted_at) continue
    const k = d.posted_at.slice(0, 10)
    if (buckets.has(k)) buckets.set(k, (buckets.get(k) ?? 0) + 1)
  }
  const spark = [...buckets.entries()].map(([d, n]) => ({ d, n }))

  return {
    handle: top.handle,
    hits: top.hits,
    tier: top.tier,
    spark,
    topDetection: top.tops.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))[0] ?? null,
  }
}

// Spike detection: hashtag with biggest WoW jump.
export function detectSpike(rows: DetectionRow[]): {
  tag: string
  now: number
  prev: number
  pctDelta: number
  newCreators: number
} | null {
  const now = Date.now()
  const wk = 7 * 24 * 3600_000
  const last7 = rows.filter((d) => d.posted_at && now - new Date(d.posted_at).getTime() < wk)
  const prev7 = rows.filter((d) => {
    if (!d.posted_at) return false
    const age = now - new Date(d.posted_at).getTime()
    return age >= wk && age < 2 * wk
  })

  // Brand tags are excluded: #stelz "spiking" is not news, it is the baseline,
  // and it crowded out the context tags that actually signal something new.
  const tagsNow = new Map<string, Set<string>>()
  const tagsPrev = new Map<string, number>()
  for (const d of last7) for (const t of d.post_hashtags ?? []) {
    if (isBrandTag(t)) continue
    if (!tagsNow.has(t)) tagsNow.set(t, new Set())
    tagsNow.get(t)!.add(d.creator_handle)
  }
  for (const d of prev7) for (const t of d.post_hashtags ?? []) {
    if (isBrandTag(t)) continue
    tagsPrev.set(t, (tagsPrev.get(t) ?? 0) + 1)
  }

  let best: { tag: string; now: number; prev: number; pctDelta: number; newCreators: number } | null = null
  for (const [tag, creators] of tagsNow.entries()) {
    const nowCount = [...creators].length
    if (nowCount < 3) continue // ignore noise
    const prevCount = tagsPrev.get(tag) ?? 0
    const denom = Math.max(1, prevCount)
    const pct = ((nowCount - prevCount) / denom) * 100
    if (pct < 80) continue // require ≥80% jump
    if (!best || pct > best.pctDelta) {
      best = { tag, now: nowCount, prev: prevCount, pctDelta: pct, newCreators: nowCount }
    }
  }
  return best
}

// New since a timestamp (or last visit).
export function countNewSince(rows: DetectionRow[], iso: string | null): number {
  if (!iso) return 0
  return rows.filter((d) => d.posted_at && d.posted_at > iso).length
}

// New creators in the last N days (never seen before that).
export function newCreatorsLastDays(rows: DetectionRow[], days = 7): string[] {
  const cutoff = Date.now() - days * 24 * 3600_000
  const seenBefore = new Set(
    rows.filter((d) => d.posted_at && new Date(d.posted_at).getTime() < cutoff).map((d) => d.creator_handle),
  )
  const seenAfter = new Set(
    rows.filter((d) => d.posted_at && new Date(d.posted_at).getTime() >= cutoff).map((d) => d.creator_handle),
  )
  return [...seenAfter].filter((h) => !seenBefore.has(h))
}
