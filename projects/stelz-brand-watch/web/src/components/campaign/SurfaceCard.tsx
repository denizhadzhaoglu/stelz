import { Card } from '../ui'
import { SURFACE_LABEL, SURFACE_METRIC, type Surface, type SurfaceStats } from '../../lib/campaign'
import { fmtNum, compactNum } from '../../lib/format'

/** What one surface produced. Three of these sit side by side and are never
 *  added up: TikTok publishes plays, an Instagram post publishes likes, and a
 *  story publishes nothing at all to anyone but the account holder. A single
 *  "reach" spanning the three would mean none of those things. */
export function SurfaceCard({ surface, stats, active, onPick }: {
  surface: Surface
  stats: SurfaceStats
  active: boolean
  onPick: () => void
}) {
  // An Instagram carousel is archived per slide, so `items` is images and
  // `posts` is what a person would count. Showing the slide count as though it
  // were posts turned 210 posts into 1150 on the real fixture.
  const split = surface === 'post' && stats.posts > 0 && stats.posts !== stats.items
  return (
    <Card className={`p-5 cursor-pointer transition-colors ${
      active ? 'border-[var(--color-ink)]' : ''
    }`}>
      <button onClick={onPick} className="text-left w-full">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">
          {SURFACE_LABEL[surface]}
        </div>
        <div className="stelz-display text-[26px] leading-none text-[var(--color-ink)] mb-1.5">
          {fmtNum(split ? stats.posts : stats.items)}
          {split && (
            <span className="stelz-display text-[13px] text-[var(--color-ink-subtle)]">
              {' '}posts · {fmtNum(stats.items)} beelden
            </span>
          )}
        </div>
        <div className="text-[12px] text-[var(--color-ink-muted)] space-y-0.5">
          <div>
            {stats.withStelz > 0
              ? (
                <span className="text-[var(--color-good)]">
                  {fmtNum(split ? stats.postsWithStelz : stats.withStelz)}× Stëlz
                </span>
              )
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
