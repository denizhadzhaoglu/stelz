// Scan progress, derived — pure so it can be tested without a browser.
//
// A scan runs seven steps and then spends most of its wall-clock time in a
// detect fan-out that is not a step at all. The old UI showed one 16x2 pixel
// bar for the first step only; the other five ran fire-and-forget and a failure
// in any of them vanished silently.
//
// Everything here degrades: a backend that has not deployed the steps map yet
// yields the same shape from the flat counters, so the panel is never blank.

import type { ScanState, ScanStepKey } from './firestore'

export type StepState = 'pending' | 'running' | 'done' | 'error' | 'skipped'
export type ScanPhase = 'idle' | 'scraping' | 'analysing' | 'done' | 'stalled' | 'error'

/** The derived pseudo-step: where nearly all the time actually goes. */
export const ANALYSIS_KEY = 'analysis' as const
export type StepId = ScanStepKey | typeof ANALYSIS_KEY

export type StepView = {
  key: StepId
  label: string
  state: StepState
  detail: string | null
  error: string | null
}

/** Display order. Analysis sits after the two scrape steps that feed it. */
export const STEP_ORDER: { key: StepId; label: string }[] = [
  { key: 'hashtags', label: 'Hashtags scrapen' },
  { key: 'stories', label: 'Stories ophalen' },
  { key: 'creators', label: 'Creators scrapen' },
  { key: ANALYSIS_KEY, label: 'Beelden analyseren' },
  { key: 'profiles', label: 'Profielen verversen' },
  { key: 'subcultures', label: 'Scenes indelen' },
  { key: 'srs', label: 'Resonantie berekenen' },
  { key: 'sentiment', label: 'Sentiment scoren' },
]

/** No worker has written for this long → treat the session as dead. */
export const STALL_MS = 5 * 60_000

/** Too few completions to extrapolate from; an ETA here swings wildly. */
const ETA_MIN_SAMPLES = 20

export function analysisProgress(s: ScanState | null, now = Date.now()):
  { done: number; total: number; pct: number; etaMs: number | null } | null {
  if (!s) return null
  const total = s.detectTasksEnqueued ?? 0
  if (total <= 0) return null
  const done = Math.min(s.detectionsCompleted ?? 0, total)
  const pct = Math.round((done / total) * 100)
  let etaMs: number | null = null
  if (done >= ETA_MIN_SAMPLES && done < total && s.startedAt) {
    const elapsed = now - new Date(s.startedAt).getTime()
    if (elapsed > 0) etaMs = Math.round((elapsed / done) * (total - done))
  }
  return { done, total, pct, etaMs }
}

function isStale(s: ScanState, now: number): boolean {
  if (!s.startedAt || s.finishedAt) return false
  const last = s.lastActivityAt ? new Date(s.lastActivityAt).getTime() : 0
  return last > 0 && now - last > STALL_MS
}

export function scanPhase(s: ScanState | null, now = Date.now()): ScanPhase {
  if (!s || !s.startedAt) return 'idle'
  const steps = s.steps ?? {}
  const anyRunning = Object.values(steps).some((st) => st?.state === 'running')
  const anyError = Object.values(steps).some((st) => st?.state === 'error')
  const analysis = analysisProgress(s, now)
  const analysing = analysis != null && analysis.done < analysis.total

  if (isStale(s, now) && !analysing) return 'stalled'
  if (anyRunning) return 'scraping'
  if (analysing) return 'analysing'
  // An error only becomes the headline once nothing is still running — a failed
  // enrichment step must not hide the fact that detection is still working.
  if (anyError) return 'error'
  // Without a steps map, fall back to the flat pair the old pill used.
  if (!s.finishedAt) return 'scraping'
  return 'done'
}

export function stepViews(
  s: ScanState | null,
  clientErrors: Partial<Record<ScanStepKey, string>> = {},
  now = Date.now(),
): StepView[] {
  const steps = s?.steps ?? {}
  const analysis = analysisProgress(s, now)
  const scanFinished = Boolean(s?.finishedAt)

  return STEP_ORDER.map(({ key, label }) => {
    if (key === ANALYSIS_KEY) {
      if (!analysis) {
        return { key, label, state: (scanFinished ? 'skipped' : 'pending') as StepState, detail: null, error: null }
      }
      const running = analysis.done < analysis.total
      return {
        key,
        label,
        state: (running ? 'running' : 'done') as StepState,
        detail: running
          ? `${analysis.done} van ${analysis.total}${analysis.etaMs != null ? ` · nog ~${Math.max(1, Math.round(analysis.etaMs / 60_000))} min` : ''}`
          : `${analysis.total} beelden · ${s?.detectionsHit ?? 0} hits`,
        error: null,
      }
    }

    const step = steps[key as ScanStepKey]
    const clientError = clientErrors[key as ScanStepKey] ?? null
    if (!step) {
      // No entry: either it has not started yet, or the scan is over and it
      // never ran. Both are worth showing — a step that silently never ran is
      // exactly what used to be invisible.
      return {
        key,
        label,
        state: (scanFinished ? 'skipped' : 'pending') as StepState,
        detail: null,
        error: clientError,
      }
    }
    const state: StepState = clientError && step.state !== 'running' ? 'error' : step.state
    return {
      key,
      label,
      state,
      detail: state === 'done' ? summarizeCounts(step.counts) : null,
      error: step.error ?? clientError,
    }
  })
}

/** A handler's return dict, rendered as one short line. */
function summarizeCounts(counts: Record<string, number> | undefined): string | null {
  if (!counts) return null
  const parts: string[] = []
  const LABELS: Record<string, string> = {
    storiesFound: 'stories',
    accountsChecked: 'accounts',
    creators_scanned: 'creators',
    posts_added: 'posts',
    postsWritten: 'posts',
    hashtagDone: 'tags',
    scored: 'gescoord',
    updated: 'bijgewerkt',
  }
  for (const [k, label] of Object.entries(LABELS)) {
    const v = counts[k]
    if (typeof v === 'number' && v > 0) parts.push(`${v} ${label}`)
    if (parts.length === 2) break
  }
  return parts.length ? parts.join(' · ') : null
}

export function scanHeadline(s: ScanState | null, now = Date.now()):
  { title: string; sub: string | null; tone: 'accent' | 'good' | 'bad' | 'muted' } {
  const phase = scanPhase(s, now)
  const analysis = analysisProgress(s, now)
  switch (phase) {
    case 'idle':
      return { title: 'Nog geen scan gedraaid', sub: null, tone: 'muted' }
    case 'scraping':
      return { title: 'Bezig met scannen', sub: 'content ophalen bij Instagram en TikTok', tone: 'accent' }
    case 'analysing':
      return {
        title: 'Beelden analyseren',
        sub: analysis ? `${analysis.done} van ${analysis.total} · ${s?.detectionsHit ?? 0} hits` : null,
        tone: 'accent',
      }
    case 'stalled':
      return {
        title: 'Scan lijkt vastgelopen',
        sub: 'geen activiteit in 5 minuten — start opnieuw',
        tone: 'bad',
      }
    case 'error':
      return { title: 'Scan afgerond met fouten', sub: 'zie de stappen hieronder', tone: 'bad' }
    default:
      return {
        title: 'Scan afgerond',
        sub: s ? `${s.postsWritten ?? 0} posts · ${s.detectionsHit ?? 0} hits` : null,
        tone: 'good',
      }
  }
}
