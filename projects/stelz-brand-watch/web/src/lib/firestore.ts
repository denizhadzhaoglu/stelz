// Firestore reads + writes. Mirrors the domain types.

import {
  collection,
  query,
  where,
  orderBy,
  limit as fsLimit,
  getDocs,
  getDoc,
  doc,
  setDoc,
  updateDoc,
  deleteDoc,
  onSnapshot,
  serverTimestamp,
  Timestamp,
  type Unsubscribe,
  type QueryConstraint,
  type QueryDocumentSnapshot,
  type DocumentData,
} from 'firebase/firestore'
import { ref as storageRef, uploadBytes, getDownloadURL, deleteObject } from 'firebase/storage'
import { fbDb, fbAuth, fbStorage } from './firebase'
import type { DetectionRow, ResonanceRow } from './types'

// Default brand. Replace once brand switcher reads from auth context.
export const BRAND_ID = 'stelz'

// Cloud Functions base URL (Firebase Hosting rewrites or direct functions URL).
const FUNCTIONS_BASE =
  import.meta.env.VITE_FUNCTIONS_BASE ||
  'https://europe-west1-brand-audit-4b2cc.cloudfunctions.net'

function tsToIso(t: unknown): string | null {
  if (!t) return null
  if (t instanceof Timestamp) return t.toDate().toISOString()
  if (typeof t === 'string') return t
  if (typeof t === 'object' && t && 'seconds' in t) {
    return new Date((t as { seconds: number }).seconds * 1000).toISOString()
  }
  return null
}

function mapDetection(d: QueryDocumentSnapshot<DocumentData>, brandId: string): DetectionRow {
  const x = d.data()
  return {
    detection_id: d.id,
    creator_id: typeof x.creatorRef === 'string' ? x.creatorRef : null,
    creator_handle: x.creatorHandle ?? '',
    creator_category: x.creatorCategory ?? null,
    platform: x.platform ?? 'instagram',
    product_line: x.productLine ?? null,
    confidence: x.confidence ?? null,
    size_in_frame: x.sizeInFrame ?? null,
    is_primary_subject: x.isPrimarySubject ?? null,
    image_url: x.imageUrl ?? null,
    stored_path: x.storedPath ?? null,
    post_url: x.postUrl ?? null,
    post_caption: x.postCaption ?? null,
    posted_at: tsToIso(x.postedAt),
    likes_count: x.likesCount ?? null,
    comments_count: x.commentsCount ?? null,
    views_count: x.viewsCount ?? null,
    follower_count: x.followerCount ?? null,
    creator_tier: x.creatorTier ?? null,
    verified: x.verified ?? null,
    context: x.context ?? null,
    post_hashtags: x.postHashtags ?? null,
    post_mentions: x.postMentions ?? null,
    music: (x.music as DetectionRow['music']) ?? null,
    extras: (x.extras as DetectionRow['extras']) ?? null,
    surface_type: (x.surfaceType as string | null) ?? null,
    visible_text: (x.visibleText as string | null) ?? null,
    false_positive_risk: (x.falsePositiveRisk as string | null) ?? null,
    people_count: (x.peopleCount as number | null) ?? null,
    setting: (x.setting as string | null) ?? null,
    activity: (x.activity as string | null) ?? null,
    frame_idx: (x.frameIdx as number | null) ?? null,
    post_id: (x.postId as string | null) ?? null,
    brand_id: brandId,
    detected: x.detected ?? null,
    is_false_positive: x.isFalsePositive ?? null,
  }
}

function mapResonance(d: QueryDocumentSnapshot<DocumentData>, brandId: string): ResonanceRow {
  const x = d.data()
  return {
    brand_id: brandId,
    creator_handle: x.handle ?? '',
    platform: x.platform ?? 'instagram',
    srs: x.srs ?? 0,
    graph: x.graph ?? null,
    hashtag: x.hashtag ?? null,
    subculture: x.subculture ?? null,
    comment: x.comment ?? null,
    geo: x.geo ?? null,
    visual: x.visual ?? null,
    bootstrap_mode: x.bootstrapMode ?? null,
    computed_at: tsToIso(x.computedAt) ?? new Date().toISOString(),
    creator_id: null,
    full_name: x.fullName ?? null,
    follower_count: x.followerCount ?? null,
    tier: x.tier ?? null,
    status: x.status ?? null,
    category: x.category ?? null,
    relevance_score: x.relevanceScore ?? null,
    clear_visibility_hits: x.clearVisibilityHits ?? null,
    latest_detection_at: tsToIso(x.latestDetectionAt),
    posts_scraped: x.postsScraped ?? null,
  }
}

// ────────────── Reads ──────────────

export async function fbFetchDetections({
  brandId = BRAND_ID,
  limit = 500,
  detectedOnly = true,
  creatorHandle,
  sinceIso,
  minConfidence,
  maxConfidence,
  sizes,
  unreviewedOnly = false,
}: {
  brandId?: string
  limit?: number
  detectedOnly?: boolean
  creatorHandle?: string
  sinceIso?: string
  minConfidence?: number
  maxConfidence?: number
  sizes?: string[]
  unreviewedOnly?: boolean
} = {}): Promise<DetectionRow[]> {
  const col = collection(fbDb, 'brands', brandId, 'detections')
  const clauses: QueryConstraint[] = []
  if (detectedOnly) clauses.push(where('detected', '==', true))
  if (creatorHandle) clauses.push(where('creatorHandle', '==', creatorHandle))
  if (sinceIso) clauses.push(where('postedAt', '>=', Timestamp.fromDate(new Date(sinceIso))))
  if (typeof minConfidence === 'number') clauses.push(where('confidence', '>=', minConfidence))
  if (typeof maxConfidence === 'number') clauses.push(where('confidence', '<', maxConfidence))
  if (sizes?.length) clauses.push(where('sizeInFrame', 'in', sizes))
  if (unreviewedOnly) clauses.push(where('verified', '==', null), where('isFalsePositive', '==', null))
  clauses.push(orderBy('postedAt', 'desc'), fsLimit(limit))
  const snap = await getDocs(query(col, ...clauses))
  return snap.docs.map((d) => mapDetection(d, brandId))
}

export async function fbFetchResonanceForCreator(handle: string, brandId = BRAND_ID): Promise<ResonanceRow | null> {
  const col = collection(fbDb, 'brands', brandId, 'resonance')
  const snap = await getDocs(query(col, where('handle', '==', handle), fsLimit(1)))
  if (snap.empty) return null
  return mapResonance(snap.docs[0], brandId)
}

export async function fbFetchTopResonance(limit = 50, brandId = BRAND_ID): Promise<ResonanceRow[]> {
  const col = collection(fbDb, 'brands', brandId, 'resonance')
  const snap = await getDocs(query(col, orderBy('srs', 'desc'), fsLimit(limit)))
  return snap.docs.map((d) => mapResonance(d, brandId))
}

export async function fbFetchBrand(brandId = BRAND_ID) {
  const snap = await getDoc(doc(fbDb, 'brands', brandId))
  return snap.exists() ? { id: snap.id, ...snap.data() } : null
}

// Lightweight collection counts (uses Firestore aggregation, cheap)
export async function fbFetchPipelineCounts(brandId = BRAND_ID): Promise<{
  creators: number
  posts: number
  detections: number
  detectionsHit: number
  discoveryQueue: number
}> {
  const counts = await Promise.all([
    getDocs(query(collection(fbDb, 'brands', brandId, 'creators'), fsLimit(1000))).then((s) => s.size),
    getDocs(query(collection(fbDb, 'brands', brandId, 'posts'), fsLimit(1000))).then((s) => s.size),
    getDocs(query(collection(fbDb, 'brands', brandId, 'detections'), fsLimit(1000))).then((s) => s.size),
    getDocs(query(collection(fbDb, 'brands', brandId, 'detections'), where('detected', '==', true), fsLimit(1000))).then((s) => s.size),
    getDocs(query(collection(fbDb, 'brands', brandId, 'discoveryQueue'), fsLimit(1000))).then((s) => s.size),
  ])
  return {
    creators: counts[0],
    posts: counts[1],
    detections: counts[2],
    detectionsHit: counts[3],
    discoveryQueue: counts[4],
  }
}

export async function fbFetchLatestScanRun(brandId = BRAND_ID) {
  const snap = await getDocs(query(
    collection(fbDb, 'brands', brandId, 'scanRuns'),
    orderBy('finishedAt', 'desc'),
    fsLimit(1),
  ))
  return snap.empty ? null : { id: snap.docs[0].id, ...snap.docs[0].data() }
}

// ────────────── Writes (via Cloud Functions) ──────────────

async function authedFetch(path: string, body: unknown) {
  const user = fbAuth.currentUser
  if (!user) throw new Error('Not signed in')
  const token = await user.getIdToken()
  const res = await fetch(`${FUNCTIONS_BASE}/${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${path} failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function fbRateDetection(detectionId: string, verdict: 'confirmed' | 'plausible' | 'rejected') {
  await authedFetch('api_rate_detection', { brandId: BRAND_ID, detectionId, verdict })
}

// ────────────── Reference images ──────────────

export type ReferenceImage = {
  id: string
  storagePath: string
  url: string
  productLine?: string | null
  uploadedAt: string | null
  size?: number
  width?: number
  height?: number
}

export async function fbListReferenceImages(brandId = BRAND_ID): Promise<ReferenceImage[]> {
  const col = collection(fbDb, 'brands', brandId, 'referenceImages')
  const snap = await getDocs(query(col, orderBy('uploadedAt', 'desc')))
  return snap.docs.map((d) => {
    const x = d.data()
    return {
      id: d.id,
      storagePath: x.storagePath ?? '',
      url: x.url ?? '',
      productLine: x.productLine ?? null,
      uploadedAt: x.uploadedAt instanceof Timestamp ? x.uploadedAt.toDate().toISOString() : null,
      size: x.size,
      width: x.width,
      height: x.height,
    }
  })
}

export async function fbUploadReferenceImage(
  file: File,
  productLine?: string,
  brandId = BRAND_ID,
): Promise<ReferenceImage> {
  if (!fbAuth.currentUser) throw new Error('Not signed in')
  // sanitize filename to a safe doc id + path
  const safeName = file.name.replace(/[^a-zA-Z0-9._-]/g, '_').slice(-80)
  const docId = `${Date.now()}_${safeName}`
  const path = `references/${brandId}/${docId}`

  const sref = storageRef(fbStorage, path)
  await uploadBytes(sref, file, { contentType: file.type || 'image/jpeg' })
  const url = await getDownloadURL(sref)

  await setDoc(doc(fbDb, 'brands', brandId, 'referenceImages', docId), {
    storagePath: path,
    url,
    productLine: productLine ?? null,
    size: file.size,
    uploadedAt: serverTimestamp(),
    uploadedBy: fbAuth.currentUser.uid,
  })

  return {
    id: docId,
    storagePath: path,
    url,
    productLine: productLine ?? null,
    uploadedAt: new Date().toISOString(),
    size: file.size,
  }
}

export async function fbDeleteReferenceImage(
  id: string,
  storagePath: string,
  brandId = BRAND_ID,
): Promise<void> {
  await deleteDoc(doc(fbDb, 'brands', brandId, 'referenceImages', id))
  try {
    await deleteObject(storageRef(fbStorage, storagePath))
  } catch (e) {
    console.warn('storage delete failed (doc removed)', e)
  }
}

export async function fbBootstrapBrand(brandName = 'Stelz') {
  return authedFetch('api_bootstrap_brand', { brandId: BRAND_ID, brandName })
}

// Per-step scan API. UI calls these sequentially and shows progress between them.
export async function fbStepHashtags(perTag = 500, maxTags = 50) {
  return authedFetch('api_step_hashtags', { brandId: BRAND_ID, perTag, maxTags })
}
export async function fbStepCreators(maxCreators = 80, postsPer = 8) {
  return authedFetch('api_step_creators', { brandId: BRAND_ID, maxCreators, postsPer })
}
// fbStepScore removed in productization cleanup — SRS already covers the signal.
export async function fbStepSrs() {
  return authedFetch('api_step_srs', { brandId: BRAND_ID })
}

// ────────────── Brand settings (write via Cloud Function) ──────────────

export type BrandDoc = {
  id: string
  name?: string
  slug?: string
  website?: string
  visualIdentity?: string
  wordmarkAliases?: string[]
  productLines?: Record<string, string>
  confidenceMin?: number
  embeddingThreshold?: number
  dailyBudgetUsd?: number
  hashtagYield?: Record<string, number>
  visualCentroidComputedAt?: string | null
  visualCentroidRefCount?: number
}

export async function fbGetBrand(brandId = BRAND_ID): Promise<BrandDoc | null> {
  const snap = await getDoc(doc(fbDb, 'brands', brandId))
  if (!snap.exists()) return null
  const x = snap.data()
  return {
    id: snap.id,
    name: x.name,
    slug: x.slug,
    website: x.website,
    visualIdentity: x.visualIdentity,
    wordmarkAliases: x.wordmarkAliases,
    productLines: x.productLines,
    confidenceMin: x.confidenceMin,
    embeddingThreshold: x.embeddingThreshold,
    dailyBudgetUsd: x.dailyBudgetUsd,
    hashtagYield: x.hashtagYield,
    visualCentroidComputedAt:
      x.visualCentroidComputedAt instanceof Timestamp
        ? x.visualCentroidComputedAt.toDate().toISOString()
        : null,
    visualCentroidRefCount: x.visualCentroidRefCount,
  }
}

export async function fbUpdateBrandSettings(
  patch: Partial<BrandDoc>,
  opts?: { hashtagPool?: { tag: string; platform: 'instagram' | 'tiktok'; priority: number; active: boolean }[]; replaceHashtags?: boolean },
) {
  return authedFetch('api_brand_settings_update', {
    brandId: BRAND_ID,
    patch,
    hashtagPool: opts?.hashtagPool,
    replaceHashtags: opts?.replaceHashtags,
  })
}

export async function fbRecomputeCentroid() {
  return authedFetch('api_recompute_centroid', { brandId: BRAND_ID })
}

// ────────────── Hashtag pool reads ──────────────

export type HashtagPoolEntry = {
  id: string
  tag: string
  platform: 'instagram' | 'tiktok'
  priority: number
  active: boolean
}

export async function fbListHashtagPool(brandId = BRAND_ID): Promise<HashtagPoolEntry[]> {
  const snap = await getDocs(collection(fbDb, 'brands', brandId, 'hashtagPool'))
  return snap.docs.map((d) => {
    const x = d.data()
    return {
      id: d.id,
      tag: x.tag ?? '',
      platform: x.platform ?? 'instagram',
      priority: x.priority ?? 5,
      active: x.active ?? true,
    }
  })
}

// ────────────── Daily usage (Settings → Usage card) ──────────────

export type UsageDay = {
  day: string
  apify_runs?: number
  gemini_flash_calls?: number
  gemini_embed_calls?: number
  ocr_calls?: number
  detections_written?: number
  detections_hit?: number
  estimated_spend_usd?: number
}

export async function fbListUsage(days = 14, brandId = BRAND_ID): Promise<UsageDay[]> {
  const snap = await getDocs(
    query(collection(fbDb, 'brands', brandId, 'usage'), orderBy('__name__', 'desc'), fsLimit(days)),
  )
  return snap.docs.map((d) => {
    const x = d.data() as Record<string, number>
    const COSTS: Record<string, number> = {
      gemini_flash_calls: 0.00075,
      gemini_embed_calls: 0.0001,
      apify_runs: 0.1,
    }
    let est = 0
    for (const k of Object.keys(COSTS)) est += (x[k] ?? 0) * COSTS[k]
    return { day: d.id, ...(x as Record<string, number>), estimated_spend_usd: est }
  })
}

// ────────────── Inbox subscription ──────────────

export type InboxItem = {
  id: string
  type: 'tier1_hit' | 'spike' | 'scan_complete' | 'review_pending' | string
  brandId: string
  body: string
  link?: string | null
  meta?: Record<string, unknown>
  read: boolean
  createdAt: string | null
}

export function fbSubscribeInbox(
  uid: string,
  onChange: (items: InboxItem[]) => void,
): Unsubscribe {
  const q = query(
    collection(fbDb, 'users', uid, 'inbox'),
    orderBy('createdAt', 'desc'),
    fsLimit(50),
  )
  return onSnapshot(q, (snap) => {
    onChange(
      snap.docs.map((d) => {
        const x = d.data()
        return {
          id: d.id,
          type: x.type ?? 'event',
          brandId: x.brandId ?? '',
          body: x.body ?? '',
          link: x.link ?? null,
          meta: x.meta ?? {},
          read: !!x.read,
          createdAt: x.createdAt instanceof Timestamp ? x.createdAt.toDate().toISOString() : null,
        }
      }),
    )
  })
}

export type ScanState = {
  startedAt: string | null
  finishedAt: string | null
  hashtagQueued: number
  hashtagDone: number
  postsWritten: number
  detectTasksEnqueued: number
  detectionsCompleted: number
  detectionsHit: number
  tags: string[]
  lastActivityAt: string | null
  skippedCount: number
  endReason: string | null
}

export function fbSubscribeScanState(
  onChange: (state: ScanState | null) => void,
  brandId = BRAND_ID,
): Unsubscribe {
  const ref = doc(fbDb, 'brands', brandId)
  return onSnapshot(ref, (snap) => {
    const x = snap.data()
    const s = (x?.scan ?? null) as Record<string, unknown> | null
    if (!s) { onChange(null); return }
    onChange({
      startedAt: s.startedAt instanceof Timestamp ? s.startedAt.toDate().toISOString() : null,
      finishedAt: s.finishedAt instanceof Timestamp ? s.finishedAt.toDate().toISOString() : null,
      hashtagQueued: (s.hashtagQueued as number) ?? 0,
      hashtagDone: (s.hashtagDone as number) ?? 0,
      postsWritten: (s.postsWritten as number) ?? 0,
      detectTasksEnqueued: (s.detectTasksEnqueued as number) ?? 0,
      detectionsCompleted: (s.detectionsCompleted as number) ?? 0,
      detectionsHit: (s.detectionsHit as number) ?? 0,
      tags: (s.tags as string[]) ?? [],
      lastActivityAt: s.lastActivityAt instanceof Timestamp ? s.lastActivityAt.toDate().toISOString() : null,
      skippedCount: (s.skippedCount as number) ?? 0,
      endReason: (s.endReason as string) ?? null,
    })
  })
}

export async function fbMarkInboxRead(itemId: string) {
  if (!fbAuth.currentUser) return
  const uid = fbAuth.currentUser.uid
  await updateDoc(doc(fbDb, 'users', uid, 'inbox', itemId), { read: true })
}

// ────────────── Debug: detection attempt log + scan runs ──────────────

export type DetectLog = {
  id: string
  postId: string
  imageUrl: string
  outcome: 'wrote' | 'skipped' | 'error' | string
  reason: string
  createdAt: string | null
  detected?: boolean
  cosine?: number
  threshold?: number
  term?: string
  errMsg?: string
  confidence?: number | null
  productLine?: string | null
  hint?: string
  ocrText?: string
  geminiContext?: string
  centroidMissing?: boolean
}

export async function fbListDetectLog(limit = 50, brandId = BRAND_ID): Promise<DetectLog[]> {
  const snap = await getDocs(
    query(
      collection(fbDb, 'brands', brandId, 'detectLog'),
      orderBy('createdAt', 'desc'),
      fsLimit(limit),
    ),
  )
  return snap.docs.map((d) => {
    const x = d.data() as Record<string, unknown>
    return {
      id: d.id,
      postId: (x.postId as string) ?? '',
      imageUrl: (x.imageUrl as string) ?? '',
      outcome: (x.outcome as string) ?? 'unknown',
      reason: (x.reason as string) ?? '',
      createdAt: x.createdAt instanceof Timestamp ? x.createdAt.toDate().toISOString() : null,
      detected: x.detected as boolean | undefined,
      cosine: x.cosine as number | undefined,
      threshold: x.threshold as number | undefined,
      term: x.term as string | undefined,
      errMsg: x.errMsg as string | undefined,
      confidence: x.confidence as number | null | undefined,
      productLine: x.productLine as string | null | undefined,
      hint: x.hint as string | undefined,
    }
  })
}

export type ScanRun = {
  id: string
  type: string
  status: string
  stats: Record<string, unknown>
  startedAt: string | null
  finishedAt: string | null
}

export type VideoLog = {
  id: string
  postId: string
  videoUrl: string
  stage: 'received' | 'download' | 'frames' | 'analyse' | 'done' | string
  status: string  // 'ok' | 'failed' | 'hit' | 'no_hit' | 'skipped_budget' | 'no_post' | etc
  createdAt: string | null
  // optional debug fields
  reason?: string
  bytes?: number
  bytesAttempted?: number
  ms?: number
  totalMs?: number
  framesExtracted?: number
  framesAnalysed?: number
  info?: Record<string, unknown>
  frames?: Array<{ idx: number; source?: string; detected?: boolean; err?: string }>
  hitFrame?: { frame_idx: number; source?: string } | null
}

export async function fbListVideoLog(limit = 100, brandId = BRAND_ID): Promise<VideoLog[]> {
  const snap = await getDocs(
    query(
      collection(fbDb, 'brands', brandId, 'videoLog'),
      orderBy('createdAt', 'desc'),
      fsLimit(limit),
    ),
  )
  return snap.docs.map((d) => {
    const x = d.data() as Record<string, unknown>
    return {
      id: d.id,
      postId: (x.postId as string) ?? '',
      videoUrl: (x.videoUrl as string) ?? '',
      stage: (x.stage as string) ?? 'received',
      status: (x.status as string) ?? '',
      createdAt: x.createdAt instanceof Timestamp ? x.createdAt.toDate().toISOString() : null,
      reason: x.reason as string | undefined,
      bytes: x.bytes as number | undefined,
      bytesAttempted: x.bytesAttempted as number | undefined,
      ms: x.ms as number | undefined,
      totalMs: x.totalMs as number | undefined,
      framesExtracted: x.framesExtracted as number | undefined,
      framesAnalysed: x.framesAnalysed as number | undefined,
      info: x.info as Record<string, unknown> | undefined,
      frames: x.frames as VideoLog['frames'],
      hitFrame: (x.hitFrame as VideoLog['hitFrame']) ?? null,
    }
  })
}

export type ScrapeLog = {
  id: string
  tag: string
  platform: 'instagram' | 'tiktok' | string
  itemsReturned: number
  error?: string
  source: 'scan_hashtags' | 'scan_creators' | string
  createdAt: string | null
  breakdown?: {
    kinds?: Record<string, number>
    hasVideoUrl?: number
    hasDisplayUrl?: number
    hasDownloadAddr?: number
  }
  sampleKeys?: string[]
  sample?: Record<string, unknown>
  diag?: {
    landedUrl?: string | null
    captchaDetected?: boolean
    itemListResponses?: number
    itemListNonOk?: number
    itemListZero?: number
    detailResponseSeen?: boolean
    landedTitle?: string | null
    blockedReason?: string | null
    elapsedMs?: number
    attempts?: number
    transportError?: string | null
    proxy?: string | null
  }
}

export async function fbListScrapeLog(limit = 50, brandId = BRAND_ID): Promise<ScrapeLog[]> {
  const snap = await getDocs(
    query(
      collection(fbDb, 'brands', brandId, 'scrapeLog'),
      orderBy('createdAt', 'desc'),
      fsLimit(limit),
    ),
  )
  return snap.docs.map((d) => {
    const x = d.data() as Record<string, unknown>
    return {
      id: d.id,
      tag: (x.tag as string) ?? '',
      platform: (x.platform as string) ?? '',
      itemsReturned: (x.itemsReturned as number) ?? 0,
      error: x.error as string | undefined,
      source: (x.source as string) ?? '',
      createdAt: x.createdAt instanceof Timestamp ? x.createdAt.toDate().toISOString() : null,
      breakdown: x.breakdown as ScrapeLog['breakdown'],
      sampleKeys: x.sampleKeys as string[] | undefined,
      sample: x.sample as Record<string, unknown> | undefined,
      diag: x.diag as ScrapeLog['diag'],
    }
  })
}

export async function fbListScanRuns(limit = 20, brandId = BRAND_ID): Promise<ScanRun[]> {
  const snap = await getDocs(
    query(
      collection(fbDb, 'brands', brandId, 'scanRuns'),
      orderBy('finishedAt', 'desc'),
      fsLimit(limit),
    ),
  )
  return snap.docs.map((d) => {
    const x = d.data() as Record<string, unknown>
    return {
      id: d.id,
      type: (x.type as string) ?? '',
      status: (x.status as string) ?? '',
      stats: (x.stats as Record<string, unknown>) ?? {},
      startedAt: x.startedAt instanceof Timestamp ? x.startedAt.toDate().toISOString() : null,
      finishedAt: x.finishedAt instanceof Timestamp ? x.finishedAt.toDate().toISOString() : null,
    }
  })
}

export async function fbMarkAllInboxRead(items: InboxItem[]) {
  if (!fbAuth.currentUser) return
  const uid = fbAuth.currentUser.uid
  await Promise.all(
    items.filter((i) => !i.read).map((i) => updateDoc(doc(fbDb, 'users', uid, 'inbox', i.id), { read: true })),
  )
}
