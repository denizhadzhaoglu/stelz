import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Img, PRODUCT_LINE_LABEL } from './ui'
import { imageUrlFor, loadState, toggleShortlist, toggleHidden, type DetectionRow } from '../lib/data'

export function DetectionDrawer({
  detection,
  similar,
  frames = [],
  onClose,
}: {
  detection: DetectionRow | null
  similar: DetectionRow[]
  frames?: DetectionRow[]
  onClose: () => void
}) {
  const [shortlist, setShortlist] = useState<string[]>(() => loadState().shortlist)
  const [hidden, setHidden] = useState<string[]>(() => loadState().hidden)
  // Which frame's image is showing in the hero slot.
  const [activeFrame, setActiveFrame] = useState<DetectionRow | null>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    if (detection) window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [detection, onClose])

  // Reset frame selection when a different detection opens.
  useEffect(() => { setActiveFrame(null) }, [detection?.detection_id])

  if (!detection) return null
  const d = detection
  const hero = activeFrame ?? d
  const inShortlist = shortlist.includes(d.detection_id)
  const isHidden = hidden.includes(d.creator_handle)

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <aside className="fixed top-0 right-0 h-screen w-full max-w-[640px] bg-[var(--color-surface)] z-50 border-l border-[var(--color-border)] overflow-y-auto">
        <div className="sticky top-0 z-10 bg-[var(--color-surface)] border-b border-[var(--color-border)] px-5 h-12 flex items-center justify-between">
          <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)]">Detection · {d.detection_id.slice(0, 8)}</div>
          <button onClick={onClose} className="w-7 h-7 flex items-center justify-center text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]">✕</button>
        </div>

        <div className="p-5 space-y-6">
          <div className="bg-[var(--color-bg)] border border-[var(--color-border)] relative">
            <div className="aspect-[4/3] relative">
              <Img src={imageUrlFor(hero)} fit="contain" />
              {hero.frame_idx != null && (
                <span className="absolute bottom-2 right-2 text-[10px] bg-[var(--color-ink)]/80 text-white px-2 py-0.5">
                  frame {hero.frame_idx}
                </span>
              )}
            </div>
          </div>

          {/* All detected frames of this post — click to swap the hero image */}
          {frames.length > 1 && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">
                Detected in {frames.length} frames
              </div>
              <div className="flex gap-1.5 flex-wrap">
                {frames.map((f) => (
                  <button
                    key={f.detection_id}
                    onClick={() => setActiveFrame(f)}
                    className={`w-14 h-14 border p-0.5 bg-[var(--color-surface)] transition-colors ${
                      (activeFrame ?? d).detection_id === f.detection_id
                        ? 'border-[var(--color-ink)]'
                        : 'border-[var(--color-border)] hover:border-[var(--color-border-strong)]'
                    }`}
                    title={f.frame_idx != null ? `Frame ${f.frame_idx} · ${((f.confidence ?? 0) * 100).toFixed(0)}%` : undefined}
                  >
                    <Img src={imageUrlFor(f)} />
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {d.product_line && <Badge>{PRODUCT_LINE_LABEL[d.product_line] ?? d.product_line}</Badge>}
            {d.size_in_frame && <Badge tone="muted">size · {d.size_in_frame}</Badge>}
            {d.is_primary_subject && <Badge tone="muted">primary</Badge>}
            <Badge tone={(d.confidence ?? 0) >= 0.85 ? 'good' : (d.confidence ?? 0) >= 0.75 ? 'warn' : 'bad'}>
              {((d.confidence ?? 0) * 100).toFixed(0)}% confidence
            </Badge>
            {d.creator_tier && <Badge tone={d.creator_tier === 'tier_1' ? 'accent' : 'neutral'}>tier {d.creator_tier}</Badge>}
            <Badge tone="muted">{d.platform}</Badge>
          </div>

          <div>
            <Link to={`/creators/${d.creator_handle}`} className="text-[16px] font-medium hover:underline">@{d.creator_handle}</Link>
            <div className="text-[12px] text-[var(--color-ink-muted)] mt-0.5 tabular-nums">
              {(d.follower_count ?? 0).toLocaleString()} followers
              {d.likes_count ? ` · ${d.likes_count.toLocaleString()} likes` : ''}
              {d.posted_at ? ` · ${new Date(d.posted_at).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })}` : ''}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              variant={inShortlist ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => setShortlist(toggleShortlist(d.detection_id))}
            >
              {inShortlist ? '✓ Shortlisted' : '+ Shortlist'}
            </Button>
            <Button size="sm" variant="secondary">Promote to tier 1</Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setHidden(toggleHidden(d.creator_handle))}
            >
              {isHidden ? 'Unhide creator' : 'Hide creator'}
            </Button>
            {d.post_url && (
              <a href={d.post_url} target="_blank" rel="noreferrer">
                <Button size="sm" variant="ghost">Open original ↗</Button>
              </a>
            )}
          </div>

          {d.post_caption && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">Caption</div>
              <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{d.post_caption}</p>
            </div>
          )}

          {(d.context || d.surface_type || d.visible_text || d.activity || d.setting || d.people_count != null) && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">What the AI saw</div>
              <dl className="grid grid-cols-[110px_1fr] gap-y-2.5 gap-x-4 text-[13px]">
                {d.visible_text && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">Text read</dt>
                    <dd className="font-medium tabular-nums text-[var(--color-ink)]">"{d.visible_text}"</dd>
                  </>
                )}
                {d.surface_type && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">Surface</dt>
                    <dd>{d.surface_type.replace(/_/g, ' ')}</dd>
                  </>
                )}
                {d.activity && d.activity !== 'none' && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">Activity</dt>
                    <dd>{d.activity}</dd>
                  </>
                )}
                {d.setting && d.setting !== 'unclear' && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">Setting</dt>
                    <dd className="capitalize">{d.setting}</dd>
                  </>
                )}
                {d.people_count != null && d.people_count > 0 && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">People</dt>
                    <dd className="tabular-nums">{d.people_count}</dd>
                  </>
                )}
                {d.context && (
                  <>
                    <dt className="text-[var(--color-ink-subtle)] text-[11px] uppercase tracking-widest pt-0.5">Notes</dt>
                    <dd className="text-[var(--color-ink-muted)] leading-relaxed">{d.context}</dd>
                  </>
                )}
              </dl>
            </div>
          )}

          {d.post_hashtags && d.post_hashtags.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">Hashtags</div>
              <div className="flex flex-wrap gap-1.5">
                {d.post_hashtags.map((h) => (
                  <span key={h} className="text-[12px] px-2 py-0.5 border border-[var(--color-border-strong)] bg-[var(--color-bg)]">#{h}</span>
                ))}
              </div>
            </div>
          )}

          {similar.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">
                Other hits from @{d.creator_handle}
              </div>
              <div className="grid grid-cols-4 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
                {similar.slice(0, 8).map((s) => (
                  <a key={s.detection_id} href={s.post_url ?? '#'} target="_blank" rel="noreferrer" className="bg-[var(--color-surface)] aspect-square p-1.5 block">
                    <Img src={imageUrlFor(s)} />
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}

