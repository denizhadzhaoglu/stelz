// Dedicated Lowlands tab — the client's festival roster, one click from
// anywhere.
//
// Two states, on purpose:
//   1. The roster project exists → this tab IS the roster (redirect to the
//      project page, which renders members including the silent ones).
//   2. It doesn't exist yet → this tab is the import screen, pre-filled with
//      the client's transcribed list so the first import is review-and-click,
//      not copy-paste-and-hope.
//
// The import creates the project at tier_2 (12h cadence): the whole 53-id
// roster fits under the wide tracking cap without touching the expensive
// tier_1 allowance, and two Run-scan clicks a day cover the festival weekend.

import { useCallback, useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { Card, PageShell } from '../components/ui'
import { PasteImport } from '../components/PasteImport'
import { fetchProjects, projectsAction, type Project } from '../lib/data'
import { LOWLANDS_SEED, LOWLANDS_SEED_NAME } from '../data/lowlandsSeed'
import { useMembership } from '../lib/membership'

function findLowlands(projects: Project[]): Project | null {
  // Name-based on purpose: project doc ids derive from the name server-side,
  // so matching the name is the stable contract. Live projects win over
  // archived ones (an archived roster still redirects — the detail page is
  // where Unarchive lives).
  const match = (p: Project) => p.name.toLowerCase().includes('lowlands')
  return projects.find((p) => !p.archived && match(p)) ?? projects.find(match) ?? null
}

export default function LowlandsPage() {
  const { canWrite } = useMembership()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetchProjects().then(setProjects).catch((e) => { setProjects([]); setError((e as Error).message) })
  }, [])
  useEffect(() => { load() }, [load])

  if (projects === null) {
    return (
      <PageShell title="Lowlands">
        <Card className="p-14 text-center text-[13px] text-[var(--color-ink-subtle)]">Loading…</Card>
      </PageShell>
    )
  }

  const existing = findLowlands(projects)
  if (existing) return <Navigate to={`/projects/${existing.id}`} replace />

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

  return (
    <PageShell
      title="Lowlands"
      subtitle="Importeer de creatorlijst van Stelz — daarna is deze tab de roster"
    >
      {error && <Card className="p-4 mb-4 text-[12px] text-[var(--color-bad)]">{error}</Card>}

      {!canWrite ? (
        <Card className="p-10 text-center text-[13px] text-[var(--color-ink-muted)]">
          De Lowlands-lijst is nog niet geïmporteerd. Importeren vereist schrijfrechten —
          vraag een teamlid met toegang, daarna verschijnt de roster hier vanzelf.
        </Card>
      ) : (
        <Card className="p-5 space-y-4">
          <div className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed max-w-2xl">
            De lijst hieronder is overgenomen uit de Stelz-sheet (28 creators, 53 profielen).
            Elke cel is direct aan te passen — klik op een naam of handle om te corrigeren,
            vink rijen uit die niet mee moeten, of voeg rijen toe. Importeren maakt het project
            &ldquo;{LOWLANDS_SEED_NAME}&rdquo; aan op een 12-uurs scancadans: elke Run scan pakt
            due creators mee en alles waar Stëlz in beeld is verschijnt in de feed.
          </div>
          <div className="text-[11px] text-[var(--color-warn)]">
            ⚠ Check rij 3 (Rein van Duivenboden): de TikTok-handle was slecht leesbaar in de
            bron-sheet — vergelijk met de sheet en pas hem hier direct in de tabel aan.
            Een verkeerde handle kost niets, maar levert ook niets op.
          </div>
          <PasteImport
            initialText={LOWLANDS_SEED}
            busy={busy}
            submitLabel={(n) => `Importeer ${n} creators als "${LOWLANDS_SEED_NAME}" (12u)`}
            onImport={doImport}
          />
        </Card>
      )}
    </PageShell>
  )
}
