// Settings — user-friendly, section-grouped. All the backend calls are the
// same as before; the change is purely UX: friendlier copy, progressive
// disclosure for the technical dials, cleaner hierarchy.

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { activeReferenceIds, REFERENCE_SLOTS } from '../lib/refselect'
import {
  PageShell, Card, Button, Badge, Field, Input, Textarea, Img,
} from '../components/ui'
import {
  fbListReferenceImages,
  fbUploadReferenceImage,
  fbDeleteReferenceImage,
  fbGetBrand,
  fbUpdateBrandSettings,
  fbListHashtagPool,
  fbRecomputeCentroid,
  type ReferenceImage,
  type BrandDoc,
  type HashtagPoolEntry,
} from '../lib/firestore'

export default function Settings() {
  return (
    <PageShell title="Settings" subtitle="Stëlz Community Watch">
      <div className="space-y-16">
        <BrandProfileSection />
        <TrainingSection />
        <HashtagPoolSection />
        <AdvancedSection />
        <DangerSection />
      </div>
    </PageShell>
  )
}

// ─── Shared shell ────────────────────────────────────────────────────

function SectionShell({
  eyebrow, title, hint, action, children,
}: {
  eyebrow: string
  title: string
  hint?: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="space-y-5">
      <header className="flex items-start justify-between gap-6 border-b-2 border-[var(--color-ink)] pb-4">
        <div className="min-w-0 flex-1">
          <div className="text-[10px] uppercase tracking-[0.16em] text-[var(--color-accent)] font-medium mb-2">{eyebrow}</div>
          <h2 className="stelz-display text-[22px] lg:text-[26px] leading-none text-[var(--color-ink)]">{title}</h2>
          {hint && <p className="text-[13px] text-[var(--color-ink-muted)] mt-2 leading-relaxed max-w-[560px]">{hint}</p>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      {children}
    </section>
  )
}

function SavedInline({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--color-ink-muted)]">
      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-good)]" />
      {msg}
    </span>
  )
}

function ErrorInline({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <div className="text-[12px] text-[var(--color-bad)] border border-[var(--color-bad)] px-3 py-2 leading-relaxed">
      {msg}
    </div>
  )
}

// ─── 1. Brand ────────────────────────────────────────────────────────

function BrandProfileSection() {
  const [brand, setBrand] = useState<BrandDoc | null>(null)
  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fbGetBrand().then((b) => {
      setBrand(b); setName(b?.name ?? ''); setWebsite(b?.website ?? '')
    })
  }, [])

  async function save() {
    setBusy(true); setMsg(null); setErr(null)
    try {
      await fbUpdateBrandSettings({ name, website })
      setMsg('Saved')
      setTimeout(() => setMsg(null), 2500)
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  if (!brand) return null
  return (
    <SectionShell
      eyebrow="Brand"
      title="Your brand's profile"
      hint="Public-facing name and website. Used across the dashboard and in outreach templates."
    >
      <Card className="p-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Field label="Brand name">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Stelz" />
          </Field>
          <Field label="Website">
            <Input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://drinkstelz.com" />
          </Field>
        </div>
        <ErrorInline msg={err} />
        <div className="flex items-center gap-3 pt-2">
          <Button variant="primary" size="sm" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Save changes'}
          </Button>
          <SavedInline msg={msg} />
        </div>
      </Card>
    </SectionShell>
  )
}

// ─── 2. Training the detector (identity + wordmarks + reference images) ──

function TrainingSection() {
  const [identity, setIdentity] = useState('')
  const [wordmarks, setWordmarks] = useState('')
  const [items, setItems] = useState<ReferenceImage[]>([])
  // Which of these the detector is actually shown — see lib/refselect.ts.
  const activeIds = useMemo(() => activeReferenceIds(items), [items])
  const [loadingRefs, setLoadingRefs] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [centroidBusy, setCentroidBusy] = useState(false)
  const [savingIdentity, setSavingIdentity] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [centroidComputedAt, setCentroidComputedAt] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function refresh() {
    setLoadingRefs(true)
    try {
      const [list, brand] = await Promise.all([fbListReferenceImages(), fbGetBrand()])
      setItems(list)
      setIdentity(brand?.visualIdentity ?? '')
      setWordmarks((brand?.wordmarkAliases ?? []).join(', '))
      setCentroidComputedAt(brand?.visualCentroidComputedAt ?? null)
    } catch (e) { setErr((e as Error).message) }
    finally { setLoadingRefs(false) }
  }
  useEffect(() => { void refresh() }, [])

  async function saveIdentity() {
    setSavingIdentity(true); setMsg(null); setErr(null)
    try {
      const aliases = wordmarks.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean)
      await fbUpdateBrandSettings({ visualIdentity: identity, wordmarkAliases: aliases })
      setMsg('Identity saved. Next scan will use it.')
      setTimeout(() => setMsg(null), 3000)
    } catch (e) { setErr((e as Error).message) }
    finally { setSavingIdentity(false) }
  }

  async function uploadFiles(files: FileList | File[]) {
    setUploading(true); setErr(null); setMsg(null)
    try {
      const arr = Array.from(files).filter((f) => f.type.startsWith('image/'))
      for (const f of arr) {
        if (f.size > 8 * 1024 * 1024) { setErr(`${f.name} is over 8 MB — skipped`); continue }
        await fbUploadReferenceImage(f)
      }
      await refresh()
      setMsg(`Uploaded ${arr.length} image${arr.length === 1 ? '' : 's'}. Recomputing detection profile…`)
      void autoRecompute()
    } catch (e) { setErr((e as Error).message) }
    finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function onDelete(item: ReferenceImage) {
    if (!confirm('Remove this reference image?')) return
    setUploading(true); setErr(null)
    try {
      await fbDeleteReferenceImage(item.id, item.storagePath)
      await refresh()
      void autoRecompute()
    } catch (e) { setErr((e as Error).message) }
    finally { setUploading(false) }
  }

  async function autoRecompute() {
    setCentroidBusy(true)
    try {
      const r = await fbRecomputeCentroid()
      if (r.computed) setMsg(`Detection profile updated · using ${r.refsUsed} of ${r.refsFound} images.`)
      else if ((r.refsFound ?? 0) === 0) setMsg('Upload at least one reference image to enable the visual filter.')
      else if ((r.fetchErrors ?? []).length > 0) setErr(`Couldn't process ${r.fetchErrors.length} of ${r.refsFound} images. First error: ${r.fetchErrors[0]}`)
      else setErr("Reference images uploaded but couldn't be processed. Try re-uploading.")
      await refresh()
    } catch (e) { setErr(`Auto-refresh failed: ${(e as Error).message}`) }
    finally { setCentroidBusy(false) }
  }

  return (
    <SectionShell
      eyebrow="Detection"
      title="Teach the AI what to look for"
      hint="Describe your brand's look, add exact spellings to catch by text, and drop in a few product photos. The more it sees, the smarter it gets."
    >
      <div className="space-y-6">
        {/* Reference images — first because it's the highest signal */}
        <Card className="p-6">
          <SubHeader
            step="Product photos"
            title="Reference images"
            desc="Clean product shots at different angles and lighting work best. Every image here is shown to the AI as “this IS the product”, so a photo containing another brand's can teaches it wrong — there is no way to mark an image as a counter-example."
            trailing={items.length > 0 ? (
              <span className="text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
                {items.length} image{items.length === 1 ? '' : 's'}
              </span>
            ) : null}
          />

          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files) uploadFiles(e.dataTransfer.files) }}
            className={`border border-dashed py-10 px-6 text-center transition-colors ${dragOver ? 'border-[var(--color-ink)] bg-[var(--color-bg)]' : 'border-[var(--color-border-strong)]'}`}
          >
            <div className="text-[13px] font-medium text-[var(--color-ink)] mb-1.5">Drop images here</div>
            <div className="text-[12px] text-[var(--color-ink-muted)] mb-4">or</div>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => e.target.files && uploadFiles(e.target.files)}
            />
            <Button size="sm" variant="primary" disabled={uploading} onClick={() => fileRef.current?.click()}>
              {uploading ? 'Uploading…' : 'Choose files'}
            </Button>
          </div>

          {(msg || err) && (
            <div className="mt-4 space-y-2">
              {err && <ErrorInline msg={err} />}
              {msg && !err && (
                <div className="text-[12px] text-[var(--color-ink-muted)] border border-[var(--color-border)] px-3 py-2 leading-relaxed">
                  {msg}
                </div>
              )}
            </div>
          )}

          {centroidComputedAt && !centroidBusy && (
            <div className="mt-4 flex items-center justify-between text-[11px] text-[var(--color-ink-subtle)]">
              <span>Detection profile updated {new Date(centroidComputedAt).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })}</span>
            </div>
          )}
          {centroidBusy && (
            <div className="mt-4 text-[11px] text-[var(--color-ink-muted)]">Rebuilding detection profile…</div>
          )}

          {loadingRefs && <div className="mt-6 text-[12px] text-[var(--color-ink-muted)] text-center">Loading…</div>}
          {!loadingRefs && items.length > 0 && (
            <>
              {/* Which images are actually in play. The detector is sent 8, chosen
                  newest-first with one slot reserved per product line — so with
                  more than 8 uploads, some are dead weight and an operator hunting
                  a bad reference could delete one the model never sees. See
                  lib/refselect.ts, which mirrors refs.py _select_reference_docs. */}
              <p className="mt-6 text-[12px] text-[var(--color-ink-muted)] leading-relaxed">
                {items.length > REFERENCE_SLOTS ? (
                  <>
                    The detector is shown <strong className="text-[var(--color-ink)]">{REFERENCE_SLOTS} of these {items.length}</strong>{' '}
                    — newest first, with one slot kept for each product line. The dimmed ones
                    are stored but never sent. If a detection keeps confusing another brand's
                    can for yours, check the {REFERENCE_SLOTS} highlighted here first.
                  </>
                ) : (
                  <>All {items.length} of these are shown to the detector on every scan.</>
                )}
              </p>
              <div className="mt-3 grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
              {items.map((it) => (
                <div
                  key={it.id}
                  className={`bg-[var(--color-surface)] p-1.5 relative group ${activeIds.has(it.id) ? '' : 'opacity-40'}`}
                  title={activeIds.has(it.id) ? 'Sent to the detector' : 'Stored, but not sent — the detector only takes 8'}
                >
                  <div className="aspect-square"><Img src={it.url} /></div>
                  {activeIds.has(it.id) && (
                    <span className="absolute bottom-2 left-2 text-[9px] uppercase tracking-widest bg-[var(--color-ink)]/80 text-white px-1.5 py-0.5">
                      in use
                    </span>
                  )}
                  <button
                    onClick={() => onDelete(it)}
                    disabled={uploading}
                    className="absolute top-2 right-2 w-5 h-5 bg-[var(--color-surface)] border border-[var(--color-border-strong)] text-[var(--color-ink-muted)] hover:text-[var(--color-bad)] hover:border-[var(--color-bad)] flex items-center justify-center text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Remove image"
                  >
                    ✕
                  </button>
                </div>
              ))}
              </div>
            </>
          )}
        </Card>

        {/* Brand name spellings (OCR wordmarks) */}
        <Card className="p-6 space-y-5">
          <SubHeader
            step="Brand names"
            title="Spellings we catch on sight"
            desc="Every way your brand can be written (accents, common misspellings). If we read one of these on a can, shirt, or sign, it's an instant match."
          />
          <Field label="">
            <Input
              value={wordmarks}
              onChange={(e) => setWordmarks(e.target.value)}
              placeholder="stelz, stélz, stëlz"
            />
          </Field>
          <div className="text-[11px] text-[var(--color-ink-subtle)]">Comma-separated. Case doesn't matter.</div>
        </Card>

        {/* Visual identity description */}
        <Card className="p-6 space-y-5">
          <SubHeader
            step="Look & feel"
            title="Describe how your brand looks"
            desc="Colors, logo, packaging, tagline. In plain English. Bullets work great."
          />
          <Field label="">
            <Textarea
              rows={8}
              value={identity}
              onChange={(e) => setIdentity(e.target.value)}
              placeholder={`- Slim navy can with the STËLZ wordmark and an umlaut on the E\n- A circle-S ring icon — its color shows the flavor (orange = lemonade, red = seltzer, teal = iced tea)\n- Curved tagline: HARD SELTZER / HARD LEMONADE\n- Dutch beverage, 250–330ml can format`}
              className="text-[12px] leading-relaxed"
            />
          </Field>
        </Card>

        <div className="flex items-center gap-3 pt-2">
          <Button variant="primary" size="sm" disabled={savingIdentity} onClick={saveIdentity}>
            {savingIdentity ? 'Saving…' : 'Save identity & spellings'}
          </Button>
          <SavedInline msg={msg && !err ? msg : null} />
        </div>
      </div>
    </SectionShell>
  )
}

function SubHeader({ step, title, desc, trailing }: { step: string; title: string; desc: string; trailing?: ReactNode }) {
  return (
    <header className="mb-5 flex items-start justify-between gap-4">
      <div>
        <div className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)] mb-1.5">{step}</div>
        <h3 className="text-[15px] font-medium text-[var(--color-ink)] tracking-tight">{title}</h3>
        <p className="text-[12px] text-[var(--color-ink-muted)] mt-1.5 leading-relaxed max-w-[540px]">{desc}</p>
      </div>
      {trailing}
    </header>
  )
}

// ─── 3. Hashtag pool ─────────────────────────────────────────────────

function HashtagPoolSection() {
  const [items, setItems] = useState<HashtagPoolEntry[]>([])
  const [draft, setDraft] = useState('')
  const [draftPlatform, setDraftPlatform] = useState<'instagram' | 'tiktok'>('instagram')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function refresh() { setItems(await fbListHashtagPool()) }
  useEffect(() => { void refresh() }, [])

  async function save(next: HashtagPoolEntry[], replace = false) {
    setBusy(true); setMsg(null); setErr(null)
    try {
      await fbUpdateBrandSettings({}, {
        hashtagPool: next.map(({ tag, platform, priority, active }) => ({ tag, platform, priority, active })),
        replaceHashtags: replace,
      })
      await refresh()
      setMsg('Saved')
      setTimeout(() => setMsg(null), 2000)
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  async function addTag() {
    const t = draft.trim().toLowerCase().replace(/^#/, '')
    if (!t) return
    const next: HashtagPoolEntry[] = [...items, { id: `${draftPlatform}_${t}`, tag: t, platform: draftPlatform, priority: 5, active: true }]
    setDraft('')
    await save(next)
  }

  const activeCount = items.filter((i) => i.active).length

  return (
    <SectionShell
      eyebrow="Discovery"
      title="Hashtags we watch"
      hint="We scan Instagram and TikTok for posts using these tags. Higher-priority tags are scanned first."
      action={
        <div className="text-[11px] text-[var(--color-ink-subtle)] tabular-nums">
          {activeCount} active · {items.length} total
        </div>
      }
    >
      <Card className="p-6 space-y-5">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={draftPlatform}
            onChange={(e) => setDraftPlatform(e.target.value as 'instagram' | 'tiktok')}
            className="border border-[var(--color-border-strong)] bg-[var(--color-surface)] px-3 h-9 text-[13px] focus:outline-none focus:border-[var(--color-ink)]"
          >
            <option value="instagram">Instagram</option>
            <option value="tiktok">TikTok</option>
          </select>
          <Input
            placeholder="stelz, vrijmibo, koningsdag…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addTag()}
            className="max-w-xs flex-1"
          />
          <Button variant="primary" size="sm" disabled={busy || !draft.trim()} onClick={addTag}>Add</Button>
          <SavedInline msg={msg} />
        </div>

        {err && <ErrorInline msg={err} />}

        {items.length === 0 ? (
          <div className="border border-dashed border-[var(--color-border-strong)] py-10 text-center text-[12px] text-[var(--color-ink-muted)]">
            No hashtags yet. Add 3–5 to get discovery started.
          </div>
        ) : (
          <ul className="divide-y divide-[var(--color-border)]">
            {items.sort((a, b) => b.priority - a.priority || a.tag.localeCompare(b.tag)).map((h) => (
              <li key={h.id} className="py-3 grid grid-cols-[24px_1fr_88px_120px_60px] gap-3 items-center text-[13px]">
                <input
                  type="checkbox"
                  checked={h.active}
                  onChange={() => save(items.map((x) => x.id === h.id ? { ...x, active: !x.active } : x))}
                  className="accent-[var(--color-ink)]"
                />
                <span className={h.active ? '' : 'text-[var(--color-ink-subtle)] line-through'}>
                  #{h.tag}
                </span>
                <Badge tone="muted">{h.platform}</Badge>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-[0.14em] text-[var(--color-ink-subtle)]">Priority</span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={h.priority}
                    onChange={(e) => save(items.map((x) => x.id === h.id ? { ...x, priority: parseInt(e.target.value) || 5 } : x))}
                    className="w-11 border border-[var(--color-border)] px-2 h-7 text-[12px] tabular-nums text-center"
                  />
                </div>
                <button
                  onClick={() => save(items.filter((x) => x.id !== h.id), true)}
                  className="text-[11px] text-[var(--color-ink-subtle)] hover:text-[var(--color-bad)] text-right"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </SectionShell>
  )
}

// ─── 5. Advanced (collapsed by default) ──────────────────────────────

function AdvancedSection() {
  const [open, setOpen] = useState(false)
  const [confidenceMin, setConfidenceMin] = useState(0.7)
  const [dailyBudget, setDailyBudget] = useState(5)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fbGetBrand().then((b) => {
      if (!b) return
      if (typeof b.confidenceMin === 'number') setConfidenceMin(b.confidenceMin)
      if (typeof b.dailyBudgetUsd === 'number') setDailyBudget(b.dailyBudgetUsd)
    })
  }, [])

  async function save() {
    setBusy(true); setMsg(null); setErr(null)
    try {
      await fbUpdateBrandSettings({
        confidenceMin,
        dailyBudgetUsd: dailyBudget,
      })
      setMsg('Saved')
      setTimeout(() => setMsg(null), 2500)
    } catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }

  return (
    <SectionShell
      eyebrow="Advanced"
      title="Fine-tuning"
      hint="Sensible defaults are already set. Open this only if you want to trade precision for reach, or cap daily costs."
      action={
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] underline decoration-dotted underline-offset-4"
        >
          {open ? 'Hide options' : 'Show options'}
        </button>
      }
    >
      {open && (
        <Card className="p-6 space-y-8">
          <Slider
            label="Only show detections above"
            hint="Anything the AI is less sure about stays hidden from the main feed. You can still find them in a filter."
            value={confidenceMin}
            min={0} max={1} step={0.05}
            onChange={setConfidenceMin}
            format={(v) => `${(v * 100).toFixed(0)}%`}
          />

          <Field label="Daily budget cap (USD)" hint="Once the day's estimated spend hits this, further scans pause until tomorrow.">
            <Input
              type="number"
              min={0}
              step={1}
              value={dailyBudget}
              onChange={(e) => setDailyBudget(parseFloat(e.target.value) || 0)}
              className="max-w-[140px]"
            />
          </Field>

          <ErrorInline msg={err} />
          <div className="flex items-center gap-3 pt-2 border-t border-[var(--color-border)]">
            <Button variant="primary" size="sm" disabled={busy} onClick={save}>
              {busy ? 'Saving…' : 'Save advanced settings'}
            </Button>
            <SavedInline msg={msg} />
          </div>
        </Card>
      )}
    </SectionShell>
  )
}

function Slider({ label, hint, value, min, max, step, onChange, format }: {
  label: string; hint?: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format: (v: number) => string
}) {
  return (
    <div>
      <div className="flex items-start justify-between mb-3 gap-4">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-[var(--color-ink)]">{label}</div>
          {hint && <div className="text-[11px] text-[var(--color-ink-muted)] mt-1 leading-relaxed max-w-[440px]">{hint}</div>}
        </div>
        <div className="text-[16px] font-medium tabular-nums text-[var(--color-ink)] shrink-0">{format(value)}</div>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-[var(--color-ink)]"
      />
    </div>
  )
}

// ─── 6. Danger zone (collapsed by default) ───────────────────────────

function DangerSection() {
  const [open, setOpen] = useState(false)
  return (
    <SectionShell
      eyebrow="Danger zone"
      title="Irreversible actions"
      hint="Export all your data or delete this brand entirely. These aren't wired up yet — they'll ask twice before doing anything."
      action={
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-[12px] text-[var(--color-ink-muted)] hover:text-[var(--color-bad)] underline decoration-dotted underline-offset-4"
        >
          {open ? 'Hide' : 'Show'}
        </button>
      }
    >
      {open && (
        <Card className="p-6 divide-y divide-[var(--color-border)]">
          <div className="flex items-center justify-between pb-5">
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-[var(--color-ink)]">Export all data</div>
              <div className="text-[11px] text-[var(--color-ink-muted)] mt-0.5">Download every detection and creator as CSV.</div>
            </div>
            <Button size="sm" disabled>Coming soon</Button>
          </div>
          <div className="flex items-center justify-between pt-5">
            <div className="min-w-0">
              <div className="text-[13px] font-medium text-[var(--color-bad)]">Delete brand</div>
              <div className="text-[11px] text-[var(--color-ink-muted)] mt-0.5">Removes every detection, hashtag, and reference image. Cannot be undone.</div>
            </div>
            <Button variant="danger" size="sm" disabled>Coming soon</Button>
          </div>
        </Card>
      )}
    </SectionShell>
  )
}
