// Shared domain types. Backend-agnostic; Firestore reads conform to these.

export type DetectionMusic = {
  title?: string | null
  artist?: string | null
  musicId?: string | null
  original?: boolean
  playUrl?: string | null
  url?: string | null
  coverUrl?: string | null
}

export type DetectionExtras = {
  shareCount?: number
  collectCount?: number
  repostCount?: number
  isPinned?: boolean
  isAd?: boolean
  isSponsored?: boolean
  isSlideshow?: boolean
  duration?: number | null
  definition?: string | null
  width?: number | null
  height?: number | null
  effects?: string[]
  textLanguage?: string | null
  location?: { city?: string | null; country?: string | null } | null
  author?: {
    nickName?: string | null
    avatar?: string | null
    verified?: boolean
    signature?: string | null
    profileUrl?: string | null
    ttSeller?: boolean
    privateAccount?: boolean
  } | null
}

export type DetectionRow = {
  detection_id: string
  creator_id: string | null
  creator_handle: string
  creator_category: string | null
  platform: string
  product_line: string | null
  confidence: number | null
  size_in_frame: string | null
  is_primary_subject: boolean | null
  image_url: string | null
  stored_path: string | null
  post_url: string | null
  post_caption: string | null
  posted_at: string | null
  likes_count: number | null
  comments_count: number | null
  views_count: number | null
  follower_count: number | null
  creator_tier: string | null  // 'tier_1' | 'tier_2' | 'tier_3' | 'watch'
  verified: boolean | null
  context: string | null
  post_hashtags: string[] | null
  post_mentions: string[] | null
  music: DetectionMusic | null
  extras: DetectionExtras | null
  bbox?: unknown  // legacy — no longer rendered; kept for backward compat
  frame_idx?: number | null  // present when the detection came from a video frame
  post_id?: string | null    // groups multiple frame-hits of the same post
  frame_hits?: number        // UI-only: how many detections were collapsed into this row
  // Prompt v5 findings — what Gemini saw + where the brand appeared
  surface_type: string | null
  visible_text: string | null
  false_positive_risk: string | null
  people_count: number | null
  setting: string | null
  activity: string | null
  brand_id: string
  detected: boolean | null
  is_false_positive: boolean | null
}

export type ResonanceRow = {
  brand_id: string
  creator_handle: string
  platform: string
  srs: number
  graph: number | null
  hashtag: number | null
  subculture: number | null
  comment: number | null
  geo: number | null
  visual: number | null
  bootstrap_mode: 'cold' | 'warm' | 'hot' | null
  computed_at: string
  creator_id: string | null
  full_name: string | null
  follower_count: number | null
  tier: string | null
  status: string | null
  category: string | null
  relevance_score: number | null
  clear_visibility_hits: number | null
  latest_detection_at: string | null
  posts_scraped: number | null
}

// Image URL helper — Firebase pipeline stores fully-qualified URLs already
// (Cloud Storage public path or original CDN URL).
export function imageUrlFor(d: { stored_path?: string | null; image_url?: string | null }): string {
  return d.stored_path || d.image_url || ''
}

// Group key for frame/carousel dedupe: platform + parent post id.
// "instagram_123_456" (carousel slot) and "instagram_123" (parent) → same key.
export function parentPostKey(d: DetectionRow): string {
  const pid = d.post_id || d.detection_id
  const parts = pid.split('_')
  return parts.length >= 2 ? `${parts[0]}_${parts[1]}` : pid
}

// Collapse frame/carousel detections into one row per real post, keeping the
// highest-confidence hit as representative and merging review verdicts.
export function dedupeByPost(detections: DetectionRow[]): DetectionRow[] {
  const byPost = new Map<string, DetectionRow[]>()
  for (const d of detections) {
    const key = parentPostKey(d)
    const arr = byPost.get(key)
    if (arr) arr.push(d)
    else byPost.set(key, [d])
  }
  const out: DetectionRow[] = []
  for (const group of byPost.values()) {
    const detectedOnes = group.filter((g) => g.detected === true)
    const pool = detectedOnes.length > 0 ? detectedOnes : group
    const best = pool.reduce((a, b) => ((b.confidence ?? 0) > (a.confidence ?? 0) ? b : a))
    out.push({
      ...best,
      frame_hits: detectedOnes.length || group.length,
      verified: group.some((g) => g.verified === true) ? true : best.verified,
      is_false_positive: group.some((g) => g.is_false_positive === true) ? true : best.is_false_positive,
    })
  }
  out.sort((a, b) => (b.posted_at ?? '').localeCompare(a.posted_at ?? ''))
  return out
}
