// Project detail — one tracked group of creators (/projects/:projectId).
//
// The page answers three questions a campaign manager actually has:
// what did this group produce, who in it is delivering, and who is silent.
// Zero-hit members stay visible on purpose: a tracked creator producing
// nothing is information, not a rendering gap.
//
// Writes (remove member, archive) go through api_projects — server-gated,
// because project membership changes scan cadence, which is spend. The UI
// hides those controls for read-only users rather than teasing a 403.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageShell, Card, Badge, Button, Avatar } from '../components/ui'
import { StackedDayBars, bucketByDay, type Series } from '../components/Chart'
import { PasteImport } from '../components/PasteImport'
import { dedupeByPost, type DetectionRow } from '../lib/types'
import { fetchDetections, fetchProjects, projectsAction, fetchCreatorProfiles, type Project } from '../lib/data'
import { fbStepCreators, type CreatorProfile } from '../lib/firestore'
import { rollupProject, splitCreatorId } from '../lib/projects'
import { useMembership } from '../lib/membership'

export default function ProjectPage() {
  const { projectId = '' } = useParams()
  const { canWrite } = useMembership()

  const [project, setProject] = useState<Project | null>(null)
  const [rows, setRows] = useState<DetectionRow[]>([])
  const [profiles, setProfiles] = useState<Record<string, CreatorProfile>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // Profiles ride along for display names + fresh follower counts —
      // imported roster members have a fullName long before their first hit.
      const [all, profs] = await Promise.all([
        fetchProjects(),
        fetchCreatorProfiles().catch(() => ({} as Record<string, CreatorProfile>)),
      ])
      setProfiles(profs)
      const p = all.find((x) => x.id === projectId) ?? null
      setProject(p)
      if (p && p.creatorIds.length) {
        // One query per member via the existing creatorHandle index — same
        // pattern as Creator.tsx, bounded by the member cap (25 server-side).
        const batches = await Promise.all(
          p.creatorIds.map((cid) =>
            fetchDetections({ creatorHandle: splitCreatorId(cid).handle, limit: 300 }).catch(() => []),
          ),
        )
        // Moderator-rejected rows are excluded, matching every other surface.
        setRows(dedupeByPost(batches.flat()).filter((r) => r.is_false_positive !== true))
      } else {
        setRows([])
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => { void load() }, [load])

  const rollup = useMemo(
    () => (project ? rollupProject(project, rows) : null),
    [project, rows],
  )

  const act = async (
    action: 'addCreators' | 'removeCreators' | 'archive' | 'unarchive',
    params: { creatorIds?: string[]; names?: Record<string, string> },
  ) => {
    if (!project) return
    setBusy(true)
    setError(null)
    try {
      const updated = await projectsAction(action, { projectId: project.id, ...params })
      setProject(updated)
      if (action === 'addCreators') {
        // New members need their profiles/rows fetched to render properly.
        setShowImport(false)
        void load()
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const scanNow = async () => {
    setBusy(true)
    setScanMsg(null)
    setError(null)
    try {
      // Honest scope: this steps the GLOBAL creator scan — every due tracked
      // creator, not just this project's. That is also why the button lives
      // here and not per-member.
      const out = await fbStepCreators(80, 8) as {
        creators_scanned?: number; posts_added?: number; skipped?: string
      }
      setScanMsg(out.skipped
        ? `Scan overgeslagen (${out.skipped}) — budgetlimiet bereikt voor vandaag.`
        : `Scan klaar: ${out.creators_scanned ?? 0} creators gescand, ${out.posts_added ?? 0} posts opgehaald. Detecties verschijnen binnen enkele minuten in de feed.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <PageShell title="Project"><Card className="p-14 text-center text-[13px] text-[var(--color-ink-subtle)]">Loading…</Card></PageShell>
  }
  if (!project) {
    return (
      <PageShell title="Project">
        <Card className="p-14 text-center text-[13px] text-[var(--color-ink-muted)]">
          Project not found. <Link to="/" className="underline">Back to the dashboard</Link>
        </Card>
      </PageShell>
    )
  }

  const trend: Series = { id: 'hits', label: 'Hits', tone: 'accent', data: bucketByDay(rollup?.postedAts ?? [], 60) }
  const r = rollup!
  const scored = r.hits - r.sentiment.unscored
  // Roster order: by display name where known (imports carry fullName), so the
  // list reads like the client's sheet instead of raw handle soup.
  const members = [...r.creators].sort((a, b) =>
    (profiles[a.handle]?.fullName ?? a.handle).localeCompare(profiles[b.handle]?.fullName ?? b.handle, 'nl'),
  )

  return (
    <PageShell
      title={project.name}
      subtitle={`${project.creatorIds.length} tracked creators at ${project.trackingTier === 'tier_1' ? '6h' : '12h'} scan cadence${project.note ? ` · ${project.note}` : ''}${project.archived ? ' · ARCHIVED' : ''}`}
      actions={
        <div className="flex items-center gap-3">
          {canWrite && !project.archived && (
            <Button
              size="sm" variant="secondary" disabled={busy}
              title="Scant álle due creators (niet alleen dit project) en haalt hun recente posts op"
              onClick={() => void scanNow()}
            >
              Scan creators nu
            </Button>
          )}
          {canWrite && !project.archived && (
            <Button
              size="sm" variant="ghost" disabled={busy}
              onClick={() => {
                // Archiving stops the fast cadence for every member not claimed
                // by another project — that is its point. Say so before doing it.
                if (window.confirm('Archive this project? Its creators return to the normal scan cadence unless another project tracks them.')) {
                  void act('archive', {})
                }
              }}
            >
              Archive
            </Button>
          )}
          {canWrite && project.archived && (
            // Reviving re-claims the members' fast cadence; the server re-checks
            // the tracking cap and refuses with a clear message when full.
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act('unarchive', {})}>
              Unarchive
            </Button>
          )}
          <Link to="/" className="text-[12px] underline text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]">← Dashboard</Link>
        </div>
      }
    >
      {error && <Card className="p-4 mb-4 text-[12px] text-[var(--color-bad)]">{error}</Card>}
      {scanMsg && <Card className="p-4 mb-4 text-[12px] text-[var(--color-ink-muted)]">{scanMsg}</Card>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Kpi label="Hits" value={String(r.hits)} />
        <Kpi label="Members" value={String(project.creatorIds.length)} />
        <Kpi
          label="Reach"
          value={r.reach > 0 ? r.reach.toLocaleString() : '—'}
          sub={r.reachKnownFor > 0 ? `followers known for ${r.reachKnownFor} of ${project.creatorIds.length}` : 'no follower counts yet — run a profile refresh'}
        />
        <Kpi
          label="Positive share"
          value={scored > 0 ? `${Math.round((r.sentiment.positive / scored) * 100)}%` : '—'}
          sub={scored > 0 ? `of ${scored} scored` : 'nothing scored yet'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-5">
          <h3 className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Hits over time</h3>
          <StackedDayBars series={[trend]} height={180} days={60} />
        </Card>

        <Card className="p-5">
          <h3 className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">
            Members — including the silent ones
          </h3>
          <ul className="divide-y divide-[var(--color-border)]">
            {members.map((c) => {
              const prof = profiles[c.handle]
              const displayName = prof?.fullName ?? null
              const followers = prof?.followerCount ?? c.followers
              return (
              <li key={c.creatorId} className="flex items-center gap-3 py-2.5">
                <Avatar src={prof?.avatarUrl ?? c.avatar} handle={c.handle} className="w-8 h-8 rounded-full text-[12px] shrink-0" />
                <Link to={`/creators/${c.handle}`} className="min-w-0 flex-1 hover:underline">
                  <span className="block text-[13px] font-medium truncate">{displayName ?? `@${c.handle}`}</span>
                  <span className="block text-[11px] text-[var(--color-ink-subtle)]">
                    {displayName ? `@${c.handle} · ` : ''}{c.platform}
                    {followers ? ` · ${followers.toLocaleString()} followers` : ''}
                    {c.lastHitAt ? ` · last hit ${new Date(c.lastHitAt).toLocaleDateString('nl-NL')}` : ''}
                  </span>
                </Link>
                {c.hits === 0 ? (
                  <Badge tone="muted">no hits yet</Badge>
                ) : (
                  <Badge tone="accent">{c.hits} {c.hits === 1 ? 'hit' : 'hits'}</Badge>
                )}
                {canWrite && !project.archived && (
                  <button
                    disabled={busy}
                    onClick={() => void act('removeCreators', { creatorIds: [c.creatorId] })}
                    title="Remove from project — returns to normal scan cadence unless tracked elsewhere"
                    className="text-[11px] text-[var(--color-ink-subtle)] hover:text-[var(--color-bad)] shrink-0 disabled:opacity-40"
                  >
                    ✕
                  </button>
                )}
              </li>
              )
            })}
          </ul>
          {project.creatorIds.length === 0 && (
            <p className="text-[12px] text-[var(--color-ink-muted)] py-6 text-center">
              No creators yet. Add them from the Creators tab or a detection's detail panel.
            </p>
          )}
        </Card>
      </div>

      {canWrite && !project.archived && (
        <Card className="p-5 mt-6">
          <button
            onClick={() => setShowImport((v) => !v)}
            className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)]"
          >
            Lijst importeren — plak uit een sheet {showImport ? '▴' : '▾'}
          </button>
          {showImport && (
            <div className="mt-4">
              <PasteImport
                busy={busy}
                submitLabel={(n) => `Voeg ${n} creators toe aan ${project.name}`}
                onImport={(ids, names) => void act('addCreators', { creatorIds: ids, names })}
              />
            </div>
          )}
        </Card>
      )}
    </PageShell>
  )
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)]">{label}</div>
      <div className="text-[22px] font-medium tabular-nums mt-1">{value}</div>
      {sub && <div className="text-[11px] text-[var(--color-ink-subtle)] mt-0.5">{sub}</div>}
    </Card>
  )
}
