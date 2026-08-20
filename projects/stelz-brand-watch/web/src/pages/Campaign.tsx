// The campaign, both platforms, one table.
//
// The question this page answers is the one the Stories page cannot: of the
// people on the roster, who actually posted, on which surface, and where was
// Stëlz in frame. Instagram stories are a quarter of the answer — a creator can
// deliver a reel, a carousel and four TikToks and show up as silent on a page
// that only reads the 24-hour surface.
//
// EVERY NUMBER SAYS WHICH SURFACE IT CAME FROM. TikTok publishes play counts,
// Instagram publishes story views to the account holder alone, and an IG photo
// post publishes neither. Those three facts do not add up into a "total reach",
// so this page never adds them. See lib/campaign.ts.

import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageShell, Card, Badge } from '../components/ui'
import { MediaTile } from '../components/MediaTile'
import { StoryDetail } from '../components/StoryDetail'
import {
  joinCampaign, campaignRollup, stelzShare, metricFor,
  SURFACE_LABEL, SURFACE_METRIC, SURFACES,
  type CampaignRow, type Surface, type CampaignItem,
} from '../lib/campaign'
import { VERDICT_LABEL, isStelzStory, type StoryVerdict } from '../lib/storyStats'
import { fbFetchCreatorProfiles, type CreatorProfile } from '../lib/firestore'
import { fetchProjects, type Project } from '../lib/data'
import type { DetectionRow } from '../lib/types'
import { splitCreatorId } from '../lib/projects'
import { parseCreatorList } from '../lib/importList'
import { LOWLANDS_SEED } from '../data/lowlandsSeed'
import { fmtNum, compactNum, timeAgo } from '../lib/format'
import { useCampaignPreview, useCampaignDetectionsPreview } from '../lib/devPreview'

type Filter = 'all' | 'stelz' | 'near' | 'none' | 'pending'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'Alles' },
  { id: 'stelz', label: 'Met Stëlz' },
  { id: 'near', label: 'Mogelijk Stëlz' },
  { id: 'none', label: 'Zonder Stëlz' },
  { id: 'pending', label: 'Niet geanalyseerd' },
]

const VERDICT_TONE: Record<StoryVerdict, string> = {
  visible: 'bg-[var(--color-good)] text-white',
  small: 'bg-[var(--color-warn)] text-white',
  near: 'bg-[var(--color-accent)] text-white',
  absent: 'bg-[var(--color-ink)]/70 text-white',
  unanalysed: 'bg-[var(--color-ink-subtle)] text-white',
  rejected: 'bg-[var(--color-bad)] text-white',
}

export default function Campaign() {
  const [params, setParams] = useSearchParams()
  const filter = (params.get('f') as Filter) || 'all'
  const creator = params.get('c')
  const surface = params.get('s') as Surface | null

  const [profiles, setProfiles] = useState<Record<string, CreatorProfile>>({})
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<CampaignRow | null>(null)

  const previewItems = useCampaignPreview()
  const previewDetections = useCampaignDetectionsPreview()

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const [pr, pj] = await Promise.all([
        fbFetchCreatorProfiles().catch(() => ({} as Record<string, CreatorProfile>)),
        fetchProjects().catch(() => [] as Project[]),
      ])
      if (cancelled) return
      setProfiles(pr)
      setProjects(pj)
      setLoading(false)
    })()
    return () => { cancelled = true }
  }, [])

  const project = projects.find((p) => p.id === params.get('p')) ?? projects[0] ?? null
  // The roster is what makes "who delivered nothing" answerable, and it is the
  // most useful column on the page. Falling back to the committed seed keeps it
  // working when no project has loaded — which is every visit on localhost,
  // where fetchProjects needs an authenticated Firestore. INSTAGRAM handles
  // only: the fixture already resolves TikTok accounts to the same person, so
  // adding the TikTok ids here would list everyone twice.
  const roster = useMemo(() => {
    if (project) return project.creatorIds.map((cid) => splitCreatorId(cid).handle.toLowerCase())
    return [...new Set(
      parseCreatorList(LOWLANDS_SEED).creatorIds
        .filter((cid) => cid.startsWith('instagram_'))
        .map((cid) => splitCreatorId(cid).handle.toLowerCase()),
    )]
  }, [project])

  // Preview-only for now, and deliberately not faked from a partial live
  // source. The three surfaces live in the posts collection, and the only
  // fetcher that exists reads `contentType == 'story'` (fbFetchStoryPosts) —
  // so a "live" version today would show stories and silently claim TikTok and
  // feed posts were empty, which is the exact failure this page is meant to
  // cure. Wiring it up needs one server-side fetch (posts, all content types)
  // and nothing else; until scan_creators is deployed there is nothing to read.
  const rows = useMemo(
    () => joinCampaign(previewItems ?? ([] as CampaignItem[]),
                       previewDetections ?? ([] as DetectionRow[])),
    [previewItems, previewDetections],
  )
  const rollup = useMemo(() => campaignRollup(rows, profiles, roster), [rows, profiles, roster])

  const shown = useMemo(() => {
    let out = rows
    if (creator) out = out.filter((r) => r.creatorHandle === creator)
    if (surface) out = out.filter((r) => r.surface === surface)
    if (filter === 'stelz') out = out.filter((r) => isStelzStory(r.verdict))
    if (filter === 'near') out = out.filter((r) => r.verdict === 'near')
    if (filter === 'none') out = out.filter((r) => r.verdict === 'absent')
    if (filter === 'pending') out = out.filter((r) => r.verdict === 'unanalysed')
    return [...out].sort((a, b) => (b.postedAt ?? '').localeCompare(a.postedAt ?? ''))
  }, [rows, filter, creator, surface])

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  const share = stelzShare(rollup)

  return (
    <PageShell
      title="Campagne"
      subtitle={project ? project.name : 'Instagram en TikTok naast elkaar'}
      crumbs={[{ label: 'Overzicht', to: '/' }]}
    >
      {previewItems && (
        <Card className="mb-6 px-4 py-2.5 text-[12px] text-[var(--color-warn)]">
          Preview: echt gescrapte content uit een lokaal bestand, niet uit de database.
          De oordelen komen uit een lokale analyse met hetzelfde model en dezelfde
          referentiefoto's als productie.
        </Card>
      )}

      {loading && rows.length === 0 ? (
        <Card className="p-14 text-center text-[13px] text-[var(--color-ink-subtle)]">Laden…</Card>
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
            <Kpi
              label="Creators geleverd"
              value={rollup.rosterSize > 0
                ? `${fmtNum(rollup.delivered)}/${fmtNum(rollup.rosterSize)}`
                : fmtNum(rollup.delivered)}
              sub={rollup.silent > 0
                ? `${rollup.silent} plaatste${rollup.silent === 1 ? '' : 'n'} niets`
                : 'iedereen plaatste iets'}
            />
            <Kpi
              label="Geanalyseerd"
              value={`${fmtNum(rollup.judged)}/${fmtNum(rollup.items)}`}
              sub={`${fmtNum(rollup.imagesSeen)} beelden bekeken`}
            />
            <Kpi
              label="Stëlz zichtbaar"
              value={share == null ? '—' : `${Math.round(share)}%`}
              sub={share == null ? 'nog niets beoordeeld'
                : `${fmtNum(rollup.withStelz)} van ${fmtNum(rollup.judged)}`}
            />
            <Kpi
              label="Mogelijk Stëlz"
              value={fmtNum(rollup.near)}
              sub={rollup.near > 0 ? 'afgekeurd bij tweede controle' : 'geen twijfelgevallen'}
            />
            {/* Named for what it is. This is the only published viewing figure
                in the whole product, and it belongs to ONE surface. */}
            <Kpi
              label="TikTok-weergaven"
              value={rollup.tiktokViews > 0 ? compactNum(rollup.tiktokViews) : '—'}
              sub={rollup.bySurface.tiktok.items > 0
                ? `over ${fmtNum(rollup.bySurface.tiktok.items)} video's`
                : 'geen TikToks'}
            />
          </div>

          <Card className="mb-6 px-4 py-3 text-[12px] text-[var(--color-ink-muted)] leading-relaxed">
            <strong className="font-medium text-[var(--color-ink)]">Over deze cijfers.</strong>{' '}
            De drie oppervlakken publiceren verschillende dingen, dus ze worden hier nooit bij
            elkaar opgeteld. <strong>TikTok</strong> geeft echte weergaven —
            {rollup.tiktokViews > 0 ? ` ${fmtNum(rollup.tiktokViews)} in totaal` : ' nog geen'}.
            <strong> Instagram-stories</strong> geven aan niemand behalve de accounthouder een
            kijkcijfer; poll-stemmen
            {rollup.pollVotes > 0 ? ` (${fmtNum(rollup.pollVotes)})` : ''} zijn de enige harde
            ondergrens. <strong>Instagram-posts</strong> geven likes
            {rollup.postLikes > 0 ? ` (${fmtNum(rollup.postLikes)})` : ''}, en alleen reels een
            afspeelteller. Eén opgeteld "bereik" zou geen van deze dingen betekenen.
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {SURFACES.map((s) => (
              <SurfaceCard
                key={s}
                surface={s}
                stats={rollup.bySurface[s]}
                active={surface === s}
                onPick={() => setParam('s', surface === s ? null : s)}
              />
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2 mb-4">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                onClick={() => setParam('f', f.id === 'all' ? null : f.id)}
                className={`text-[12px] px-3 py-1.5 border transition-colors ${
                  filter === f.id
                    ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white'
                    : 'border-[var(--color-border)] text-[var(--color-ink-muted)] hover:border-[var(--color-border-strong)]'
                }`}
              >
                {f.label}
                {f.id === 'stelz' && rollup.withStelz > 0 && ` · ${rollup.withStelz}`}
                {f.id === 'near' && rollup.near > 0 && ` · ${rollup.near}`}
                {f.id === 'pending' && rollup.unanalysed > 0 && ` · ${rollup.unanalysed}`}
              </button>
            ))}
            {creator && (
              <button
                onClick={() => setParam('c', null)}
                className="text-[12px] px-3 py-1.5 border border-[var(--color-accent)] text-[var(--color-accent)]"
              >@{creator} ✕</button>
            )}
            {surface && (
              <button
                onClick={() => setParam('s', null)}
                className="text-[12px] px-3 py-1.5 border border-[var(--color-accent)] text-[var(--color-accent)]"
              >{SURFACE_LABEL[surface]} ✕</button>
            )}
            <span className="ml-auto text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
              {fmtNum(shown.length)} van {fmtNum(rollup.items)}
            </span>
          </div>

          {shown.length === 0 ? (
            <Card className="p-10 text-center text-[13px] text-[var(--color-ink-muted)]">
              Niets in deze selectie.
            </Card>
          ) : (
            <div className="flex flex-wrap gap-2 mb-8">
              {shown.slice(0, 240).map((r) => (
                <ContentCard key={`${r.surface}_${r.itemId}`} row={r} onOpen={() => setOpen(r)} />
              ))}
            </div>
          )}
          {shown.length > 240 && (
            <Card className="mb-8 px-4 py-2.5 text-[12px] text-[var(--color-warn)]">
              De eerste 240 van {fmtNum(shown.length)} worden getoond. Filter op creator of
              oppervlak om de rest te zien — niets is weggegooid, alleen niet getekend.
            </Card>
          )}

          <CreatorTable rollup={rollup} onPick={(h) => setParam('c', h === creator ? null : h)} />
        </>
      )}

      <StoryDetail
        row={open ? { ...open, surfaceLabel: SURFACE_LABEL[open.surface] } : null}
        onClose={() => setOpen(null)}
      />
    </PageShell>
  )
}

function SurfaceCard({ surface, stats, active, onPick }: {
  surface: Surface
  stats: { items: number; judged: number; withStelz: number; near: number; metric: number | null; coverOnly: number }
  active: boolean
  onPick: () => void
}) {
  return (
    <Card className={`p-5 cursor-pointer transition-colors ${
      active ? 'border-[var(--color-ink)]' : ''
    }`}>
      <button onClick={onPick} className="text-left w-full">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">
          {SURFACE_LABEL[surface]}
        </div>
        <div className="stelz-display text-[26px] leading-none text-[var(--color-ink)] mb-1.5">
          {fmtNum(stats.items)}
        </div>
        <div className="text-[12px] text-[var(--color-ink-muted)] space-y-0.5">
          <div>
            {stats.withStelz > 0
              ? <span className="text-[var(--color-good)]">{fmtNum(stats.withStelz)}× Stëlz</span>
              : <span>geen Stëlz</span>}
            {stats.near > 0 && <span className="text-[var(--color-accent)]"> · {stats.near}× mogelijk</span>}
          </div>
          <div className="text-[var(--color-ink-subtle)]">
            {stats.metric != null
              ? `${compactNum(stats.metric)} ${SURFACE_METRIC[surface]}`
              : `geen ${SURFACE_METRIC[surface]}`}
          </div>
          {stats.coverOnly > 0 && (
            <div className="text-[var(--color-warn)]">
              {fmtNum(stats.coverOnly)}× alleen de cover beoordeeld
            </div>
          )}
        </div>
      </button>
    </Card>
  )
}

function ContentCard({ row, onOpen }: { row: CampaignRow; onOpen: () => void }) {
  const metric = metricFor(row)
  return (
    <button
      type="button"
      onClick={onOpen}
      title={`@${row.creatorHandle} · ${SURFACE_LABEL[row.surface]} · ${VERDICT_LABEL[row.verdict]}`}
      className={`shrink-0 w-[112px] block border text-left transition-colors ${
        isStelzStory(row.verdict)
          ? 'border-[var(--color-good)] hover:border-[var(--color-ink)]'
          : row.verdict === 'near'
            ? 'border-[var(--color-accent)] hover:border-[var(--color-ink)]'
            : 'border-[var(--color-border)] hover:border-[var(--color-border-strong)]'
      }`}
    >
      <MediaTile
        src={row.detection?.stored_path || row.detection?.image_url || row.coverUrl}
        size="story"
        alt={`${SURFACE_LABEL[row.surface]} van @${row.creatorHandle}`}
      >
        <span className={`absolute top-1 left-1 text-[9px] uppercase tracking-wider px-1.5 py-0.5 ${VERDICT_TONE[row.verdict]}`}>
          {row.verdict === 'visible' ? 'Stëlz'
            : row.verdict === 'small' ? 'Stëlz klein'
            : row.verdict === 'near' ? 'Mogelijk' : VERDICT_LABEL[row.verdict]}
        </span>
        <span className="absolute top-1 right-1 text-[9px] px-1 py-0.5 bg-[var(--color-ink)]/70 text-white">
          {row.surface === 'tiktok' ? 'TT' : row.surface === 'story' ? 'ST' : 'IG'}
        </span>
        {row.framesJudged > 1 && (
          <span className="absolute bottom-1 left-1 text-[9px] px-1 py-0.5 bg-[var(--color-ink)]/70 text-white tabular-nums">
            {row.framesJudged} beelden
          </span>
        )}
      </MediaTile>
      <span className="block px-1.5 pt-1 text-[10px] truncate text-[var(--color-ink)]">
        @{row.creatorHandle}
      </span>
      <span className="block px-1.5 pb-1 text-[9px] text-[var(--color-ink-subtle)] truncate">
        {metric != null ? `${compactNum(metric)} ${row.surface === 'tiktok' ? 'views' : row.surface === 'post' ? 'likes' : 'stemmen'}` : '—'}
      </span>
    </button>
  )
}

function CreatorTable({ rollup, onPick }: {
  rollup: ReturnType<typeof campaignRollup>
  onPick: (handle: string) => void
}) {
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-[12px] min-w-[760px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] border-b border-[var(--color-border)]">
            <th className="text-left font-normal px-4 py-2.5">Creator</th>
            <th className="text-right font-normal px-3 py-2.5">IG stories</th>
            <th className="text-right font-normal px-3 py-2.5">IG posts</th>
            <th className="text-right font-normal px-3 py-2.5">TikToks</th>
            <th className="text-right font-normal px-3 py-2.5">Met Stëlz</th>
            <th className="text-right font-normal px-3 py-2.5">Mogelijk</th>
            <th className="text-right font-normal px-3 py-2.5">TikTok-views</th>
            <th className="text-right font-normal px-4 py-2.5">Laatste post</th>
          </tr>
        </thead>
        <tbody>
          {rollup.creators.map((c) => {
            const last = SURFACES
              .map((s) => c.bySurface[s].lastPostedAt)
              .filter(Boolean)
              .sort()
              .pop()
            return (
              <tr
                key={c.handle}
                onClick={() => !c.silent && onPick(c.handle)}
                className={`border-b border-[var(--color-border)] last:border-0 ${
                  c.silent ? 'text-[var(--color-ink-subtle)]' : 'cursor-pointer hover:bg-[var(--color-bg)]'
                }`}
              >
                <td className="px-4 py-2.5">
                  <Link to={`/creators/${c.handle}`} className="hover:underline"
                    onClick={(e) => e.stopPropagation()}>@{c.handle}</Link>
                  {c.fullName && <span className="text-[var(--color-ink-subtle)]"> · {c.fullName}</span>}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">{c.bySurface.story.items || '—'}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{c.bySurface.post.items || '—'}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">{c.bySurface.tiktok.items || '—'}</td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {c.withStelz > 0 ? <Badge tone="good">{c.withStelz}</Badge> : '—'}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {c.near > 0 ? <Badge tone="accent">{c.near}</Badge> : '—'}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {c.bySurface.tiktok.metric ? compactNum(c.bySurface.tiktok.metric) : '—'}
                </td>
                <td className="px-4 py-2.5 text-right text-[var(--color-ink-subtle)]">
                  {last ? timeAgo(last) : 'niets geplaatst'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}

function EmptyState() {
  return (
    <Card className="p-12 text-center">
      <p className="text-[13px] text-[var(--color-ink-muted)] mb-2">Nog geen campagnedata.</p>
      <p className="text-[12px] text-[var(--color-ink-subtle)] max-w-[520px] mx-auto leading-relaxed">
        Deze pagina toont Instagram-stories, Instagram-posts en TikToks naast elkaar. Zolang de
        scans niet zijn uitgerold, wordt hij gevuld met{' '}
        <code className="text-[11px]">72_campaign_fixture.py</code> en{' '}
        <code className="text-[11px]">?preview=campaign</code>.
      </p>
    </Card>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-1.5">{label}</div>
      <div className="stelz-display text-[26px] leading-none text-[var(--color-ink)]">{value}</div>
      {sub && <div className="text-[11px] text-[var(--color-ink-subtle)] mt-1.5">{sub}</div>}
    </Card>
  )
}
