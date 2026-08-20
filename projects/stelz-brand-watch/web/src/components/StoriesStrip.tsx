// Stories, at the top, because they are the thing that disappears.
//
// Everything else in this tool can be looked at tomorrow. A story cannot: it is
// gone 24 hours after it was posted, and for a festival roster that is the
// whole window. So stories do not live inside a tab — they sit above the tabs,
// on every view, and they lead with what is still live.
//
// Three states this must tell apart, because an empty strip means something
// different in each and the client is reading over your shoulder:
//   - never fetched          → nothing has ever looked
//   - fetched, nothing live  → normal; most creators have no story right now
//   - fetched, skipped       → budget or roster gate stopped it
// The last-run stamp on the brand doc is what makes that distinguishable; the
// 6-hourly scheduler runs outside any scan session and writes no step state.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card } from './ui'
import { MediaTile } from './MediaTile'
import { imageUrlFor, type DetectionRow } from '../lib/types'
import { storyChip, storyExpiry, storyFeed } from '../lib/stories'
import { timeAgo } from '../lib/format'
import type { StoriesState } from '../lib/firestore'

/** How many fit before the row asks you to scroll. */
const SHOWN = 24

export function StoriesStrip({
  rows,
  state,
  onOpen,
  onFetch,
  fetching = false,
  canWrite = true,
  error = null,
}: {
  rows: DetectionRow[]
  state: StoriesState | null
  onOpen: (d: DetectionRow) => void
  onFetch?: () => void
  fetching?: boolean
  /** Read-only viewers see the strip but not the fetch button. */
  canWrite?: boolean
  /** Failure from the last manual fetch, shown where the button was clicked. */
  error?: string | null
}) {
  const [onlyHits, setOnlyHits] = useState(false)
  const feed = storyFeed(rows)
  const hits = feed.all.filter((d) => d.detected === true)
  const shown = (onlyHits ? hits : feed.all).slice(0, SHOWN)

  return (
    <Card className="mb-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 border-b border-[var(--color-border)]">
        <h2 className="text-[13px] font-medium">Stories</h2>

        <span className="text-[12px] text-[var(--color-ink-muted)] tabular-nums">
          {feed.active.length > 0 && (
            <span className="text-[var(--color-accent)] font-medium">{feed.active.length} live</span>
          )}
          {feed.active.length > 0 && feed.expired.length > 0 && ' · '}
          {feed.expired.length > 0 && `${feed.expired.length} verlopen`}
          {feed.all.length > 0 && hits.length > 0 && (
            <span className="text-[var(--color-good)]"> · {hits.length}× Stëlz</span>
          )}
        </span>

        {hits.length > 0 && feed.all.length > hits.length && (
          <button
            onClick={() => setOnlyHits((v) => !v)}
            className={`text-[11px] px-2 py-0.5 border transition-colors ${
              onlyHits
                ? 'border-[var(--color-ink)] bg-[var(--color-ink)] text-white'
                : 'border-[var(--color-border)] text-[var(--color-ink-muted)] hover:border-[var(--color-border-strong)]'
            }`}
          >
            Alleen met Stëlz
          </button>
        )}

        <span className="ml-auto flex items-center gap-3 text-[11px] text-[var(--color-ink-subtle)]">
          <LastRun state={state} />
          {canWrite && onFetch && (
            <button
              onClick={onFetch}
              disabled={fetching}
              className="text-[11px] px-2.5 py-1 border border-[var(--color-border)] hover:border-[var(--color-ink)] hover:text-[var(--color-ink)] disabled:opacity-50 transition-colors"
            >
              {fetching ? 'Ophalen…' : 'Nu ophalen'}
            </button>
          )}
        </span>
      </div>

      {/* Next to the button that caused it, not in a page-level banner the eye
          has already scrolled past. */}
      {error && (
        <p className="px-4 py-2.5 text-[12px] text-[var(--color-bad)] border-b border-[var(--color-border)]">
          {error}
        </p>
      )}

      {shown.length === 0 ? (
        <EmptyStories state={state} onlyHits={onlyHits && hits.length === 0 && feed.all.length > 0} />
      ) : (
        // Horizontal scroll, not a wrapping grid: the row must not push the
        // rest of the page down as the roster grows, and stories are read in
        // sequence anyway — that is the format's own grammar.
        <div className="flex gap-2 overflow-x-auto px-4 py-3">
          {shown.map((d) => (
            <StoryTile key={d.detection_id} d={d} onOpen={() => onOpen(d)} />
          ))}
          {(onlyHits ? hits : feed.all).length > SHOWN && (
            <div className="shrink-0 w-[112px] flex items-center justify-center text-[11px] text-[var(--color-ink-subtle)] border border-dashed border-[var(--color-border)]">
              +{(onlyHits ? hits : feed.all).length - SHOWN}
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

function StoryTile({ d, onOpen }: { d: DetectionRow; onOpen: () => void }) {
  const e = storyExpiry(d)
  const hit = d.detected === true
  return (
    <button
      onClick={onOpen}
      title={`@${d.creator_handle}`}
      className={`shrink-0 w-[112px] text-left border transition-colors ${
        hit
          ? 'border-[var(--color-good)] hover:border-[var(--color-ink)]'
          : 'border-[var(--color-border)] hover:border-[var(--color-border-strong)]'
      } ${e?.expired ? 'opacity-70 hover:opacity-100' : ''}`}
    >
      <MediaTile src={imageUrlFor(d)} size="story" alt={`Story van @${d.creator_handle}`}>
        <span
          className={`absolute top-1 left-1 text-[9px] uppercase tracking-wider px-1.5 py-0.5 text-white ${
            e?.expired ? 'bg-[var(--color-ink-muted)]' : 'bg-[var(--color-accent)]'
          }`}
        >
          {e ? storyChip(e) : '—'}
        </span>
        {hit && (
          <span className="absolute top-1 right-1 text-[9px] px-1 py-0.5 bg-[var(--color-good)] text-white">
            Stëlz
          </span>
        )}
      </MediaTile>
      <span className="block px-1.5 py-1 text-[10px] truncate text-[var(--color-ink-muted)]">
        @{d.creator_handle}
      </span>
    </button>
  )
}

function LastRun({ state }: { state: StoriesState | null }) {
  if (!state?.lastRunAt) return <span>nog nooit opgehaald</span>
  const when = timeAgo(state.lastRunAt)
  if (state.lastSkipped) return <span title={state.lastSkipped}>overgeslagen · {when}</span>
  return <span>laatst gekeken · {when}</span>
}

function EmptyStories({ state, onlyHits }: { state: StoriesState | null; onlyHits: boolean }) {
  if (onlyHits) {
    return (
      <p className="px-4 py-6 text-[12px] text-[var(--color-ink-muted)]">
        Geen van de opgehaalde stories bevat een zichtbare Stëlz.
      </p>
    )
  }
  if (!state?.lastRunAt) {
    return (
      <div className="px-4 py-6 text-[12px] text-[var(--color-ink-muted)] space-y-1">
        <p>Nog geen stories opgehaald.</p>
        <p className="text-[var(--color-ink-subtle)]">
          Stories verdwijnen na 24 uur. Zet automatisch ophalen aan onder{' '}
          <Link to="/settings" className="underline hover:text-[var(--color-ink)]">Instellingen</Link>{' '}
          of haal ze nu handmatig op.
        </p>
      </div>
    )
  }
  if (state.lastSkipped) {
    const why = state.lastSkipped.startsWith('budget')
      ? 'het scrapebudget voor deze maand is op'
      : state.lastSkipped === 'no_creators'
        ? 'er staan geen creators op tier 1 of 2'
        : state.lastSkipped
    return (
      <p className="px-4 py-6 text-[12px] text-[var(--color-ink-muted)]">
        Laatste poging overgeslagen: {why}.
      </p>
    )
  }
  // The normal case. Deliberately not styled as a problem: most creators have
  // no live story at any given moment, and a panel that cries wolf four times
  // a day gets ignored on the day it matters.
  return (
    <p className="px-4 py-6 text-[12px] text-[var(--color-ink-muted)]">
      Geen actieve stories op dit moment — {state.lastChecked ?? 0} account
      {state.lastChecked === 1 ? '' : 's'} gecontroleerd. Dat is normaal.
    </p>
  )
}
