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
  SURFACE_LABEL, SURFACE_METRIC, SURFACES, SOURCE_LABEL,
  type CampaignRow, type Surface, type CampaignItem, type Source,
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
type Sort = 'recent' | 'stelz'
type SourceTab = 'all' | Source

const SOURCE_TABS: { id: SourceTab; label: string; sub: string }[] = [
  { id: 'all', label: 'Alles', sub: 'roster en los gevonden' },
  { id: 'roster', label: 'Roster', sub: 'de creators die Stëlz betaalt' },
  { id: 'discovery', label: 'Los gevonden', sub: 'iedereen daarbuiten' },
]

// Newest first is the default because this is a LIVE campaign: the thing worth
// seeing on opening the page is what went up in the last few hours, not the
// best hit from three weeks ago. The order used to be newest-first too, but
// implicitly and with no date anywhere on a tile — so there was no way to tell
// whether the page was sorted at all.
const SORTS: { id: Sort; label: string }[] = [
  { id: 'recent', label: 'Nieuwste eerst' },
  { id: 'stelz', label: 'Stëlz eerst' },
]

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

// Shown instead of the plain "Stëlz" tag when the wordmark was not on a can.
// Short enough for a 112px tile; the drawer spells it out.
const PLACEMENT_TAG: Record<string, string> = {
  signage: 'Stëlz bord',
  merchandise: 'Stëlz merch',
  clothing: 'Stëlz kleding',
  other: 'Stëlz',
}

export default function Campaign() {
  const [params, setParams] = useSearchParams()
  const filter = (params.get('f') as Filter) || 'all'
  const creator = params.get('c')
  const surface = params.get('s') as Surface | null
  const sort = (params.get('sort') as Sort) || 'recent'
  const sourceTab = (params.get('bron') as SourceTab) || 'all'

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
  // TWO ROLLUPS, on purpose. `rollup` is the whole page and is what the source
  // tabs count themselves from — a tab that reported only its own half could
  // never show you the other. `scoped` follows the selected tab and is what the
  // KPI row reads, so clicking "Los gevonden" changes the numbers above the
  // grid instead of leaving them at a page total that contradicts what is
  // shown underneath.
  const rollup = useMemo(() => campaignRollup(rows, profiles, roster), [rows, profiles, roster])
  const scoped = useMemo(() => {
    if (sourceTab === 'all') return rollup
    // Roster stays roster-scoped so "wie leverde er niets" keeps its meaning;
    // discovery has no roster, and passing one would invent 28 silent members
    // for a set nobody booked.
    return campaignRollup(rows.filter((r) => r.source === sourceTab), profiles,
                          sourceTab === 'roster' ? roster : [])
  }, [rows, profiles, roster, rollup, sourceTab])

  // WHY DISCOVERY CONTENT IS FILTERED BEFORE ANYTHING ELSE SEES IT.
  //
  // A roster item with no Stëlz in it is a finding: someone we are paying
  // posted, and the can was not there. A discovery item with no Stëlz is not a
  // finding at all — it is a stranger's festival video that a hashtag happened
  // to return, and there are hundreds of them. Showing those would bury the
  // handful that matter and make the page look like a firehose.
  //
  // So they never reach the grid. The COUNT does reach the screen, in the
  // discovery panel: "4 van 287 bekeken" is the honest form, and dropping the
  // denominator along with the tiles would turn a 1.4% hit rate into an
  // unqualified "4 sightings".
  const discoveryJudged = useMemo(
    () => rows.filter((r) => r.source === 'discovery' && r.verdict !== 'unanalysed').length,
    [rows])
  const worthShowing = useMemo(
    () => rows.filter((r) => r.source === 'roster'
      || isStelzStory(r.verdict) || r.verdict === 'near'),
    [rows])

  const shown = useMemo(() => {
    let out = worthShowing
    if (sourceTab !== 'all') out = out.filter((r) => r.source === sourceTab)
    if (creator) out = out.filter((r) => r.creatorHandle === creator)
    if (surface) out = out.filter((r) => r.surface === surface)
    if (filter === 'stelz') out = out.filter((r) => isStelzStory(r.verdict))
    if (filter === 'near') out = out.filter((r) => r.verdict === 'near')
    if (filter === 'none') out = out.filter((r) => r.verdict === 'absent')
    if (filter === 'pending') out = out.filter((r) => r.verdict === 'unanalysed')
    const byRecent = (a: CampaignRow, b: CampaignRow) =>
      (b.postedAt ?? '').localeCompare(a.postedAt ?? '')
    // Confirmed first, then the ones the detector argued about, then the rest —
    // and inside each band still newest first, so "Stëlz eerst" never hides
    // today's hit behind last year's.
    const rank = (r: CampaignRow) => (isStelzStory(r.verdict) ? 0 : r.verdict === 'near' ? 1 : 2)
    return [...out].sort((a, b) =>
      sort === 'stelz' ? (rank(a) - rank(b)) || byRecent(a, b) : byRecent(a, b))
  }, [worthShowing, filter, creator, surface, sort, sourceTab])

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  const share = stelzShare(scoped)

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
            {/* Discovery has no roster, so "geleverd" is meaningless there —
                nobody agreed to post. The honest figure for that half is how
                many DIFFERENT accounts it came from: one enthusiast posting
                nine times and nine strangers posting once are the same total
                and completely different news. */}
            {sourceTab === 'discovery' ? (
              <Kpi
                label="Accounts"
                value={fmtNum(rollup.bySource.discovery.accounts)}
                sub="buiten de roster, niets afgesproken"
              />
            ) : (
              <Kpi
                label="Creators geleverd"
                value={scoped.rosterSize > 0
                  ? `${fmtNum(scoped.delivered)}/${fmtNum(scoped.rosterSize)}`
                  : fmtNum(scoped.delivered)}
                sub={scoped.silent > 0
                  ? `${scoped.silent} plaatste${scoped.silent === 1 ? '' : 'n'} niets`
                  : 'iedereen plaatste iets'}
              />
            )}
            <Kpi
              label="Geanalyseerd"
              value={`${fmtNum(scoped.judged)}/${fmtNum(scoped.items)}`}
              sub={`${fmtNum(scoped.imagesSeen)} beelden bekeken`}
            />
            <Kpi
              label="Stëlz zichtbaar"
              value={share == null ? '—' : `${Math.round(share)}%`}
              sub={share == null ? 'nog niets beoordeeld'
                : scoped.offContainer > 0
                  ? `${fmtNum(scoped.withStelz)} van ${fmtNum(scoped.judged)} · ${scoped.offContainer}× niet op een blikje`
                  : `${fmtNum(scoped.withStelz)} van ${fmtNum(scoped.judged)}`}
            />
            <Kpi
              label="Mogelijk Stëlz"
              value={fmtNum(scoped.near)}
              sub={scoped.near > 0 ? 'afgekeurd bij tweede controle' : 'geen twijfelgevallen'}
            />
            {/* Named for what it is. This is the only published viewing figure
                in the whole product, and it belongs to ONE surface. */}
            <Kpi
              label="TikTok-weergaven"
              value={scoped.tiktokViews > 0 ? compactNum(scoped.tiktokViews) : '—'}
              sub={scoped.bySurface.tiktok.items > 0
                ? `over ${fmtNum(scoped.bySurface.tiktok.items)} video's`
                : 'geen TikToks'}
            />
          </div>

          {/* THE SPLIT THE BRAND ACTUALLY NEEDS. Roster content answers "did the
              people we booked deliver"; discovery content answers "is the can
              showing up on its own". Same festival, same week, entirely
              different things to have bought — so they are two tabs and never
              one total. */}
          <div className="flex flex-wrap gap-2 mb-4">
            {SOURCE_TABS.map((t) => {
              const st = t.id === 'all' ? null : rollup.bySource[t.id]
              const active = sourceTab === t.id
              return (
                <button
                  key={t.id}
                  onClick={() => setParam('bron', t.id === 'all' ? null : t.id)}
                  className={`text-left px-3.5 py-2 border transition-colors ${
                    active
                      ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white'
                      : 'border-[var(--color-border)] hover:border-[var(--color-ink)]'
                  }`}
                >
                  <span className="block text-[12px]">
                    {t.label}
                    {st && <span className="tabular-nums"> · {fmtNum(st.withStelz)}× Stëlz</span>}
                  </span>
                  <span className={`block text-[10px] ${
                    active ? 'text-white/70' : 'text-[var(--color-ink-subtle)]'
                  }`}>
                    {st
                      ? `${fmtNum(st.accounts)} account${st.accounts === 1 ? '' : 's'} · ${t.sub}`
                      : t.sub}
                  </span>
                </button>
              )
            })}
          </div>

          {/* The denominator. Discovery tiles without Stëlz are never rendered —
              a stranger's festival video that a hashtag returned is not a
              finding — but the number looked at has to stay on screen, or a
              1% hit rate reads as an unqualified list of sightings. */}
          {rollup.bySource.discovery.items > 0 && (
            <Card className="mb-6 px-4 py-3 text-[12px] text-[var(--color-ink-muted)] leading-relaxed border-l-2 border-[var(--color-accent)]">
              <strong className="font-medium text-[var(--color-ink)]">
                Los gevonden: {fmtNum(rollup.bySource.discovery.withStelz)} met Stëlz
                {discoveryJudged > 0 && ` uit ${fmtNum(discoveryJudged)} bekeken video's`}.
              </strong>{' '}
              Gevonden via hashtags op TikTok, van accounts die niet op de roster staan — dit is
              wat er uit zichzelf gebeurde, los van wat er betaald is. Alleen de beelden waar
              Stëlz daadwerkelijk in staat worden hier getoond; de rest is festivalcontent die
              een hashtag toevallig opleverde en zegt niets over het merk.
              {rollup.bySource.discovery.tiktokViews > 0 && (
                <> Samen {fmtNum(rollup.bySource.discovery.tiktokViews)} weergaven — apart
                gehouden van de {fmtNum(rollup.bySource.roster.tiktokViews)} van de roster,
                omdat betaald bereik en organisch bereik niet hetzelfde getal zijn.</>
              )}
            </Card>
          )}

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

          {/* A gap between this page and the backend that will serve it. Stated
              here rather than left for someone to discover after the deploy,
              when the count silently drops and looks like a scraping problem. */}
          {rollup.missedByDeploy > 0 && (
            <Card className="mb-6 px-4 py-3 text-[12px] text-[var(--color-ink-muted)] leading-relaxed border-l-2 border-[var(--color-warn)]">
              <strong className="font-medium text-[var(--color-ink)]">
                {rollup.missedByDeploy} van deze {fmtNum(rollup.withStelz)} vondsten vindt de
                live backend op dit moment niet.
              </strong>{' '}
              De gepubliceerde functie verkleint elk beeld naar 512 pixels voordat het model
              kijkt. Videoframes komen binnen op de resolutie van de clip zelf, dus een frame
              van 1080×1920 verliest ruim 90% van zijn pixels en een merknaam van 40 pixels
              breed wordt er 19. Deze pagina is geanalyseerd op de archiefresolutie, wat meer
              vindt en meer kost. Beelden waar dat verschil speelt zijn hieronder gemarkeerd;
              de keuze om die grens te verhogen ligt bij wie de Gemini-rekening betaalt.
            </Card>
          )}

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
                {f.id === 'stelz' && scoped.withStelz > 0 && ` · ${scoped.withStelz}`}
                {f.id === 'near' && scoped.near > 0 && ` · ${scoped.near}`}
                {f.id === 'pending' && scoped.unanalysed > 0 && ` · ${scoped.unanalysed}`}
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
            <span className="ml-auto flex items-center gap-2">
              {SORTS.map((o) => (
                <button
                  key={o.id}
                  onClick={() => setParam('sort', o.id === 'recent' ? null : o.id)}
                  className={`text-[11px] px-2.5 py-1 border transition-colors ${
                    sort === o.id
                      ? 'border-[var(--color-ink)] text-[var(--color-ink)]'
                      : 'border-[var(--color-border)] text-[var(--color-ink-subtle)] hover:border-[var(--color-border-strong)]'
                  }`}
                >{o.label}</button>
              ))}
              <span className="text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
                {fmtNum(shown.length)} van {fmtNum(scoped.items)}
              </span>
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

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {SURFACES.map((s) => (
              <SurfaceCard
                key={s}
                surface={s}
                stats={scoped.bySurface[s]}
                active={surface === s}
                onPick={() => setParam('s', surface === s ? null : s)}
              />
            ))}
          </div>

          <CreatorTable rollup={scoped} onPick={(h) => setParam('c', h === creator ? null : h)} />
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
          {/* A logo on a bar front or a cap is a sighting, but not the same
              sighting as a can in someone's hand — the tile says which. */}
          {row.placement ? PLACEMENT_TAG[row.placement]
            : row.verdict === 'visible' ? 'Stëlz'
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
        {row.missedByDeploy && (
          <span
            title="De live backend verkleint dit beeld naar 512px en vindt Stëlz dan niet meer"
            className="absolute bottom-1 right-1 text-[9px] px-1 py-0.5 bg-[var(--color-warn)] text-white"
          >
            niet live
          </span>
        )}
      </MediaTile>
      <span className="block px-1.5 pt-1 text-[10px] truncate text-[var(--color-ink)]">
        @{row.creatorHandle}
      </span>
      <span className="block px-1.5 text-[9px] text-[var(--color-ink)] truncate tabular-nums">
        {row.postedAt ? timeAgo(row.postedAt) : 'datum onbekend'}
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
        <code className="text-[11px]">72_campaign_fixture.py</code>.
      </p>
      {/* Dev server only — folded out of a production build along with the URL
          it names. Typing a query parameter you have to be told about is not a
          way to find a page; on localhost the empty state IS the signpost. */}
      {import.meta.env.DEV && (
        <p className="mt-4">
          <a
            href="/campagne?preview=campaign"
            className="text-[12px] underline hover:text-[var(--color-ink)]"
          >
            Lokale preview openen →
          </a>
        </p>
      )}
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
