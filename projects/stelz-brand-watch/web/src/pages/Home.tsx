// Single-page home with 5 tabs. Replaces: Today, Dashboard/Feed, Highlights,
// Outreach (inline action on Creator detail), Reports, Discover, Moderator.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  PageShell, Card, Badge, Button, Img, Input, Tabs, PRODUCT_LINE_LABEL,
} from '../components/ui'
import { Sparkline, LineChart, BarChart, Donut, StackedDayBars, bucketByDay, type Series } from '../components/Chart'
import { DetectionDrawer } from '../components/DetectionDrawer'
import { fetchDetections, fetchTopResonance, loadState, markSeen, rateDetection, type DetectionRow, type ResonanceRow } from '../lib/data'
import { imageUrlFor, parentPostKey, dedupeByPost } from '../lib/types'
import {
  fbBootstrapBrand, fbStepHashtags, fbStepCreators, fbStepSrs,
  fbFetchPipelineCounts, fbSubscribeScanState, type ScanState,
} from '../lib/firestore'
import {
  pickWorthALook, biggestFanToday, detectSpike, countNewSince,
} from '../lib/score'

type Tab = 'briefing' | 'feed' | 'review' | 'creators'
type PipelineCounts = { creators: number; posts: number; detections: number; detectionsHit: number; discoveryQueue: number }

// Charts + list default window (was user-selectable 7/30/90; simplified).
const DAYS_WINDOW = 30

const CACHE_KEY = 'spotthebrand:dashboard-cache:v2'
type DashboardCache = {
  savedAt: number
  detections: DetectionRow[]
  resonance: ResonanceRow[]
  counts: PipelineCounts | null
}

function loadCache(): DashboardCache | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as DashboardCache
    if (!Array.isArray(parsed.detections)) return null
    return parsed
  } catch { return null }
}

function saveCache(c: DashboardCache) {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(c)) } catch { /* quota — ignore */ }
}

export default function Home() {
  const [tab, setTab] = useState<Tab>('briefing')
  const [activeDetection, setActiveDetection] = useState<DetectionRow | null>(null)

  // Boot from cache if we have one — the dashboard is visible instantly,
  // even before the fresh Firestore reads finish. `refreshing` shows a
  // subtle spinner in the header while we're pulling new data on top.
  const [detections, setDetections] = useState<DetectionRow[]>(() => loadCache()?.detections ?? [])
  const [resonance, setResonance] = useState<ResonanceRow[]>(() => loadCache()?.resonance ?? [])
  const [counts, setCounts] = useState<PipelineCounts | null>(() => loadCache()?.counts ?? null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const hasCache = detections.length > 0 || !!counts
  const loading = !hasCache && refreshing

  const [lastSeenAt] = useState<string | null>(() => loadState().lastSeenAt)
  useEffect(() => { markSeen() }, [])

  const refreshData = useCallback(async () => {
    setRefreshing(true)
    try {
      const [d, r, c] = await Promise.all([
        fetchDetections({ limit: 5000 }).catch(() => [] as DetectionRow[]),
        fetchTopResonance(100).catch(() => [] as ResonanceRow[]),
        fbFetchPipelineCounts().catch(() => null),
      ])
      setDetections(d)
      setResonance(r)
      setCounts(c)
      saveCache({ savedAt: Date.now(), detections: d, resonance: r, counts: c })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { void refreshData() }, [refreshData])

  // Detection workers keep writing after the scrape publisher finishes.
  // Poll refreshData every 25s only when the backend is actively working:
  // scan running OR finished within the last 3 minutes.
  const [scanActive, setScanActive] = useState(false)
  useEffect(() => {
    const unsub = fbSubscribeScanState((s) => {
      const started = s?.startedAt ? new Date(s.startedAt).getTime() : 0
      const finished = s?.finishedAt ? new Date(s.finishedAt).getTime() : 0
      const running = !!started && !finished
      const recentlyDone = !!finished && (Date.now() - finished) < 3 * 60_000
      setScanActive(running || recentlyDone)
    })
    return () => unsub()
  }, [])
  useEffect(() => {
    if (!scanActive) return
    const id = window.setInterval(() => { void refreshData() }, 25_000)
    return () => window.clearInterval(id)
  }, [scanActive, refreshData])

  const days = DAYS_WINDOW
  // Collapse frame-level AND carousel-slot detections into one row per real
  // POST (see lib/types.dedupeByPost — verdicts merge across the group).
  const uniqueDetections = useMemo(() => dedupeByPost(detections), [detections])
  // Rejected content is excluded from Dashboard, Creators, and default views.
  // The Feed keeps access to it via the "Flagged FP" trust filter.
  const activeRows = useMemo(
    () => uniqueDetections.filter((d) => d.is_false_positive !== true),
    [uniqueDetections],
  )

  // Dashboard shows every non-rejected post-hit — age of the underlying
  // post shouldn't hide a real hit, but moderator-rejected content is out.
  const rangeRows = activeRows

  // Tab badge counts — all post-level (deduped), rejected excluded.
  const newSince = useMemo(() => countNewSince(activeRows, lastSeenAt), [activeRows, lastSeenAt])
  const reviewCount = useMemo(
    () => activeRows.filter((d) => d.detected === true && d.verified !== true).length,
    [activeRows],
  )
  const creatorCount = useMemo(
    () => new Set(activeRows.filter((d) => d.detected === true && d.creator_handle).map((d) => d.creator_handle)).size,
    [activeRows],
  )

  const tabItems = useMemo(() => [
    { id: 'briefing', label: 'Dashboard', count: newSince > 0 ? newSince : undefined },
    { id: 'feed', label: 'Feed', count: rangeRows.length },
    { id: 'review', label: 'Review', count: reviewCount > 0 ? reviewCount : undefined },
    { id: 'creators', label: 'Creators', count: creatorCount },
  ], [newSince, rangeRows.length, reviewCount, creatorCount])

  return (
    <PageShell
      title="The Stëlz Community"
      subtitle="Live brand tracker"
      actions={
        <div className="flex items-center gap-3">
          {refreshing && hasCache && <RefreshingTag />}
          <RunScanButton onComplete={refreshData} liveHits={activeRows.filter((d) => d.detected === true).length} />
        </div>
      }
    >
      {loading && <SkeletonHome />}
      {error && <Card className="p-10 text-center text-[13px] text-[var(--color-bad)]">{error}</Card>}

      {!loading && !error && (
        <>
          <Tabs items={tabItems} active={tab} onChange={(id) => setTab(id as Tab)} />

          <div className="mt-8">
            {tab === 'briefing' && (
              <BriefingTab
                detections={uniqueDetections}
                rangeRows={rangeRows}
                resonance={resonance}
                counts={counts}
                lastSeenAt={lastSeenAt}
                days={days}
                onOpen={setActiveDetection}
                onGotoTab={setTab}
              />
            )}
            {tab === 'feed' && (
              <FeedTab rows={uniqueDetections} lastSeenAt={lastSeenAt} onOpen={setActiveDetection} />
            )}
            {tab === 'review' && (
              <ReviewTab detections={activeRows} allDetections={detections} />
            )}
            {tab === 'creators' && (
              <CreatorsTab detections={activeRows} />
            )}
          </div>
        </>
      )}

      <DetectionDrawer
        detection={activeDetection}
        similar={activeDetection ? uniqueDetections.filter((d) => d.creator_handle === activeDetection.creator_handle && d.detection_id !== activeDetection.detection_id) : []}
        frames={activeDetection ? detections
          .filter((d) => d.detected === true && parentPostKey(d) === parentPostKey(activeDetection))
          .sort((a, b) => (a.frame_idx ?? 0) - (b.frame_idx ?? 0)) : []}
        onClose={() => setActiveDetection(null)}
      />
    </PageShell>
  )
}

// ─────────────────────── BRIEFING ───────────────────────

function BriefingTab({
  detections, rangeRows, counts, days, onOpen, onGotoTab,
}: {
  detections: DetectionRow[]
  rangeRows: DetectionRow[]
  resonance: ResonanceRow[]
  counts: PipelineCounts | null
  lastSeenAt: string | null
  days: number
  onOpen: (d: DetectionRow) => void
  onGotoTab: (t: Tab) => void
}) {
  const worthLook = useMemo(() => pickWorthALook(detections, 6), [detections])
  const biggestFan = useMemo(() => biggestFanToday(detections), [detections])
  const spike = useMemo(() => detectSpike(detections), [detections])

  if (detections.length === 0) {
    return <EmptyBriefing counts={counts} />
  }

  return (
    <div className="space-y-8">
      <DashboardSection detections={detections} rangeRows={rangeRows} days={days} />

      <section>
        <header className="flex items-end justify-between mb-4">
          <div>
            <h2 className="text-[18px] font-medium tracking-tight">Worth a look</h2>
            <p className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">
              Picked by score: tier + visibility + confidence + novelty.
            </p>
          </div>
          <button onClick={() => onGotoTab('feed')} className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]">All detections →</button>
        </header>
        {worthLook.length === 0 ? (
          <Card className="p-10 text-center text-[13px] text-[var(--color-ink-muted)]">No standout detections yet.</Card>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
            {worthLook.map((d) => (
              <PickCard key={d.detection_id} d={d} onOpen={() => onOpen(d)} />
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {biggestFan && (
          <section>
            <header className="mb-4">
              <h2 className="text-[18px] font-medium tracking-tight">Today's biggest fan</h2>
              <p className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">Most hits in the last 24 hours.</p>
            </header>
            <Card className="overflow-hidden">
              <div className="grid grid-cols-[120px_1fr]">
                <div className="aspect-square border-r border-[var(--color-border)]">
                  <Img src={biggestFan.topDetection ? imageUrlFor(biggestFan.topDetection) : null} />
                </div>
                <div className="p-5">
                  <div className="flex items-center gap-2 mb-2">
                    <Link to={`/creators/${biggestFan.handle}`} className="text-[18px] font-medium hover:underline">@{biggestFan.handle}</Link>
                    {biggestFan.tier === 'tier_1' && <Badge tone="accent">tier 1</Badge>}
                  </div>
                  <div className="text-[13px] text-[var(--color-ink-muted)] mb-3 tabular-nums">
                    {biggestFan.hits} hit{biggestFan.hits === 1 ? '' : 's'} in the last 24h
                  </div>
                  <div className="mb-4">
                    <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-1.5">14-day trend</div>
                    <Sparkline data={biggestFan.spark} height={28} tone="accent" />
                  </div>
                  <Link to={`/creators/${biggestFan.handle}`}><Button size="sm">View profile →</Button></Link>
                </div>
              </div>
            </Card>
          </section>
        )}

        <section>
          <header className="mb-4">
            <h2 className="text-[18px] font-medium tracking-tight">Spike detection</h2>
            <p className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">Hashtags trending vs prior week.</p>
          </header>
          {spike ? (
            <Card className="p-5 border-l-2 border-l-[var(--color-accent)]">
              <div className="flex items-start gap-3 mb-3">
                <div className="text-[var(--color-accent)] text-[18px] leading-none">⚡</div>
                <div className="flex-1">
                  <div className="text-[15px] font-medium">#{spike.tag}</div>
                  <div className="text-[12px] text-[var(--color-ink-muted)] mt-0.5 tabular-nums">
                    {spike.now} creators this week · {spike.prev} prior week
                  </div>
                </div>
                <Badge tone="accent">+{Math.round(spike.pctDelta)}%</Badge>
              </div>
              <Button size="sm" variant="primary" onClick={() => onGotoTab('feed')}>Explore in feed →</Button>
            </Card>
          ) : (
            <Card className="p-5">
              <div className="text-[13px] text-[var(--color-ink-muted)]">No significant spikes this week.</div>
              <div className="text-[11px] text-[var(--color-ink-subtle)] mt-1">Need ≥80% jump and ≥3 unique creators.</div>
            </Card>
          )}
        </section>
      </div>

    </div>
  )
}

function EmptyBriefing({ counts }: { counts: PipelineCounts | null }) {
  const hasAny = counts && (counts.creators > 0 || counts.posts > 0 || counts.discoveryQueue > 0)
  if (hasAny) {
    return (
      <Card className="p-10 text-center max-w-xl mx-auto">
        <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Pipeline warming up</div>
        <h2 className="text-[20px] font-medium tracking-tight mb-3">Analysing what we found.</h2>
        <p className="text-[14px] text-[var(--color-ink-muted)] leading-relaxed mb-2">
          We scraped {counts!.posts} posts from {counts!.creators} creators.
          Detection runs in the background.
        </p>
        <p className="text-[13px] text-[var(--color-ink-muted)]">
          First hits appear here within minutes.
        </p>
      </Card>
    )
  }
  return (
    <Card className="p-10 lg:p-14 text-center max-w-xl mx-auto">
      <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Welcome</div>
      <h2 className="text-[22px] font-medium tracking-tight mb-3">Let's find your brand in the wild.</h2>
      <p className="text-[14px] text-[var(--color-ink-muted)] leading-relaxed mb-6">
        Run your first scan — we'll crawl Instagram and TikTok for posts featuring your products.
      </p>
      <div className="flex justify-center"><RunScanButton onComplete={() => window.location.reload()} /></div>
    </Card>
  )
}

// ─────────────────────── FEED ───────────────────────

function FeedTab({ rows, lastSeenAt, onOpen }: { rows: DetectionRow[]; lastSeenAt: string | null; onOpen: (d: DetectionRow) => void }) {
  const [search, setSearch] = useState('')
  const [productFilter, setProductFilter] = useState<string | null>(null)
  const [tierFilter, setTierFilter] = useState<string | null>(null)
  const [trustFilter, setTrustFilter] = useState<'verified' | 'unreviewed' | 'fp' | null>('verified')
  const [platformFilter, setPlatformFilter] = useState<'instagram' | 'tiktok' | null>(null)
  const [typeFilter, setTypeFilter] = useState<'video' | 'image' | null>(null)
  // High-confidence-only default. Low-quality Gemini hits polluted the feed;
  // user can drop the threshold via the "Confidence" filter below.
  const [minConfidence, setMinConfidence] = useState<number>(0.85)
  // Progressive rendering — everything matching is reachable via "Show more".
  const [visibleCount, setVisibleCount] = useState(60)

  const filtered = useMemo(() => {
    return rows.filter((d) => {
      if (productFilter && d.product_line !== productFilter) return false
      if (tierFilter && d.creator_tier !== tierFilter) return false
      if (trustFilter === 'verified' && d.is_false_positive === true) return false
      if (trustFilter === 'unreviewed' && (d.verified === true || d.is_false_positive === true)) return false
      if (trustFilter === 'fp' && d.is_false_positive !== true) return false
      if (platformFilter && d.platform !== platformFilter) return false
      if (typeFilter === 'video' && d.frame_idx == null) return false
      if (typeFilter === 'image' && d.frame_idx != null) return false
      if ((d.confidence ?? 0) < minConfidence) return false
      if (search) {
        const q = search.toLowerCase()
        if (!`${d.creator_handle ?? ''} ${d.post_caption ?? ''} ${d.context ?? ''}`.toLowerCase().includes(q)) return false
      }
      return true
    })
  }, [rows, search, productFilter, tierFilter, trustFilter, platformFilter, typeFilter, minConfidence])

  // Reset pagination when any filter narrows/changes the result set.
  useEffect(() => { setVisibleCount(60) }, [search, productFilter, tierFilter, trustFilter, platformFilter, typeFilter, minConfidence])

  const productLines = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows) if (r.product_line) m.set(r.product_line, (m.get(r.product_line) ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [rows])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex-1 min-w-[200px] max-w-md">
          <Input placeholder="Search creator, caption, context…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <FilterDropdown label="Platform" value={platformFilter} onChange={(v) => setPlatformFilter(v as 'instagram' | 'tiktok' | null)} options={[
          { id: 'instagram' as const, label: 'Instagram', count: rows.filter((r) => r.platform === 'instagram').length },
          { id: 'tiktok' as const, label: 'TikTok', count: rows.filter((r) => r.platform === 'tiktok').length },
        ]} />
        <FilterDropdown label="Type" value={typeFilter} onChange={(v) => setTypeFilter(v as 'video' | 'image' | null)} options={[
          { id: 'video' as const, label: 'Video', count: rows.filter((r) => r.frame_idx != null).length },
          { id: 'image' as const, label: 'Image', count: rows.filter((r) => r.frame_idx == null).length },
        ]} />
        <FilterDropdown label="Product" value={productFilter} onChange={(v) => setProductFilter(v as string | null)} options={productLines.map(([k, n]) => ({ id: k, label: PRODUCT_LINE_LABEL[k] ?? k, count: n }))} />
        <FilterDropdown label="Tier" value={tierFilter} onChange={(v) => setTierFilter(v as string | null)} options={['tier_1', 'tier_2', 'tier_3'].map((t, i) => ({ id: t, label: `Tier ${i + 1}`, count: rows.filter((r) => r.creator_tier === t).length }))} />
        <FilterDropdown label="Trust" value={trustFilter} onChange={(v) => setTrustFilter(v as 'verified' | 'unreviewed' | 'fp' | null)} options={[
          { id: 'verified' as const, label: 'Verified + auto', count: rows.filter((r) => r.is_false_positive !== true).length },
          { id: 'unreviewed' as const, label: 'Unreviewed only', count: rows.filter((r) => r.verified !== true && r.is_false_positive !== true).length },
          { id: 'fp' as const, label: 'Flagged FP', count: rows.filter((r) => r.is_false_positive === true).length },
        ]} />
        <FilterDropdown label="Confidence" value={minConfidence} onChange={(v) => setMinConfidence((v as number | null) ?? 0)} options={[
          { id: 0.85, label: '≥ 85% (strict)', count: rows.filter((r) => (r.confidence ?? 0) >= 0.85).length },
          { id: 0.75, label: '≥ 75%', count: rows.filter((r) => (r.confidence ?? 0) >= 0.75).length },
          { id: 0.5, label: '≥ 50%', count: rows.filter((r) => (r.confidence ?? 0) >= 0.5).length },
          { id: 0, label: 'All', count: rows.length },
        ]} />
        {(productFilter || tierFilter || search || platformFilter || typeFilter || trustFilter !== 'verified' || minConfidence !== 0.85) && (
          <button onClick={() => { setProductFilter(null); setTierFilter(null); setSearch(''); setTrustFilter('verified'); setPlatformFilter(null); setTypeFilter(null); setMinConfidence(0.85) }} className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] underline">Reset</button>
        )}
        <span className="ml-auto text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
          {filtered.length.toLocaleString()} of {rows.length.toLocaleString()}
        </span>
      </div>

      {filtered.length === 0 ? (
        <Card className="px-6 py-16 text-center text-[13px] text-[var(--color-ink-subtle)]">No detections match.</Card>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filtered.slice(0, visibleCount).map((d) => (
              <FeedCard
                key={d.detection_id}
                d={d}
                isNew={!!(lastSeenAt && d.posted_at && d.posted_at > lastSeenAt)}
                onOpen={() => onOpen(d)}
              />
            ))}
          </div>
          {filtered.length > visibleCount && (
            <div className="flex flex-col items-center gap-2 pt-2">
              <button
                onClick={() => setVisibleCount((c) => c + 60)}
                className="rounded-full border border-[var(--color-ink)] px-6 py-2 text-[12px] font-medium uppercase tracking-wide text-[var(--color-ink)] hover:bg-[var(--color-ink)] hover:text-white transition-colors"
              >
                Show more
              </button>
              <span className="text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
                Showing {Math.min(visibleCount, filtered.length)} of {filtered.length.toLocaleString()}
              </span>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function FeedCard({ d, isNew, onOpen }: { d: DetectionRow; isNew: boolean; onOpen: () => void }) {
  const tags = (d.post_hashtags ?? []).slice(0, 4)
  const extraTags = (d.post_hashtags?.length ?? 0) - tags.length
  const conf = (d.confidence ?? 0) * 100
  return (
    <button
      onClick={onOpen}
      className="text-left bg-[var(--color-surface)] border border-[var(--color-border)] hover:border-[var(--color-border-strong)] transition-colors flex flex-col group"
    >
      {/* Media */}
      <div className="relative aspect-[4/5] bg-[var(--color-bg)] overflow-hidden">
        <Img src={imageUrlFor(d)} />
        {isNew && (
          <span className="absolute top-2 left-2 text-[10px] uppercase tracking-widest bg-[var(--color-accent)] text-white px-2 py-0.5">
            New
          </span>
        )}
        <span className="absolute top-2 right-2 text-[10px] uppercase tracking-widest bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
          {d.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
        </span>
        {d.frame_idx != null && (
          <span className="absolute bottom-2 right-2 text-[10px] bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
            ▶ video{(d.frame_hits ?? 0) > 1 ? ` · ${d.frame_hits} frames` : ''}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="p-3.5 flex flex-col gap-2.5 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[13px] font-medium truncate">@{d.creator_handle}</span>
          {d.creator_tier === 'tier_1' && <Badge tone="accent">T1</Badge>}
          {d.verified === true && <Badge tone="good">✓</Badge>}
          {d.is_false_positive === true && <Badge tone="bad">FP</Badge>}
          <span className={`ml-auto text-[12px] tabular-nums font-medium shrink-0 ${conf >= 85 ? 'text-[var(--color-good)]' : conf >= 75 ? 'text-[var(--color-warn)]' : 'text-[var(--color-bad)]'}`}>
            {conf.toFixed(0)}%
          </span>
        </div>

        {d.product_line && (
          <div className="text-[11px] text-[var(--color-ink-muted)]">
            {PRODUCT_LINE_LABEL[d.product_line] ?? d.product_line}
            {d.surface_type ? ` · on ${d.surface_type.replace(/_/g, ' ')}` : ''}
          </div>
        )}

        {(d.post_caption || d.context) && (
          <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed line-clamp-2">
            {d.post_caption ?? d.context}
          </p>
        )}

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <span key={t} className="text-[10px] px-1.5 py-0.5 border border-[var(--color-border)] text-[var(--color-ink-muted)] bg-[var(--color-bg)]">
                #{t}
              </span>
            ))}
            {extraTags > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 text-[var(--color-ink-subtle)]">+{extraTags}</span>
            )}
          </div>
        )}

        <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)] tabular-nums mt-auto pt-1">
          <span className="flex items-center gap-2.5">
            {(d.likes_count ?? 0) > 0 && <span>♥ {compactNum(d.likes_count!)}</span>}
            {(d.views_count ?? 0) > 0 && <span>▶ {compactNum(d.views_count!)}</span>}
            {d.music?.title && <span className="truncate max-w-[110px]">♫ {d.music.title}</span>}
          </span>
          <span className="shrink-0">{d.posted_at ? timeAgo(d.posted_at) : '—'}</span>
        </div>
      </div>
    </button>
  )
}

function compactNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

// ─────────────────────── REVIEW (approve / reject queue) ───────────────────────

function ReviewTab({ detections, allDetections }: { detections: DetectionRow[]; allDetections: DetectionRow[] }) {
  // Local queue: unreviewed hits (post-level). `handled` tracks in-session
  // decisions keyed by PARENT POST so the card advances instantly and a
  // decision covers every frame/slot doc of that post.
  const [handled, setHandled] = useState<Record<string, 'confirmed' | 'rejected'>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const queue = useMemo(
    () => detections.filter(
      (d) => d.detected === true && d.verified !== true && d.is_false_positive !== true && !handled[parentPostKey(d)],
    ),
    [detections, handled],
  )
  const current = queue[0] ?? null
  const doneCount = Object.keys(handled).length

  const rate = useCallback(async (verdict: 'confirmed' | 'rejected') => {
    if (!current || busy) return
    setBusy(true); setError(null)
    const key = parentPostKey(current)
    // A post can have many detection docs (video frames, carousel slots).
    // Rate ALL of them — otherwise an unrated sibling resurrects the post
    // in the queue after the next refetch.
    const siblingIds = allDetections
      .filter((d) => parentPostKey(d) === key)
      .map((d) => d.detection_id)
    const ids = siblingIds.length > 0 ? siblingIds : [current.detection_id]
    // Optimistic: advance immediately; revert on failure.
    setHandled((h) => ({ ...h, [key]: verdict }))
    try {
      await Promise.all(ids.map((id) => rateDetection(id, verdict)))
    } catch (e) {
      setHandled((h) => { const c = { ...h }; delete c[key]; return c })
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [current, busy, allDetections])

  // Keyboard: ← reject, → approve
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') void rate('confirmed')
      if (e.key === 'ArrowLeft') void rate('rejected')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rate])

  if (!current) {
    return (
      <Card className="p-14 text-center max-w-lg mx-auto">
        <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-ink-subtle)] mb-3">Review queue</div>
        <h2 className="stelz-display text-[24px] mb-2 text-[var(--color-ink)]">All clear</h2>
        <p className="text-[13px] text-[var(--color-ink-muted)]">
          {doneCount > 0 ? `You reviewed ${doneCount} detection${doneCount === 1 ? '' : 's'} this session. ` : ''}
          Nothing waiting for review.
        </p>
      </Card>
    )
  }

  const conf = (current.confidence ?? 0) * 100
  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between text-[12px] text-[var(--color-ink-muted)]">
        <span className="tabular-nums">{queue.length} waiting · {doneCount} done this session</span>
        <span className="hidden sm:inline text-[var(--color-ink-subtle)]">← reject · approve →</span>
      </div>

      {error && (
        <div className="border border-[var(--color-bad)] text-[12px] text-[var(--color-bad)] px-3 py-2">{error}</div>
      )}

      <Card className="overflow-hidden">
        {/* Media */}
        <div className="relative bg-[var(--color-bg)]">
          <div className="aspect-[4/3]">
            <Img src={imageUrlFor(current)} fit="contain" />
          </div>
          <span className="absolute top-3 right-3 text-[10px] uppercase tracking-widest bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
            {current.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
          </span>
          {current.frame_idx != null && (
            <span className="absolute bottom-3 right-3 text-[10px] bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
              ▶ video frame {current.frame_idx}
            </span>
          )}
        </div>

        {/* Facts */}
        <div className="p-5 space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/creators/${current.creator_handle}`} className="text-[15px] font-medium hover:underline">
              @{current.creator_handle}
            </Link>
            {current.creator_tier === 'tier_1' && <Badge tone="accent">T1</Badge>}
            {current.product_line && <Badge tone="muted">{PRODUCT_LINE_LABEL[current.product_line] ?? current.product_line}</Badge>}
            <span className={`ml-auto text-[14px] tabular-nums font-medium ${conf >= 85 ? 'text-[var(--color-good)]' : conf >= 75 ? 'text-[var(--color-warn)]' : 'text-[var(--color-bad)]'}`}>
              {conf.toFixed(0)}%
            </span>
          </div>

          {(current.visible_text || current.surface_type || current.context) && (
            <div className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed space-y-1">
              {current.visible_text && <div><span className="text-[var(--color-ink-subtle)]">Text read:</span> "{current.visible_text}"</div>}
              {current.surface_type && <div><span className="text-[var(--color-ink-subtle)]">Surface:</span> {current.surface_type.replace(/_/g, ' ')}</div>}
              {current.context && <div><span className="text-[var(--color-ink-subtle)]">AI notes:</span> {current.context}</div>}
            </div>
          )}

          {current.post_caption && (
            <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed line-clamp-2 border-t border-[var(--color-border)] pt-3">
              "{current.post_caption}"
            </p>
          )}

          {current.post_url && (
            <a href={current.post_url} target="_blank" rel="noreferrer" className="inline-block text-[12px] text-[var(--color-ink-muted)] underline hover:text-[var(--color-ink)]">
              Open original post ↗
            </a>
          )}
        </div>

        {/* Verdict buttons */}
        <div className="grid grid-cols-2 border-t border-[var(--color-border)]">
          <button
            onClick={() => void rate('rejected')}
            disabled={busy}
            className="py-4 text-[13px] font-medium uppercase tracking-wide text-[var(--color-bad)] hover:bg-[var(--color-bad)] hover:text-white transition-colors border-r border-[var(--color-border)] disabled:opacity-50"
          >
            ✗ Not Stëlz
          </button>
          <button
            onClick={() => void rate('confirmed')}
            disabled={busy}
            className="py-4 text-[13px] font-medium uppercase tracking-wide text-[var(--color-good)] hover:bg-[var(--color-good)] hover:text-white transition-colors disabled:opacity-50"
          >
            ✓ Confirm
          </button>
        </div>
      </Card>

      {/* Next up preview strip */}
      {queue.length > 1 && (
        <div className="flex gap-1.5">
          {queue.slice(1, 9).map((d) => (
            <div key={d.detection_id} className="w-12 h-12 border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5">
              <Img src={imageUrlFor(d)} />
            </div>
          ))}
          {queue.length > 9 && (
            <div className="w-12 h-12 border border-[var(--color-border)] flex items-center justify-center text-[10px] text-[var(--color-ink-subtle)] tabular-nums">
              +{queue.length - 9}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────── CREATORS ───────────────────────

function CreatorsTab({ detections }: { detections: DetectionRow[] }) {
  const [search, setSearch] = useState('')
  const [platformFilter, setPlatformFilter] = useState<string | null>(null)
  const [sort, setSort] = useState<'hits' | 'followers' | 'recent'>('hits')

  // Built purely from actual detections — no separate scoring table.
  const rows = useMemo(() => {
    type Row = {
      handle: string
      platform: string
      hits: number
      followers: number | null
      totalLikes: number
      totalViews: number
      avatar: string | null
      lastSeen: string | null
      topProduct: string | null
      recent: DetectionRow[]
      spark: { d: string; n: number }[]
    }
    const m = new Map<string, Row>()
    for (const d of detections) {
      if (!d.creator_handle || d.detected !== true) continue
      const cur = m.get(d.creator_handle) ?? {
        handle: d.creator_handle,
        platform: d.platform,
        hits: 0,
        followers: d.follower_count,
        totalLikes: 0,
        totalViews: 0,
        avatar: null,
        lastSeen: null,
        topProduct: null,
        recent: [],
        spark: [],
      }
      cur.hits++
      cur.totalLikes += d.likes_count ?? 0
      cur.totalViews += d.views_count ?? 0
      if ((d.follower_count ?? 0) > (cur.followers ?? 0)) cur.followers = d.follower_count
      if (!cur.avatar && d.extras?.author?.avatar) cur.avatar = d.extras.author.avatar
      if (!cur.lastSeen || (d.posted_at ?? '') > cur.lastSeen) cur.lastSeen = d.posted_at
      if (cur.recent.length < 4) cur.recent.push(d)
      m.set(d.creator_handle, cur)
    }
    for (const row of m.values()) {
      const products = new Map<string, number>()
      for (const d of row.recent) if (d.product_line) products.set(d.product_line, (products.get(d.product_line) ?? 0) + 1)
      row.topProduct = [...products.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
      row.spark = bucketByDay(detections.filter((d) => d.creator_handle === row.handle && d.detected).map((d) => d.posted_at), 14)
    }
    let out = [...m.values()]
    if (search) out = out.filter((r) => r.handle.toLowerCase().includes(search.toLowerCase()))
    if (platformFilter) out = out.filter((r) => r.platform === platformFilter)
    out.sort((a, b) => {
      if (sort === 'hits') return b.hits - a.hits
      if (sort === 'followers') return (b.followers ?? 0) - (a.followers ?? 0)
      return (b.lastSeen ?? '').localeCompare(a.lastSeen ?? '')
    })
    return out
  }, [detections, search, platformFilter, sort])

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex-1 min-w-[200px] max-w-md">
          <Input placeholder="Search by handle…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="inline-flex gap-1.5">
          {(['instagram', 'tiktok'] as const).map((p) => (
            <button key={p} onClick={() => setPlatformFilter(platformFilter === p ? null : p)} className={`rounded-full border px-3.5 py-1.5 text-[12px] transition-colors ${platformFilter === p ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white' : 'border-[var(--color-ink)] text-[var(--color-ink)] hover:bg-[var(--color-ink)] hover:text-white'}`}>
              {p === 'tiktok' ? 'TikTok' : 'Instagram'}
            </button>
          ))}
        </div>
        <div className="inline-flex gap-1.5">
          {(['hits', 'followers', 'recent'] as const).map((s) => (
            <button key={s} onClick={() => setSort(s)} className={`rounded-full border px-3.5 py-1.5 text-[12px] capitalize transition-colors ${sort === s ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white' : 'border-[var(--color-border-strong)] text-[var(--color-ink-muted)] hover:border-[var(--color-ink)] hover:text-[var(--color-ink)]'}`}>
              {s}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-[var(--color-ink-subtle)] tabular-nums">{rows.length} creators</span>
      </div>

      {rows.length === 0 ? (
        <Card className="px-6 py-16 text-center text-[13px] text-[var(--color-ink-subtle)]">No creators with confirmed hits yet.</Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {rows.slice(0, 60).map((r) => (
            <Link
              key={r.handle}
              to={`/creators/${r.handle}`}
              className="bg-[var(--color-surface)] border border-[var(--color-border)] hover:border-[var(--color-border-strong)] transition-colors p-4 flex flex-col gap-3"
            >
              {/* Identity row */}
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-full overflow-hidden border border-[var(--color-border)] bg-[var(--color-bg)] shrink-0">
                  <Img src={r.avatar || (r.recent[0] ? imageUrlFor(r.recent[0]) : null)} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium truncate">@{r.handle}</div>
                  <div className="text-[11px] text-[var(--color-ink-subtle)]">
                    {r.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
                    {r.followers ? ` · ${compactNum(r.followers)} followers` : ''}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[18px] font-medium tabular-nums leading-none">{r.hits}</div>
                  <div className="text-[10px] text-[var(--color-ink-subtle)] uppercase tracking-wider mt-0.5">hits</div>
                </div>
              </div>

              {/* Recent content strip */}
              <div className="grid grid-cols-4 gap-1">
                {r.recent.map((d) => (
                  <div key={d.detection_id} className="relative aspect-square bg-[var(--color-bg)] border border-[var(--color-border)] overflow-hidden">
                    <Img src={imageUrlFor(d)} />
                    {d.frame_idx != null && (
                      <span className="absolute bottom-0.5 right-0.5 text-[8px] bg-[var(--color-ink)]/80 text-white px-1">▶</span>
                    )}
                  </div>
                ))}
                {Array.from({ length: Math.max(0, 4 - r.recent.length) }).map((_, i) => (
                  <div key={`e${i}`} className="aspect-square bg-[var(--color-bg)] border border-[var(--color-border)]" />
                ))}
              </div>

              {/* Meta row */}
              <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
                <span className="flex items-center gap-2.5">
                  {r.totalLikes > 0 && <span>♥ {compactNum(r.totalLikes)}</span>}
                  {r.totalViews > 0 && <span>▶ {compactNum(r.totalViews)}</span>}
                  {r.topProduct && <span className="truncate max-w-[120px]">{PRODUCT_LINE_LABEL[r.topProduct] ?? r.topProduct}</span>}
                </span>
                <span>{r.lastSeen ? timeAgo(r.lastSeen) : ''}</span>
              </div>

              <div className="h-6"><Sparkline data={r.spark} height={22} tone="accent" /></div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}


// ─────────────────────── DEBUG ───────────────────────



// ─────────────────────── Dashboard ───────────────────────

function DashboardSection({ detections, rangeRows, days }: { detections: DetectionRow[]; rangeRows: DetectionRow[]; days: number }) {
  // ── Top-row KPIs ────────────────────────────────────────────────
  const totalHits = rangeRows.filter((d) => d.detected === true).length
  const week = new Date(); week.setDate(week.getDate() - 7)
  const weekIso = week.toISOString()
  const thisWeekHits = rangeRows.filter((d) => d.detected && (d.posted_at ?? '') >= weekIso).length
  const activeCreators = new Set(rangeRows.filter((d) => d.detected).map((d) => d.creator_handle)).size
  const igHits = rangeRows.filter((d) => d.detected && d.platform === 'instagram').length
  const ttHits = rangeRows.filter((d) => d.detected && d.platform === 'tiktok').length
  const topPlatform = igHits >= ttHits ? 'Instagram' : 'TikTok'
  const videoHits = rangeRows.filter((d) => d.detected && d.frame_idx != null).length
  const avgConf = totalHits
    ? Math.round((rangeRows.filter((d) => d.detected).reduce((s, d) => s + (d.confidence ?? 0), 0) / totalHits) * 100)
    : 0

  // ── 1. Detections per day, split by platform ────────────────────
  const igSeries: Series = {
    id: 'ig', label: 'Instagram', tone: 'ink',
    data: bucketByDay(rangeRows.filter((d) => d.detected && d.platform === 'instagram').map((d) => d.posted_at), days),
  }
  const ttSeries: Series = {
    id: 'tt', label: 'TikTok', tone: 'accent',
    data: bucketByDay(rangeRows.filter((d) => d.detected && d.platform === 'tiktok').map((d) => d.posted_at), days),
  }

  // ── 2. New creators per day (first-seen) ────────────────────────
  const firstSeen = new Map<string, string>()
  for (const d of detections) {
    if (!d.detected || !d.posted_at) continue
    const cur = firstSeen.get(d.creator_handle)
    if (!cur || d.posted_at < cur) firstSeen.set(d.creator_handle, d.posted_at)
  }
  const newCreatorsSeries: Series = {
    id: 'newc', label: 'New creators', tone: 'good',
    data: bucketByDay([...firstSeen.values()], days),
  }

  // ── 3. Creator leaderboard (hits + growth + identity in one) ─────
  const halfMs = (days * 24 * 60 * 60 * 1000) / 2
  const cutoff = Date.now() - halfMs
  const perCreator = new Map<string, {
    recent: number; prior: number; total: number
    avatar: string | null; platform: string; firstImage: string | null
  }>()
  for (const d of rangeRows) {
    if (!d.detected) continue
    const ts = d.posted_at ? new Date(d.posted_at).getTime() : 0
    const e = perCreator.get(d.creator_handle) ?? {
      recent: 0, prior: 0, total: 0,
      avatar: null, platform: d.platform, firstImage: null,
    }
    if (ts >= cutoff) e.recent += 1; else e.prior += 1
    e.total += 1
    if (!e.avatar && d.extras?.author?.avatar) e.avatar = d.extras.author.avatar
    if (!e.firstImage) e.firstImage = imageUrlFor(d) || null
    perCreator.set(d.creator_handle, e)
  }

  // ── 4. Top hashtags by yield (hits per hashtag) ─────────────────
  const tagYield = new Map<string, number>()
  for (const d of rangeRows) {
    if (!d.detected) continue
    for (const t of (d.post_hashtags ?? [])) {
      const k = t.toLowerCase().replace(/^#/, '')
      if (!k) continue
      tagYield.set(k, (tagYield.get(k) ?? 0) + 1)
    }
  }
  const topTags = [...tagYield.entries()]
    .map(([label, value]) => ({ label: `#${label}`, value, tone: 'accent' as const }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8)

  // ── 5. Product line breakdown — Stelz flavor colours ─────────────
  // Matches the can designs on drinkstelz.com: lemonade orange, seltzer red,
  // iced tea green, classics gold, 0.0 light blue, logo-only navy.
  const PRODUCT_COLOR: Record<string, string> = {
    hard_lemonade: '#f59023',
    hard_seltzer: '#e8402f',
    hard_iced_tea: '#6f9f3c',
    mixed_classics: '#e0a92c',
    zero_zero: '#6b8fd6',
    logo_only: '#222c51',
  }
  const productMix = new Map<string, number>()
  for (const d of rangeRows.filter((x) => x.detected)) {
    const p = d.product_line || 'unspecified'
    productMix.set(p, (productMix.get(p) ?? 0) + 1)
  }
  const productSlices = [...productMix.entries()].map(([label, value], i) => ({
    label: PRODUCT_LINE_LABEL[label] ?? label,
    value,
    color: PRODUCT_COLOR[label] ?? ['#222c51', '#e8402f', '#f59023', '#6f9f3c'][i % 4],
  }))

  // ── 6. Platform comparison ──────────────────────────────────────
  const platformSlices = [
    { label: 'Instagram', value: igHits, color: '#222c51' },
    { label: 'TikTok', value: ttHits, color: '#e8402f' },
  ]

  // ── 8. Top creators leaderboard (most hits + growth) ────────────
  const leaderboard = [...perCreator.entries()]
    .map(([handle, e]) => ({
      handle,
      hits: e.total,
      recent: e.recent,
      avatar: e.avatar,
      firstImage: e.firstImage,
      platform: e.platform,
      growth: e.prior === 0 ? (e.recent > 0 ? 100 : 0) : ((e.recent - e.prior) / Math.max(1, e.prior)) * 100,
    }))
    .sort((a, b) => b.hits - a.hits)
    .slice(0, 8)
  const maxLeaderHits = leaderboard[0]?.hits ?? 1

  // ── 9. Posting day-of-week heatmap (when do hits happen) ────────
  const dayOfWeek = [0, 0, 0, 0, 0, 0, 0]
  for (const d of rangeRows.filter((x) => x.detected && x.posted_at)) {
    const dow = new Date(d.posted_at!).getDay()
    dayOfWeek[(dow + 6) % 7] += 1  // Mon-first
  }
  const dowRows = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo'].map((l, i) => ({
    label: l, value: dayOfWeek[i],
    tone: (i >= 5 ? 'accent' : 'ink') as Series['tone'],
  }))

  // ── Top sounds (TikTok music) ────────────────────────────────────
  const soundCounts = new Map<string, { label: string; url: string | null; count: number; original: boolean; artist: string | null }>()
  for (const d of rangeRows.filter((x) => x.detected && x.music)) {
    const m = d.music!
    const key = m.musicId || `${m.title || ''}|${m.artist || ''}`
    if (!key.trim()) continue
    const cur = soundCounts.get(key) ?? {
      label: m.title || '(untitled)',
      url: m.url || null,
      count: 0,
      original: !!m.original,
      artist: m.artist || null,
    }
    cur.count += 1
    soundCounts.set(key, cur)
  }
  const topSounds = [...soundCounts.values()]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)

  // ── Top effects (TikTok stickers/effects) ────────────────────────
  const effectCounts = new Map<string, number>()
  for (const d of rangeRows.filter((x) => x.detected)) {
    for (const e of (d.extras?.effects ?? [])) {
      if (!e) continue
      effectCounts.set(e, (effectCounts.get(e) ?? 0) + 1)
    }
  }
  const topEffects = [...effectCounts.entries()]
    .map(([label, value]) => ({ label, value, tone: 'good' as const }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6)

  // ── Top mentions (who's tagging the brand) ───────────────────────
  const mentionCounts = new Map<string, number>()
  for (const d of rangeRows.filter((x) => x.detected)) {
    for (const m of (d.post_mentions ?? [])) {
      if (!m) continue
      mentionCounts.set(m, (mentionCounts.get(m) ?? 0) + 1)
    }
  }
  const topMentions = [...mentionCounts.entries()]
    .map(([label, value]) => ({ label: label.startsWith('@') ? label : `@${label}`, value, tone: 'ink' as const }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6)

  return (
    <section className="space-y-14">
      {/* ─── Overview ────────────────────────────────────────────────── */}
      <DashSection
        eyebrow="Overview"
        title="Every detection so far"
        hint="Every confirmed hit we've written, regardless of when the post was originally published."
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 border border-[var(--color-border)] bg-[var(--color-border)] gap-px">
          <KpiTile label="Total hits" value={totalHits.toLocaleString()} sub="all time" />
          <KpiTile label="This week" value={thisWeekHits.toLocaleString()} sub="last 7 days" />
          <KpiTile label="Active creators" value={activeCreators.toString()} sub="with ≥1 hit" />
          <KpiTile label="Video hits" value={videoHits.toLocaleString()} sub="frame analysis" />
          <KpiTile label="Top platform" value={topPlatform} sub={`${Math.max(igHits, ttHits)} hits`} />
          <KpiTile label="Avg confidence" value={`${avgConf}%`} sub="across hits" />
        </div>
      </DashSection>

      {/* ─── Activity ────────────────────────────────────────────────── */}
      <DashSection
        eyebrow="Activity"
        title="Momentum over time"
        hint={`Detection volume and new creator discovery bucketed daily for the last ${days} days.`}
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <DashCard title="Detections" sub="Daily hits · Instagram vs TikTok" span={2}>
            <LineChart series={[igSeries, ttSeries]} height={220} />
          </DashCard>
          <DashCard title="New creators" sub="First-time detection per handle">
            <StackedDayBars series={[newCreatorsSeries]} height={220} days={days} />
          </DashCard>
        </div>
      </DashSection>

      {/* ─── Who ─────────────────────────────────────────────────────── */}
      <DashSection
        eyebrow="Creators"
        title="Who's driving the mentions"
        hint="Top fans ranked by confirmed hits, plus the hashtags delivering them."
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <DashCard title="Top fans" sub="Ranked by confirmed hits · growth vs prior period" span={2}>
            {leaderboard.length === 0 ? (
              <EmptyBlock label="Waiting for the first hit." />
            ) : (
              <ol className="divide-y divide-[var(--color-border)]">
                {leaderboard.map((g, i) => (
                  <li key={g.handle}>
                    <Link
                      to={`/creators/${g.handle}`}
                      className="flex items-center gap-4 py-3 group"
                    >
                      <span className="stelz-display text-[20px] w-8 text-right text-[var(--color-ink-subtle)] tabular-nums shrink-0">
                        {i + 1}
                      </span>
                      <span className="w-10 h-10 rounded-full overflow-hidden border border-[var(--color-border)] bg-[var(--color-bg)] shrink-0">
                        <Img src={g.avatar || g.firstImage} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-medium truncate group-hover:underline">@{g.handle}</span>
                        <span className="block text-[11px] text-[var(--color-ink-subtle)]">
                          {g.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
                        </span>
                      </span>
                      {g.growth !== 0 && (
                        <span
                          className="rounded-full px-2 py-0.5 text-[10px] font-medium text-white shrink-0"
                          style={{ background: g.growth > 0 ? '#6f9f3c' : '#e8402f' }}
                        >
                          {g.growth > 0 ? '+' : ''}{g.growth.toFixed(0)}%
                        </span>
                      )}
                      <span className="w-28 shrink-0 hidden sm:block">
                        <span className="block h-1.5 bg-[var(--color-border)] relative overflow-hidden">
                          <span
                            className="absolute inset-y-0 left-0 bg-[var(--color-ink)]"
                            style={{ width: `${Math.round((g.hits / maxLeaderHits) * 100)}%` }}
                          />
                        </span>
                      </span>
                      <span className="text-right shrink-0 w-12">
                        <span className="block text-[16px] font-medium tabular-nums leading-none">{g.hits}</span>
                        <span className="block text-[9px] uppercase tracking-wider text-[var(--color-ink-subtle)] mt-0.5">hits</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </DashCard>

          <DashCard title="Top hashtags" sub="Confirmed hits per tag">
            {topTags.length === 0 ? <EmptyBlock label="No hashtag hits yet." /> : <BarChart rows={topTags} />}
          </DashCard>
        </div>
      </DashSection>

      {/* ─── What ────────────────────────────────────────────────────── */}
      <DashSection
        eyebrow="Content"
        title="What's being shown"
        hint="Where the brand appears — product mix, platform split, and the audio and effects driving each post."
      >
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DashCard title="Product line" sub="Which variant gets detected">
            {productSlices.length === 0 ? (
              <EmptyBlock label="No product breakdown yet." />
            ) : (
              <Donut slices={productSlices} centreLabel={totalHits.toLocaleString()} centreSub="hits" />
            )}
          </DashCard>

          <DashCard title="Platform" sub="Instagram vs TikTok share">
            {(igHits + ttHits) === 0 ? (
              <EmptyBlock label="No platform data yet." />
            ) : (
              <Donut slices={platformSlices} centreLabel={`${totalHits}`} centreSub="hits" />
            )}
          </DashCard>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <DashCard title="Top sounds" sub="Most-used audio on hit videos">
            {topSounds.length === 0 ? (
              <EmptyBlock label="No music data yet." />
            ) : (
              <ul className="divide-y divide-[var(--color-border)]">
                {topSounds.map((s, i) => (
                  <li key={i} className="flex items-center gap-3 py-2.5">
                    <span className="w-8 h-8 rounded-full bg-[var(--color-bg)] border border-[var(--color-border)] flex items-center justify-center text-[13px] text-[var(--color-ink)] shrink-0">
                      ♫
                    </span>
                    <div className="min-w-0 flex-1">
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noopener" className="hover:underline truncate block text-[13px] font-medium">{s.label}</a>
                      ) : (
                        <span className="truncate block text-[13px] font-medium">{s.label}</span>
                      )}
                      <div className="text-[11px] text-[var(--color-ink-subtle)] truncate mt-0.5">
                        {s.artist || '—'}{s.original ? ' · original sound' : ''}
                      </div>
                    </div>
                    <span className="rounded-full border border-[var(--color-ink)] px-2 py-0.5 text-[10px] tabular-nums text-[var(--color-ink)] shrink-0">
                      ×{s.count}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </DashCard>

          <DashCard title="Top effects" sub="TikTok stickers and filters">
            {topEffects.length === 0 ? <EmptyBlock label="No effect data yet." /> : <BarChart rows={topEffects} />}
          </DashCard>

          <DashCard title="Top mentions" sub="@handles tagged in captions">
            {topMentions.length === 0 ? <EmptyBlock label="No mentions yet." /> : <BarChart rows={topMentions} />}
          </DashCard>
        </div>

        <DashCard title="Day-of-week activity" sub="When creators publish detected content">
          <BarChart rows={dowRows} valueFmt={(n) => `${n}`} />
        </DashCard>
      </DashSection>
    </section>
  )
}

function DashSection({
  eyebrow, title, hint, children,
}: { eyebrow: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-6">
      <header className="flex items-end justify-between gap-6 border-b-2 border-[var(--color-ink)] pb-4">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-accent)] font-medium mb-2">
            {eyebrow}
          </div>
          <h2 className="stelz-display text-[22px] lg:text-[26px] leading-none text-[var(--color-ink)]">{title}</h2>
        </div>
        {hint && (
          <p className="hidden md:block text-[12px] text-[var(--color-ink-muted)] leading-relaxed max-w-[360px] text-right">
            {hint}
          </p>
        )}
      </header>
      <div className="space-y-6">{children}</div>
    </section>
  )
}

function DashCard({
  title, sub, span, children,
}: { title: string; sub?: string; span?: 2 | 3; children: React.ReactNode }) {
  const spanCls = span === 2 ? 'lg:col-span-2' : span === 3 ? 'lg:col-span-3' : ''
  return (
    <Card className={`p-5 lg:p-6 ${spanCls}`}>
      <header className="mb-5">
        <h3 className="text-[14px] font-medium tracking-tight text-[var(--color-ink)]">{title}</h3>
        {sub && <p className="text-[11px] text-[var(--color-ink-muted)] mt-1">{sub}</p>}
      </header>
      {children}
    </Card>
  )
}

function EmptyBlock({ label }: { label: string }) {
  return (
    <div className="py-10 text-center text-[12px] text-[var(--color-ink-subtle)]">{label}</div>
  )
}

function KpiTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-[var(--color-surface)] p-5 lg:p-6 flex flex-col gap-2">
      <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)]">{label}</div>
      <div className="stelz-display text-[30px] tabular-nums leading-none text-[var(--color-ink)]">{value}</div>
      <div className="text-[11px] text-[var(--color-ink-muted)] mt-auto">{sub}</div>
    </div>
  )
}

function PickCard({ d, onOpen }: { d: DetectionRow; onOpen: () => void }) {
  return (
    <div className="bg-[var(--color-surface)] flex flex-col">
      <button onClick={onOpen} className="block aspect-[4/3] bg-[var(--color-bg)] text-left">
        <Img src={imageUrlFor(d)} />
      </button>
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <Link to={`/creators/${d.creator_handle}`} className="text-[13px] font-medium hover:underline truncate min-w-0">@{d.creator_handle}</Link>
          {d.creator_tier === 'tier_1' && <Badge tone="accent">T1</Badge>}
          {d.product_line && <Badge tone="muted">{PRODUCT_LINE_LABEL[d.product_line] ?? d.product_line}</Badge>}
        </div>
        {d.post_caption && <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed line-clamp-2">"{d.post_caption}"</p>}
        <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)] tabular-nums mt-auto">
          <span>{((d.confidence ?? 0) * 100).toFixed(0)}% · {(d.follower_count ?? 0).toLocaleString()} followers</span>
          <span>{d.posted_at ? timeAgo(d.posted_at) : '—'}</span>
        </div>
      </div>
    </div>
  )
}

function RunScanButton({ onComplete, liveHits }: { onComplete: () => void; liveHits?: number }) {
  const [state, setState] = useState<ScanState | null>(null)
  const [clicking, setClicking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const prevRunning = useRef(false)

  // Subscribe once to brand.scan — persists across refresh, updates live.
  useEffect(() => {
    const unsub = fbSubscribeScanState((s) => setState(s))
    return () => unsub()
  }, [])

  // Derived: are we currently scanning?
  // If no worker has written for 5 minutes, treat the session as dead —
  // a Pub/Sub worker crashed hard (OOM/SIGKILL) before its `finally` ran.
  // The pill flips to "stalled" so the user isn't stuck watching "18/19"
  // forever.
  const queued = state?.hashtagQueued ?? 0
  const done = state?.hashtagDone ?? 0
  const now = Date.now()
  const lastActMs = state?.lastActivityAt ? new Date(state.lastActivityAt).getTime() : 0
  const staleMs = now - lastActMs
  const isStale = !!state?.startedAt && !state.finishedAt && staleMs > 5 * 60_000
  const running = !!state?.startedAt && !state.finishedAt && !isStale
  const progressPct = queued > 0 ? Math.round((done / queued) * 100) : 0

  // On transition running → done/stale, trigger parent refresh (once).
  useEffect(() => {
    if (prevRunning.current && !running && (state?.finishedAt || isStale)) {
      onComplete()
    }
    prevRunning.current = running
  }, [running, state?.finishedAt, isStale, onComplete])

  async function go() {
    setClicking(true); setError(null)
    try {
      await fbBootstrapBrand()
      await fbStepHashtags(500, 50)
      // creators + SRS still run in the background — fire-and-forget without
      // blocking the pill. Failures surface as `error` on brand.scan later.
      void fbStepCreators(80, 8).catch(() => {})
      void fbStepSrs().catch(() => {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setClicking(false)
    }
  }

  const startedAgo = state?.startedAt ? timeAgo(state.startedAt) : null
  const finishedAgo = state?.finishedAt ? timeAgo(state.finishedAt) : null
  // Old scan info shouldn't linger forever — hide the pill 6h after finish.
  const finishedRecently = !!state?.finishedAt &&
    (Date.now() - new Date(state.finishedAt).getTime()) < 6 * 3600_000
  // Display hits = the same deduped post-level count the dashboard shows.
  // scan.detectionsHit counts every frame doc and reads inflated.
  const displayHits = liveHits ?? state?.detectionsHit ?? 0

  const busy = clicking || running
  return (
    <div className="flex items-center gap-3">
      <Button
        variant="primary"
        size="sm"
        disabled={busy}
        onClick={go}
      >
        <span className="inline-flex items-center gap-2">
          {busy && <Spinner size={10} />}
          <span>{clicking ? 'Starting…' : running ? 'Scanning' : 'Run scan'}</span>
        </span>
      </Button>

      {(running || isStale || finishedRecently || error) && (
        <div className="hidden sm:flex items-center gap-2.5 h-8 px-3 border border-[var(--color-border)] bg-[var(--color-surface)] text-[12px]">
          {error ? (
            <>
              <StatusDot tone="bad" />
              <span className="text-[var(--color-bad)] truncate max-w-[240px]">{error}</span>
            </>
          ) : isStale ? (
            <>
              <StatusDot tone="bad" />
              <span className="tabular-nums text-[var(--color-ink)]">
                Stalled at <span className="font-medium">{done}/{queued}</span>
              </span>
              <span className="tabular-nums text-[var(--color-ink-muted)]">
                · {(state?.postsWritten ?? 0).toLocaleString()} posts
              </span>
              <span className="text-[var(--color-ink-subtle)]">· no activity {timeAgo(state!.lastActivityAt!)}</span>
            </>
          ) : running ? (
            <>
              <StatusDot tone="accent" pulse />
              <span className="tabular-nums">
                <span className="text-[var(--color-ink)] font-medium">{done}/{queued}</span>
                <span className="text-[var(--color-ink-subtle)]"> tags</span>
              </span>
              {(state?.postsWritten ?? 0) > 0 && (
                <span className="tabular-nums text-[var(--color-ink-muted)]">
                  · {state!.postsWritten.toLocaleString()} posts
                </span>
              )}
              {(state?.detectTasksEnqueued ?? 0) > 0 && (
                <span className="tabular-nums text-[var(--color-ink-muted)]">
                  · {state!.detectTasksEnqueued.toLocaleString()} queued
                </span>
              )}
              {startedAgo && <span className="text-[var(--color-ink-subtle)]">· {startedAgo}</span>}
              <div className="w-16 h-0.5 bg-[var(--color-border)] relative ml-1 overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 bg-[var(--color-ink)] transition-all duration-500"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </>
          ) : state?.finishedAt ? (
            (() => {
              const analyzed = state.detectionsCompleted ?? 0
              const toAnalyze = state.detectTasksEnqueued ?? 0
              const analyzing = toAnalyze > 0 && analyzed < toAnalyze
              return analyzing ? (
                <>
                  <StatusDot tone="accent" pulse />
                  <span className="tabular-nums">
                    <span className="text-[var(--color-ink)] font-medium">Analyzing</span>
                    <span className="text-[var(--color-ink-muted)]"> · {analyzed.toLocaleString()}/{toAnalyze.toLocaleString()}</span>
                  </span>
                  {displayHits > 0 && (
                    <span className="tabular-nums text-[var(--color-ink-muted)]">· {displayHits} hits</span>
                  )}
                  <div className="w-16 h-0.5 bg-[var(--color-border)] relative ml-1 overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 bg-[var(--color-ink)] transition-all duration-500"
                      style={{ width: `${toAnalyze > 0 ? Math.round((analyzed / toAnalyze) * 100) : 0}%` }}
                    />
                  </div>
                </>
              ) : (
                <>
                  <StatusDot tone={state.endReason === 'watchdog_stale' ? 'muted' : 'good'} />
                  <span className="tabular-nums text-[var(--color-ink)]">
                    {done} tags · {(state.postsWritten ?? 0).toLocaleString()} posts
                  </span>
                  {displayHits > 0 && (
                    <span className="tabular-nums text-[var(--color-ink-muted)]">· {displayHits} hits</span>
                  )}
                  {(state.skippedCount ?? 0) > 0 && (
                    <span className="tabular-nums text-[var(--color-ink-muted)]">· {state.skippedCount} skipped</span>
                  )}
                  {finishedAgo && <span className="text-[var(--color-ink-subtle)]">· {finishedAgo} ago</span>}
                </>
              )
            })()
          ) : null}
        </div>
      )}
    </div>
  )
}

function Spinner({ size = 12 }: { size?: number }) {
  return (
    <span
      className="inline-block rounded-full border-2 border-white/25 border-t-white animate-spin align-[-1px]"
      style={{ width: size, height: size }}
      aria-label="Loading"
    />
  )
}

function RefreshingTag() {
  return (
    <div className="hidden sm:inline-flex items-center gap-2 h-8 px-3 border border-[var(--color-border)] bg-[var(--color-surface)] text-[11px] text-[var(--color-ink-muted)]">
      <DarkSpinner size={10} />
      <span>refreshing</span>
    </div>
  )
}

function DarkSpinner({ size = 12 }: { size?: number }) {
  return (
    <span
      className="inline-block rounded-full border-2 border-[var(--color-border-strong)] border-t-[var(--color-ink)] animate-spin align-[-1px]"
      style={{ width: size, height: size }}
    />
  )
}

function StatusDot({ tone, pulse }: { tone: 'accent' | 'good' | 'bad' | 'muted'; pulse?: boolean }) {
  const bg =
    tone === 'accent' ? 'bg-[var(--color-accent)]' :
    tone === 'good' ? 'bg-[var(--color-good)]' :
    tone === 'bad' ? 'bg-[var(--color-bad)]' :
    'bg-[var(--color-ink-subtle)]'
  return (
    <span className="relative inline-flex w-2 h-2">
      {pulse && <span className={`absolute inset-0 rounded-full ${bg} opacity-40 animate-ping`} />}
      <span className={`relative inline-block w-2 h-2 rounded-full ${bg}`} />
    </span>
  )
}

function FilterDropdown<T extends string | number>({ label, value, options, onChange }: {
  label: string; value: T | null; options: { id: T; label: string; count: number }[]; onChange: (v: T | null) => void
}) {
  const [open, setOpen] = useState(false)
  const active = options.find((o) => o.id === value)
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} className={`rounded-full px-3.5 py-1.5 text-[12px] border transition-colors ${active ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white' : 'border-[var(--color-ink)] text-[var(--color-ink)] hover:bg-[var(--color-ink)] hover:text-white'}`}>
        {label}{active ? ` · ${active.label}` : ''} ▾
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full left-0 mt-1 z-20 min-w-[180px] bg-[var(--color-surface)] border border-[var(--color-border-strong)]">
            <button onClick={() => { onChange(null); setOpen(false) }} className="w-full px-3 py-2 text-left text-[12px] border-b border-[var(--color-border)] hover:bg-[var(--color-bg)]">All</button>
            {options.map((o) => (
              <button key={String(o.id)} onClick={() => { onChange(o.id); setOpen(false) }} className="w-full px-3 py-2 text-left text-[12px] hover:bg-[var(--color-bg)] flex items-center justify-between">
                <span>{o.label}</span>
                <span className="text-[var(--color-ink-subtle)] tabular-nums">{o.count}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SkeletonHome() {
  return (
    <div className="space-y-4">
      <div className="h-10 bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
      <div className="h-[260px] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="h-[180px] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
        <div className="h-[180px] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
        <div className="h-[180px] bg-[var(--color-surface)] border border-[var(--color-border)] animate-pulse" />
      </div>
    </div>
  )
}

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d`
}
