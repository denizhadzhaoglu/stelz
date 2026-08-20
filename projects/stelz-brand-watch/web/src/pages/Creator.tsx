// Creator profile — built entirely from real detections. Shows who they are
// (avatar, bio, platform, followers) and every piece of content where the
// brand was found, deduped to one card per post.

import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  PageShell, Card, Badge, Button, Img, Avatar, PRODUCT_LINE_LABEL,
} from '../components/ui'
import { imageUrlFor, dedupeByPost, parentPostKey, type DetectionRow, type ResonanceRow } from '../lib/types'
import { fetchDetections, fetchResonanceForCreator, fetchCreatorProfile } from '../lib/data'
import { DetectionDrawer } from '../components/DetectionDrawer'
import { srsLayers, srsMode, srsHeadline, MODE_BLURB } from '../lib/srs'
import { sceneBreakdown } from '../lib/scenes'
import { ReadOnlyNotice } from '../lib/membership'

export default function Creator() {
  const { handle = '' } = useParams()
  const [rows, setRows] = useState<DetectionRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<DetectionRow | null>(null)
  const [resonance, setResonance] = useState<ResonanceRow | null>(null)
  // The creator record: the only current source of an Instagram follower
  // count, bio and avatar. Detections froze whatever was known at detect time,
  // and the resonance doc is only as fresh as the last SRS run.
  const [profileRecord, setProfileRecord] = useState<{ followerCount: number | null; bio: string | null; avatarUrl: string | null; fullName: string | null } | null>(null)

  useEffect(() => {
    if (!handle) return
    let cancelled = false
    setLoading(true)
    fetchDetections({ creatorHandle: handle, limit: 300 })
      .then((det) => { if (!cancelled) { setRows(det); setLoading(false) } })
      .catch((e) => { if (!cancelled) { setError(e.message ?? String(e)); setLoading(false) } })
    return () => { cancelled = true }
  }, [handle])

  // Resonance is a separate, optional read: a creator with detections but no
  // SRS doc is normal (scoring runs as its own step), so a failure here must
  // not take the page down with it.
  useEffect(() => {
    if (!handle) return
    let cancelled = false
    setResonance(null)
    setProfileRecord(null)
    fetchResonanceForCreator(handle)
      .then((r) => { if (!cancelled) setResonance(r) })
      .catch(() => { if (!cancelled) setResonance(null) })
    fetchCreatorProfile(handle)
      .then((p) => { if (!cancelled) setProfileRecord(p) })
      .catch(() => { if (!cancelled) setProfileRecord(null) })
    return () => { cancelled = true }
  }, [handle])

  // Detections carry a follower count only when the scrape happened to return
  // one — Instagram's hashtag endpoint does not. The resonance doc is built
  // from the creator record, which is populated by the profile scrape, so it
  // often has the number when the detections don't. Prefer whichever we have.
  const followersFromPosts = useMemo(
    () => rows.reduce((mx, r) => Math.max(mx, r.follower_count ?? 0), 0),
    [rows],
  )
  const followers = Math.max(
    followersFromPosts,
    resonance?.follower_count ?? 0,
    profileRecord?.followerCount ?? 0,
  )

  const posts = useMemo(
    () => dedupeByPost(rows).filter((d) => d.detected === true && d.is_false_positive !== true),
    [rows],
  )

  const profile = useMemo(() => {
    const withAuthor = rows.find((r) => r.extras?.author)
    const author = withAuthor?.extras?.author ?? null
    const platform = rows[0]?.platform ?? 'instagram'
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
      <ReadOnlyNotice />

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
                  <Avatar src={profileRecord?.avatarUrl ?? profile.avatar} handle={handle} className="w-full h-full text-[24px]" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <div className="text-[17px] font-medium truncate">@{handle}</div>
                    {profile.verifiedAccount && <span className="text-[var(--color-accent)]" title="Verified account">✓</span>}
                  </div>
                  <div className="text-[12px] text-[var(--color-ink-muted)] mt-0.5">
                    {profile.platform === 'tiktok' ? 'TikTok' : 'Instagram'}
                    {followers > 0 ? ` · ${followers.toLocaleString()} followers` : ''}
                  </div>
                </div>
              </div>

              {(profileRecord?.bio || profile.bio) && (
                <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed whitespace-pre-line mb-5 border-b border-[var(--color-border)] pb-5">
                  {profileRecord?.bio || profile.bio}
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
              <CreatorKpi label="Followers" value={followers > 0 ? followers.toLocaleString() : '—'} sub={followers > 0 ? (profile.platform === 'tiktok' ? 'TikTok' : 'Instagram') : 'not reported by the scrape'} />
            </div>
          </div>

          {/* ─── Why this creator matters ────────────────────────────── */}
          <WhyTheyMatter resonance={resonance} posts={posts} followers={followers} />

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

/**
 * The "why does this person matter" panel: SRS layer breakdown on the left,
 * audience profile on the right.
 *
 * A follower count alone can't answer that question — it can't separate someone
 * with reach from someone genuinely embedded in the scene the brand lives in.
 * The SRS layers can, which is the whole reason the score exists; it was simply
 * never rendered anywhere in the app (fetchResonanceForCreator was written and
 * left unused).
 */
function WhyTheyMatter({
  resonance, posts, followers,
}: { resonance: ResonanceRow | null; posts: DetectionRow[]; followers: number }) {
  // Audience profile is derived from detections, so it stands on its own when
  // there is no SRS doc yet.
  const scenes = useMemo(() => sceneBreakdown(posts).filter((s) => s.key !== 'other').slice(0, 3), [posts])
  const engagement = useMemo(() => {
    // Likes per post against follower count. Only meaningful with both, and
    // only over posts that actually carry a like count.
    const withLikes = posts.filter((p) => (p.likes_count ?? 0) > 0)
    if (!withLikes.length || followers <= 0) return null
    const avgLikes = withLikes.reduce((s, p) => s + (p.likes_count ?? 0), 0) / withLikes.length
    return { avgLikes, rate: (avgLikes / followers) * 100 }
  }, [posts, followers])

  const layers = resonance ? srsLayers(resonance) : []
  const headline = resonance ? srsHeadline(resonance) : null
  const mode = resonance ? srsMode(resonance) : null

  return (
    <section className="space-y-5">
      <header className="border-b-2 border-[var(--color-ink)] pb-4">
        <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-accent)] font-medium mb-2">Audience</div>
        <h2 className="stelz-display text-[22px] lg:text-[26px] leading-none text-[var(--color-ink)]">
          Why this creator matters
        </h2>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Resonance breakdown ── */}
        <Card className="p-6">
          {!resonance ? (
            <div className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed">
              No resonance score for @{posts[0]?.creator_handle} yet. Scoring runs as its own
              step after a scan, so creators found in the most recent run appear here later.
            </div>
          ) : (
            <>
              <div className="flex items-baseline gap-3 mb-1">
                <span className="stelz-display text-[34px] leading-none tabular-nums text-[var(--color-ink)]">
                  {Math.round(resonance.srs)}
                </span>
                <span className="text-[11px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)]">
                  Resonance
                </span>
              </div>
              {headline && (
                <p className="text-[13px] font-medium text-[var(--color-ink)] mb-1">{headline}</p>
              )}
              {mode && (
                <p className="text-[11px] text-[var(--color-ink-subtle)] leading-relaxed mb-5">
                  {MODE_BLURB[mode]}
                </p>
              )}

              <ul className="space-y-3">
                {layers.map((l) => (
                  <li key={l.key}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[12px] font-medium" title={l.meaning}>{l.label}</span>
                      <span className="text-[11px] tabular-nums text-[var(--color-ink-subtle)] shrink-0">
                        {/* A null layer says "not computed" and must not be
                            drawn as a zero bar — the two mean opposite things. */}
                        {l.value == null ? 'not scored' : `${Math.round(l.value * 100)}`}
                        <span className="text-[var(--color-ink-subtle)]"> · {l.weight}% weight</span>
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 bg-[var(--color-border)] relative overflow-hidden">
                      {l.value != null && (
                        <span
                          className="absolute inset-y-0 left-0 bg-[var(--color-ink)]"
                          style={{ width: `${Math.round(Math.max(0, Math.min(1, l.value)) * 100)}%` }}
                        />
                      )}
                    </div>
                    <p className="mt-1 text-[11px] text-[var(--color-ink-subtle)] leading-relaxed">{l.meaning}</p>
                  </li>
                ))}
              </ul>

              <p className="mt-5 pt-3 border-t border-[var(--color-border)] text-[11px] text-[var(--color-ink-subtle)] leading-relaxed">
                Weights depend on how much confirmed data the brand has, so scores are
                comparable between creators but not across brands at different stages.
              </p>
            </>
          )}
        </Card>

        {/* ── Follower profile ── */}
        <Card className="p-6">
          <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)] mb-4">
            Audience profile
          </div>

          <dl className="space-y-3 text-[12px]">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-muted)]">Reach</dt>
              <dd className="tabular-nums font-medium">
                {followers > 0 ? followers.toLocaleString() : '—'}
                <span className="text-[var(--color-ink-subtle)] font-normal"> followers</span>
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-muted)]">Avg likes on brand posts</dt>
              <dd className="tabular-nums font-medium">
                {engagement ? Math.round(engagement.avgLikes).toLocaleString() : '—'}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-[var(--color-ink-muted)]">Engagement rate</dt>
              <dd className="tabular-nums font-medium">
                {engagement ? `${engagement.rate.toFixed(1)}%` : '—'}
              </dd>
            </div>
            {resonance?.tier && (
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[var(--color-ink-muted)]">Tier</dt>
                <dd className="font-medium">{resonance.tier.replace('_', ' ')}</dd>
              </div>
            )}
            {resonance?.category && (
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-[var(--color-ink-muted)]">Category</dt>
                <dd className="font-medium capitalize">{resonance.category}</dd>
              </div>
            )}
          </dl>

          <div className="mt-5 pt-4 border-t border-[var(--color-border)]">
            <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)] mb-2.5">
              Scenes they post in
            </div>
            {scenes.length === 0 ? (
              <p className="text-[12px] text-[var(--color-ink-muted)]">
                Not enough scene detail on these posts to place them.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {scenes.map((s) => (
                  <li key={s.key} className="flex items-baseline justify-between gap-3 text-[12px]">
                    <span>{s.label}</span>
                    <span className="tabular-nums text-[var(--color-ink-subtle)] shrink-0">
                      {s.total} {s.total === 1 ? 'post' : 'posts'}
                      {s.untagged > 0 ? ` · ${s.untagged} untagged` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </section>
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
