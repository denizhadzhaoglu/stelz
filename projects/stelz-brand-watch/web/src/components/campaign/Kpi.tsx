import { Card } from '../ui'

/** One number with a label and a line of context underneath.
 *
 *  `sub` is not decoration. Every figure on this product is a fraction of
 *  something — sightings out of images judged, creators out of a roster — and a
 *  bare number invites the reader to supply their own denominator, which is
 *  always more flattering than the real one. */
export function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-1.5">{label}</div>
      <div className="stelz-display text-[26px] leading-none text-[var(--color-ink)]">{value}</div>
      {sub && <div className="text-[11px] text-[var(--color-ink-subtle)] mt-1.5">{sub}</div>}
    </Card>
  )
}
