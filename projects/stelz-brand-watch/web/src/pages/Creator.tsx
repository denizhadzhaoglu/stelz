// Creator profile — built entirely from real detections. Shows who they are
// (avatar, bio, platform, followers) and every piece of content where the
// brand was found, deduped to one card per post.

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  PageShell, Card, Badge, Button, Img, PRODUCT_LINE_LABEL,
} from '../components/ui'
import { imageUrlFor, dedupeByPost, parentPostKey, type DetectionRow } from '../lib/types'
import { fetchDetections } from '../lib/data'
import { DetectionDrawer } from '../components/DetectionDrawer'

export default function Creator() {
  const { handle = '' } = useParams()
  const [rows, setRows] = useState<DetectionRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<DetectionRow | null>(null)

  useEffect(() => {
    if (!handle) return
    let cancelled = false
    setLoading(true)
    fetchDetections({ creatorHandle: handle, limit: 300 })
      .then((det) => { if (!cancelled) { setRows(det); setLoading(false) } })
      .catch((e) => { if (!cancelled) { setError(e.message ?? String(e)); setLoading(false) } })
    return () => { cancelled = true }
  }, [handle])

  const posts = useMemo(
    () => dedupeByPost(rows).filter((d) => d.detected === true && d.is_false_positive !== true),
    [rows],
  )

  const profile = useMemo(() => {
    const withAuthor = rows.find((r) => r.extras?.author)
    const author = withAuthor?.extras?.author ?? null
    const platform = rows[0]?.platform ?? 'instagram'
    const followers = rows.reduce((mx, r) => Math.max(mx, r.follower_count ?? 0), 0)
    const totalLikes = posts.reduce((s, r) => s + (r.likes_count ?? 0), 0)
    const totalViews = posts.reduce((s, r) => s + (r.views_count ?? 0), 0)
    const avgConf = posts.length ? posts.reduce((s, r) => s + (r.confidence ?? 0), 0) / posts.length : 0
    const dates = posts.map((p) => p.posted_at).filter(Boolean).sort() as string[]
    const products = new Map<string, number>()
    for (const p of posts) if (p.product_line) products.set(p.product_line, (products.get(p.product_line) ?? 0) + 1)
    const externalUrl = author?.profileUrl
      || (platform === 'tiktok' ? `https://www.tiktok.com/@${handle}` : `https://www.instagram.com/${handle}/`)
    return {
      platform,
      avatar: author?.avatar ?? null,
      bio: author?.signature ?? null,
      verifiedAccount: author?.verified ?? false,
      followers,
      totalLikes,
      totalViews,
      avgConf,
      firstSeen: dates[0] ?? null,
      lastSeen: dates[dates.length - 1] ?? null,
      products: [...products.entries()].sort((a, b) => b[1] - a[1]),
      externalUrl,
      videoCount: posts.filter((p) => p.frame_idx != null).length,
      imageCount: posts.filter((p) => p.frame_idx == null).length,
    }
  }, [rows, posts, handle])

  return (
    <PageShell
      title={`@${handle}`}
      subtitle={profile.platform === 'tiktok' ? 'TikTok creator' : 'Instagram creator'}
      actions={
        <a href={profile.externalUrl} target="_blank" rel="noreferrer">
          <Button variant="secondary" size="sm">Open profile ↗</Button>
        </a>
      }
    >
      {loading && <div className="text-[14px] text-[var(--color-ink-muted)] py-16 text-center">Loading…</div>}
      {error && <div className="text-[13px] text-[var(--color-bad)] py-16 text-center">{error}</div>}
      {!loading && !error && posts.length === 0 && (
        <div className="text-[14px] text-[var(--color-ink-muted)] py-16 text-center">No confirmed detections for @{handle}.</div>
      )}

      {!loading && posts.length > 0 && (
        <div className="space-y-10">
          {/* ─── Identity + KPIs ─────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] gap-6">
            {/* Profile card */}
            <Card className="p-6">
              <div className="flex items-center gap-4 mb-5">
                <div className="w-20 h-20 rounded-full overflow-hidden border border-[var(--color-border)] bg-[var(--color-bg)] shrink-0">
                  <Img src={profile.avatar || imageUrlFor(posts[0])} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <div className="text-[17px] font-medium truncate">@{handle}</div>
                    {profile.verifiedAccount && <span className="text-[var(--color-accent)]" title="Verified account">✓</span>}
                  </div>
                  <div className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">
                    {profile.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
                    {profile.followers > 0 ? ` · ${profile.followers.toLocaleString()} followers` : ''}
                  </div>
                </div>
              </div>

              {profile.bio && (
                <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed whitespace-pre-line mb-5 border-b border-[var(--color-border)] pb-5">
                  {profile.bio}
                </p>
              )}

              <div className="space-y-2.5 text-[12px]">
                {profile.products.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {profile.products.map(([p, n]) => (
                      <Badge key={p} tone="muted">{PRODUCT_LINE_LABEL[p] ?? p} ×{n}</Badge>
                    ))}
                  </div>
                )}
                <div className="text-[var(--color-ink-subtle)] tabular-nums pt-1">
                  {profile.firstSeen && <>First seen {new Date(profile.firstSeen).toLocaleDateString('nl-NL', { day: '2-digit', month: 'short', year: 'numeric' })}</>}
                  {profile.lastSeen && profile.lastSeen !== profile.firstSeen && <> · last {new Date(profile.lastSeen).toLocaleDateString('nl-NL', { day: '2-digit', month: 'short' })}</>}
                </div>
              </div>
            </Card>

            {/* KPI grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)] self-start">
              <CreatorKpi label="Brand mentions" value={posts.length.toLocaleString()} sub="unique posts" />
              <CreatorKpi label="Videos" value={profile.videoCount.toLocaleString()} sub={`${profile.imageCount} images`} />
              <CreatorKpi label="Avg confidence" value={`${(profile.avgConf * 100).toFixed(0)}%`} sub="across hits" />
              <CreatorKpi label="Combined likes" value={profile.totalLikes.toLocaleString()} sub="on detected posts" />
              <CreatorKpi label="Combined views" value={profile.totalViews > 0 ? profile.totalViews.toLocaleString() : '—'} sub="video plays" />
              <CreatorKpi label="Followers" value={profile.followers > 0 ? profile.followers.toLocaleString() : '—'} sub={profile.platform === 'tiktok' ? 'TikTok' : 'Instagram'} />
            </div>
          </div>

          {/* ─── Content gallery ─────────────────────────────────────── */}
          <section className="space-y-5">
            <header className="border-b-2 border-[var(--color-ink)] pb-4">
              <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-accent)] font-medium mb-2">Content</div>
              <h2 className="stelz-display text-[22px] lg:text-[26px] leading-none text-[var(--color-ink)]">Where Stëlz shows up</h2>
            </header>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {posts.map((d) => {
                const conf = (d.confidence ?? 0) * 100
                return (
                  <button
                    key={d.detection_id}
                    onClick={() => setActive(d)}
                    className="text-left bg-[var(--color-surface)] border border-[var(--color-border)] hover:border-[var(--color-border-strong)] transition-colors flex flex-col"
                  >
                    <div className="relative aspect-[4/5] bg-[var(--color-bg)] overflow-hidden">
                      <Img src={imageUrlFor(d)} />
                      {d.frame_idx != null && (
                        <span className="absolute bottom-2 right-2 text-[10px] bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
                          ▶ video{(d.frame_hits ?? 0) > 1 ? ` · ${d.frame_hits} frames` : ''}
                        </span>
                      )}
                      {d.verified === true && (
                        <span className="absolute top-2 left-2 text-[10px] uppercase tracking-widest bg-[var(--color-good)] text-white px-2 py-0.5">✓</span>
                      )}
                    </div>
                    <div className="p-3 flex flex-col gap-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] text-[var(--color-ink-muted)] truncate">
                          {d.product_line ? (PRODUCT_LINE_LABEL[d.product_line] ?? d.product_line) : 'Detection'}
                          {d.surface_type ? ` · ${d.surface_type.replace(/_/g, ' ')}` : ''}
                        </span>
                        <span className={`text-[12px] tabular-nums font-medium shrink-0 ${conf >= 85 ? 'text-[var(--color-good)]' : conf >= 75 ? 'text-[var(--color-warn)]' : 'text-[var(--color-bad)]'}`}>
                          {conf.toFixed(0)}%
                        </span>
                      </div>
                      {d.post_caption && (
                        <p className="text-[11px] text-[var(--color-ink-subtle)] line-clamp-1">{d.post_caption}</p>
                      )}
                      <div className="flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
                        <span>
                          {(d.likes_count ?? 0) > 0 && `♥ ${(d.likes_count!).toLocaleString()}`}
                          {(d.views_count ?? 0) > 0 && `  ▶ ${(d.views_count!).toLocaleString()}`}
                        </span>
                        <span>{d.posted_at ? new Date(d.posted_at).toLocaleDateString('nl-NL', { day: '2-digit', month: 'short' }) : ''}</span>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>
        </div>
      )}

      <DetectionDrawer
        detection={active}
        similar={active ? posts.filter((d) => d.detection_id !== active.detection_id).slice(0, 8) : []}
        frames={active ? rows
          .filter((d) => d.detected === true && parentPostKey(d) === parentPostKey(active))
          .sort((a, b) => (a.frame_idx ?? 0) - (b.frame_idx ?? 0)) : []}
        onClose={() => setActive(null)}
      />
    </PageShell>
  )
}

function CreatorKpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-[var(--color-surface)] p-5 flex flex-col gap-1.5">
      <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)]">{label}</div>
      <div className="stelz-display text-[26px] tabular-nums leading-none text-[var(--color-ink)]">{value}</div>
      <div className="text-[11px] text-[var(--color-ink-muted)]">{sub}</div>
    </div>
  )
}
