// Dedicated Lowlands tab — the festival, in the two halves a brand actually
// buys.
//
// WHY THIS PAGE NO LONGER REDIRECTS. It used to send you straight to the roster
// project, on the reasoning that "this tab IS the roster". That was true while
// the roster was the only thing there was to see. It isn't any more: the
// hashtag harvest (73_lowlands_discovery.py) finds Stëlz at the same festival
// from people nobody is paying, and that is a different question with a
// different answer.
//
//   De roster       — did the 28 creators we booked deliver? A CONTRACT question.
//                     Silence from someone being paid is the finding.
//   Los gevonden    — is the can showing up on its own? A MARKETING question.
//                     Here silence means nothing and a single sighting means a lot.
//
// The two are never added together. A stranger's TikTok view is not a
// deliverable, and a total that contains both flatters the campaign with reach
// it did not buy.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Card, PageShell } from '../components/ui'
import { MediaTile } from '../components/MediaTile'
import { PasteImport } from '../components/PasteImport'
import { fetchProjects, projectsAction, type Project } from '../lib/data'
import { LOWLANDS_SEED, LOWLANDS_SEED_NAME } from '../data/lowlandsSeed'
import { useMembership } from '../lib/membership'
import { joinCampaign, campaignRollup, type CampaignItem, type CampaignRow } from '../lib/campaign'
import { isStelzStory } from '../lib/storyStats'
import type { DetectionRow } from '../lib/types'
import { useCampaignPreview, useCampaignDetectionsPreview } from '../lib/devPreview'
import { fmtNum, timeAgo } from '../lib/format'

function findLowlands(projects: Project[]): Project | null {
  // Name-based on purpose: project doc ids derive from the name server-side,
  // so matching the name is the stable contract. Live projects win over
  // archived ones (an archived roster still links — the detail page is where
  // Unarchive lives).
  const match = (p: Project) => p.name.toLowerCase().includes('lowlands')
  return projects.find((p) => !p.archived && match(p)) ?? projects.find(match) ?? null
}

export default function LowlandsPage() {
  const { canWrite } = useMembership()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const previewItems = useCampaignPreview()
  const previewDetections = useCampaignDetectionsPreview()

  const load = useCallback(() => {
    fetchProjects().then(setProjects).catch((e) => { setProjects([]); setError((e as Error).message) })
  }, [])
  useEffect(() => { load() }, [load])

  const rows = useMemo(
    () => joinCampaign(previewItems ?? ([] as CampaignItem[]),
                       previewDetections ?? ([] as DetectionRow[])),
    [previewItems, previewDetections],
  )
  const rollup = useMemo(() => campaignRollup(rows), [rows])

  // Only the sightings. A discovery item without Stëlz is a stranger's festival
  // video that a hashtag returned — the count belongs on screen, the tile does
  // not.
  const found = useMemo(
    () => rows
      .filter((r) => r.source === 'discovery' && (isStelzStory(r.verdict) || r.verdict === 'near'))
      .sort((a, b) => (b.postedAt ?? '').localeCompare(a.postedAt ?? '')),
    [rows],
  )
  const discoveryJudged = rows.filter(
    (r) => r.source === 'discovery' && r.verdict !== 'unanalysed').length

  const doImport = async (creatorIds: string[], names: Record<string, string>) => {
    setBusy(true)
    setError(null)
    try {
      let project: Project
      try {
        project = await projectsAction('create', {
          name: LOWLANDS_SEED_NAME,
          trackingTier: 'tier_2',
          note: 'Lowlands 20–23 aug 2026 — creatorlijst van Stelz',
        })
      } catch (e) {
        // 409 = someone created it in parallel; import into theirs instead of
        // erroring out of the one-click flow.
        const refreshed = await fetchProjects()
        const found = findLowlands(refreshed)
        if (!found) throw e
        project = found
      }
      await projectsAction('addCreators', { projectId: project.id, creatorIds, names })
      navigate(`/projects/${project.id}`, { replace: true })
    } catch (e) {
      // Server messages (cap, deploy-status) explain themselves — verbatim.
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (projects === null) {
    return (
      <PageShell title="Lowlands">
        <Card className="p-14 text-center text-[13px] text-[var(--color-ink-subtle)]">Loading…</Card>
      </PageShell>
    )
  }

  const existing = findLowlands(projects)
  const rosterStats = rollup.bySource.roster

  return (
    <PageShell
      title="Lowlands"
      subtitle="Wat de geboekte creators plaatsten, en wat er los van hen gevonden is"
    >
      {error && <Card className="p-4 mb-4 text-[12px] text-[var(--color-bad)]">{error}</Card>}

      {/* ── 1. The roster ─────────────────────────────────────────── */}
      <Section
        title="De roster"
        lead="De 28 creators die Stëlz voor Lowlands geboekt heeft. Hier is stilte een bevinding:
              wie niets plaatste, heeft niet geleverd."
      >
        {existing ? (
          <div className="space-y-3">
            {rosterStats.items > 0 && (
              <Stat
                lines={[
                  [`${fmtNum(rollup.delivered)}/${fmtNum(rollup.rosterSize)}`, 'creators leverden iets'],
                  [fmtNum(rosterStats.items), 'stuks content'],
                  [fmtNum(rosterStats.withStelz), 'met Stëlz in beeld'],
                ]}
              />
            )}
            <div className="flex flex-wrap gap-2">
              <Link to={`/projects/${existing.id}`} className={LINK}>
                Open de roster ({existing.creatorIds.length} profielen) →
              </Link>
              <Link to="/campagne?bron=roster" className={LINK}>
                Wat ze plaatsten →
              </Link>
            </div>
          </div>
        ) : !canWrite ? (
          <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed">
            De Lowlands-lijst is nog niet geïmporteerd. Importeren vereist schrijfrechten —
            vraag een teamlid met toegang, daarna verschijnt de roster hier vanzelf.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed max-w-2xl">
              De Stelz-lijst staat klaar (28 creators, 53 profielen) — importeer hem direct.
              Aanpassen kan nu (klik op een cel, vink rijen uit, voeg rijen toe) maar ook
              achteraf. Importeren maakt het project &ldquo;{LOWLANDS_SEED_NAME}&rdquo; aan op
              een 12-uurs scancadans: elke Run scan pakt due creators mee en alles waar Stëlz
              in beeld is verschijnt in de feed.
            </div>
            <PasteImport
              initialText={LOWLANDS_SEED}
              busy={busy}
              submitLabel={(n) => `Importeer ${n} creators als "${LOWLANDS_SEED_NAME}" (12u)`}
              onImport={doImport}
            />
          </div>
        )}
      </Section>

      {/* ── 2. Everyone else ──────────────────────────────────────── */}
      <Section
        title="Los gevonden"
        lead="Stëlz op Lowlands van accounts die NIET op de roster staan, gevonden via hashtags.
              Hier betekent stilte niets en betekent één vondst veel: dit is wat er uit zichzelf
              gebeurde."
      >
        {rollup.bySource.discovery.items === 0 ? (
          <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed">
            Nog niets opgehaald. De hashtag-scrape draait los van de roster en kost bij Apify
            niets — de TikTok-actor is gratis. Draai{' '}
            <code className="text-[12px] bg-[var(--color-surface-2)] px-1 py-0.5">
              73_lowlands_discovery.py
            </code>{' '}
            en daarna de analyse; deze sectie vult zich vanzelf.
          </p>
        ) : (
          <div className="space-y-4">
            <Stat
              lines={[
                [fmtNum(rollup.bySource.discovery.withStelz), 'met Stëlz'],
                [fmtNum(discoveryJudged), "video's bekeken"],
                [fmtNum(rollup.bySource.discovery.accounts), 'accounts'],
                ...(rollup.bySource.discovery.tiktokViews > 0
                  ? [[fmtNum(rollup.bySource.discovery.tiktokViews), 'weergaven'] as [string, string]]
                  : []),
              ]}
            />
            <p className="text-[12px] text-[var(--color-ink-subtle)] leading-relaxed max-w-2xl">
              Alleen de beelden waar Stëlz in staat worden getoond. De rest is festivalcontent
              die een hashtag toevallig opleverde en zegt niets over het merk — het aantal
              bekeken video's staat hierboven, zodat de trefkans zichtbaar blijft.
              Deze cijfers worden nooit bij de roster opgeteld: een weergave van een vreemde is
              geen geleverde prestatie.
            </p>
            {found.length > 0 && (
              <div className="flex gap-2 overflow-x-auto pb-1">
                {found.slice(0, 24).map((r) => <FoundTile key={r.itemId} row={r} />)}
              </div>
            )}
            <Link to="/campagne?bron=discovery" className={LINK}>
              Alles bekijken op de campagnepagina →
            </Link>
          </div>
        )}
      </Section>
    </PageShell>
  )
}

const LINK = 'text-[12px] px-3 py-1.5 border border-[var(--color-border)] ' +
  'hover:border-[var(--color-ink)] transition-colors inline-block'

function Section({ title, lead, children }: {
  title: string; lead: string; children: React.ReactNode
}) {
  return (
    <Card className="p-5 mb-4">
      <h2 className="text-[15px] text-[var(--color-ink)] mb-1">{title}</h2>
      <p className="text-[12px] text-[var(--color-ink-subtle)] leading-relaxed max-w-2xl mb-4">
        {lead}
      </p>
      {children}
    </Card>
  )
}

function Stat({ lines }: { lines: [string, string][] }) {
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-3">
      {lines.map(([value, label]) => (
        <div key={label}>
          <div className="text-[20px] text-[var(--color-ink)] tabular-nums leading-none">{value}</div>
          <div className="text-[11px] text-[var(--color-ink-subtle)] mt-1">{label}</div>
        </div>
      ))}
    </div>
  )
}

function FoundTile({ row }: { row: CampaignRow }) {
  const hit = isStelzStory(row.verdict)
  return (
    <a
      href={row.url ?? '#'}
      target="_blank"
      rel="noreferrer"
      title={`@${row.platformHandle ?? row.creatorHandle}${row.foundVia ? ` · via #${row.foundVia}` : ''}`}
      className={`shrink-0 w-[104px] block border transition-colors ${
        hit ? 'border-[var(--color-good)]' : 'border-[var(--color-accent)]'
      } hover:border-[var(--color-ink)]`}
    >
      <MediaTile
        src={row.detection?.image_url || row.coverUrl}
        size="story"
        alt={`Gevonden bij @${row.platformHandle ?? row.creatorHandle}`}
      >
        <span className={`absolute top-1 left-1 text-[9px] uppercase tracking-wider px-1.5 py-0.5 ${
          hit ? 'bg-[var(--color-good)] text-white' : 'bg-[var(--color-accent)] text-white'
        }`}>
          {hit ? 'Stëlz' : 'Mogelijk'}
        </span>
      </MediaTile>
      <span className="block px-1.5 pt-1 text-[10px] truncate text-[var(--color-ink)]">
        @{row.platformHandle ?? row.creatorHandle}
      </span>
      {/* Which hashtag surfaced it. Without this the section is a list of
          strangers with no account of how they were found. */}
      <span className="block px-1.5 text-[9px] truncate text-[var(--color-ink-subtle)]">
        {row.foundVia ? `#${row.foundVia}` : row.postedAt ? timeAgo(row.postedAt) : '—'}
      </span>
    </a>
  )
}
