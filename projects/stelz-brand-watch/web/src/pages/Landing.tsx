import { useState } from 'react'
import { Logo, Button, Badge, Input } from '../components/ui'

const FEATURES = [
  { n: '01', t: 'Visual brand detection', d: 'Gemini Vision finds your product in photos and videos, even when no caption mentions you.' },
  { n: '02', t: 'Live feed', d: 'New detections land continuously. Filter by product line, confidence, tier, sentiment.' },
  { n: '03', t: 'AI relevance scoring', d: 'Each creator gets an resonance score so you focus on the ones that matter.' },
  { n: '04', t: 'Multi-platform', d: 'Instagram posts, Reels, Stories. TikTok video frames. Comments and hashtags.' },
  { n: '05', t: 'Alerts + PDF reports', d: 'Daily summary email, Slack alerts on tier-1 hits, weekly PDF for the team.' },
  { n: '06', t: 'Historical backfill', d: 'Pro plan goes back 90 days. Enterprise up to a full year.' },
  { n: '07', t: 'Creator outreach DMs', d: 'Auto-drafted DMs tailored per creator and tone. Copy-paste, send.' },
  { n: '08', t: 'Multi-tenant by default', d: 'Manage multiple brands or product lines from one workspace.' },
]

const STEPS = [
  { n: 1, t: 'Onboard your brand', d: 'Upload 5 product photos and confirm your hashtags. 5 minutes.' },
  { n: 2, t: 'Auto-discover creators', d: 'We crawl hashtags, mentions, followers — building a candidate set per day.' },
  { n: 3, t: 'Visual + textual detection', d: 'Computer vision verifies every candidate. Strong hits land in your feed.' },
  { n: 4, t: 'Insights, weekly or daily', d: 'Daily email digest, weekly PDF, Slack alerts, outreach helpers.' },
]

const PLANS = [
  { name: 'Starter', price: '€500', features: ['200 monitored creators', 'Instagram only', '7-day lookback', 'Weekly reports', '2 seats', '100 credits'] },
  { name: 'Pro', price: '€1.500', featured: true, features: ['1.000 monitored creators', 'IG + TikTok', '90-day lookback', 'Daily reports', '5 seats', '500 credits', 'Pro detect layer', 'Slack alerts'] },
  { name: 'Enterprise', price: 'Custom', features: ['10k+ creators', 'All platforms', '1-year lookback', 'Real-time alerts', 'Unlimited seats', 'Custom integrations', 'Account manager', 'SLA + SSO'] },
]

const FAQ = [
  { q: 'How accurate is the visual detection?', a: 'We benchmark at 92-95% precision on bottle/can detection for FMCG. False positives go to the moderator queue for human review.' },
  { q: 'Do I need to give you my Instagram password?', a: 'No. We use OAuth (Meta Business) for read-only access to public content. Your password stays with Meta.' },
  { q: 'Can I monitor competitors?', a: 'Yes. Pro and Enterprise plans support multi-brand workspaces. Add competitor product lines and reference images alongside your own.' },
  { q: 'What if a creator wants to be removed?', a: 'Email privacy@jackandai.com with the handle. We exclude the creator within 7 business days. Trusted by reach 1 brand.' },
  { q: 'Is this GDPR compliant?', a: 'Yes — we process only public content, have a DPA available, and retain monitoring data tied to your subscription. See Privacy Policy.' },
  { q: 'Can I cancel anytime?', a: 'Yes. Cancel during trial: no charge. Cancel after: subscription ends at period close, data is retained for 30 days.' },
  { q: 'Do credits roll over?', a: 'Yes, one month. Unused credits expire after that.' },
  { q: 'What platforms do you cover?', a: 'Instagram (posts, reels, stories) on all plans. TikTok on Pro+. YouTube Shorts in beta.' },
]

export default function Landing() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="h-14 px-4 sm:px-6 lg:px-10 border-b border-[var(--color-border)] flex items-center bg-[var(--color-surface)] sticky top-0 z-10">
        <Logo small />
        <nav className="ml-auto flex items-center gap-4 lg:gap-7 text-[13px] text-[var(--color-ink-muted)]">
          <a className="hidden md:inline" href="#how">How it works</a>
          <a className="hidden md:inline" href="#features">Features</a>
          <a className="hidden sm:inline" href="#pricing">Pricing</a>
          <a className="hidden lg:inline" href="#demo">Demo</a>
          <a className="hidden lg:inline" href="#faq">FAQ</a>
          <a href="/login" className="text-[var(--color-ink)]">Sign in</a>
          <Button variant="primary" size="sm">Start free trial</Button>
        </nav>
      </header>

      <section className="px-4 sm:px-6 lg:px-10 py-16 lg:py-24 max-w-4xl">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-5">
          AI brand monitoring · for FMCG and lifestyle brands
        </div>
        <h1 className="text-[36px] sm:text-[48px] lg:text-[64px] leading-[1.05] lg:leading-[1.02] tracking-tight font-medium mb-7">
          See where your brand <em className="not-italic underline decoration-[var(--color-accent)] decoration-4 underline-offset-4">really</em> shows up.
        </h1>
        <p className="text-[17px] text-[var(--color-ink-muted)] leading-relaxed max-w-2xl mb-9">
          Computer vision finds your product in social content — even when nobody tags you. We rank the creators
          carrying it, surface the ones that matter, and write the outreach DMs.
        </p>
        <div className="flex gap-3 flex-wrap">
          <a href="/onboarding"><Button variant="primary" size="md">Start 14-day free trial</Button></a>
          <a href="/dashboard"><Button size="md">See live demo</Button></a>
        </div>
        <div className="mt-6 text-[12px] text-[var(--color-ink-subtle)]">
          No credit card · 5-minute setup · First hits within 30 minutes
        </div>
      </section>

      {/* Problem */}
      <section className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="max-w-3xl mb-10">
          <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">The problem</div>
          <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-4">Hashtag monitoring misses 80% of your brand mentions.</h2>
          <p className="text-[15px] text-[var(--color-ink-muted)] leading-relaxed max-w-2xl">
            Your fans drink your product without writing your name in their caption. Influencer tools want
            five-figure retainers. Manual scrolling doesn't scale.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
          {[
            { n: '01', t: 'The hashtag gap', d: 'Most people post the product without hashtagging the brand. You only see the loud minority.' },
            { n: '02', t: 'The noise problem', d: 'Generic tools surface everything. You spend hours filtering for what actually matters.' },
            { n: '03', t: 'The expensive lock-in', d: 'Most platforms charge €5-15k/mo and lock you into long contracts. We start at €500.' },
          ].map((c) => (
            <div key={c.n} className="bg-[var(--color-surface)] p-7">
              <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">{c.n}</div>
              <h3 className="text-[16px] font-medium mb-2">{c.t}</h3>
              <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed">{c.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How */}
      <section id="how" className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">How it works</div>
        <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-10">Four steps. Then it runs.</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
          {STEPS.map((s) => (
            <div key={s.n} className="bg-[var(--color-surface)] p-7">
              <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3 tabular-nums">Step {s.n}</div>
              <h3 className="text-[15px] font-medium mb-2">{s.t}</h3>
              <p className="text-[13px] text-[var(--color-ink-muted)] leading-relaxed">{s.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section id="features" className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Features</div>
        <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-10">Everything you need. Nothing you don't.</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
          {FEATURES.map((f) => (
            <div key={f.n} className="bg-[var(--color-surface)] p-6">
              <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2 tabular-nums">{f.n}</div>
              <h3 className="text-[14px] font-medium mb-1.5">{f.t}</h3>
              <p className="text-[12px] text-[var(--color-ink-muted)] leading-relaxed">{f.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Demo */}
      <section id="demo" className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-8 lg:gap-12 items-center">
          <div>
            <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Live demo</div>
            <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-4">See it live.</h2>
            <p className="text-[15px] text-[var(--color-ink-muted)] leading-relaxed mb-6 max-w-md">
              A working dashboard with real production data from a Dutch hard seltzer brand.
            </p>
            <a href="/dashboard"><Button variant="primary">Open the live demo →</Button></a>
            <div className="mt-4 text-[12px] text-[var(--color-ink-subtle)]">
              436 verified hits · 545 creators · daily scans · 90 days of history
            </div>
          </div>
          <div className="aspect-[4/3] bg-[var(--color-bg)] border border-[var(--color-border)]" />
        </div>
      </section>

      {/* Try */}
      <section className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-2xl">
          <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Try it</div>
          <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-4">Try it on your brand right now.</h2>
          <p className="text-[15px] text-[var(--color-ink-muted)] mb-6">Enter an Instagram handle and we'll scan the last 6 posts.</p>
          <TryScanner />
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">Pricing</div>
        <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-3">Simple pricing. No surprises.</h2>
        <p className="text-[15px] text-[var(--color-ink-muted)] mb-10">Pick the tier that matches your scale.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-[var(--color-border)] border border-[var(--color-border)]">
          {PLANS.map((p) => (
            <div key={p.name} className={`bg-[var(--color-surface)] p-7 ${p.featured ? 'outline outline-2 -outline-offset-2 outline-[var(--color-ink)] z-10' : ''}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="text-[14px] font-medium">{p.name}</div>
                {p.featured && <Badge tone="accent">most popular</Badge>}
              </div>
              <div className="text-[36px] font-medium tabular-nums tracking-tight mb-1">{p.price}</div>
              <div className="text-[12px] text-[var(--color-ink-muted)] mb-6">{p.price !== 'Custom' && 'per month'}</div>
              <ul className="space-y-1.5 mb-6 text-[13px]">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2">
                    <span className="text-[var(--color-ink-subtle)] mt-px">·</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <a href="/onboarding"><Button variant={p.featured ? 'primary' : 'secondary'} className="w-full">
                {p.price === 'Custom' ? 'Contact sales' : 'Start trial'}
              </Button></a>
            </div>
          ))}
        </div>
      </section>

      {/* Signup CTA */}
      <section className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 lg:gap-16 items-start">
          <div>
            <h2 className="text-[40px] font-medium tracking-tight mb-4">Start your free trial.</h2>
            <p className="text-[15px] text-[var(--color-ink-muted)] mb-6">5-minute setup. No credit card.</p>
            <ul className="space-y-2 text-[14px]">
              {['Self-serve setup', 'First detections within 30 minutes', '14 days free, cancel anytime', 'Need help? Email support@jackandai.com'].map((b) => (
                <li key={b} className="flex items-start gap-2.5">
                  <span className="text-[var(--color-accent)]">→</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="border border-[var(--color-border)] p-7 bg-[var(--color-bg)]">
            <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-2">Ready to see your brand?</div>
            <h3 className="text-[20px] font-medium mb-3">Start setup</h3>
            <p className="text-[13px] text-[var(--color-ink-muted)] mb-5">The onboarding wizard scans your Instagram, builds a hashtag pool, and provisions your workspace.</p>
            <a href="/onboarding"><Button variant="primary" className="w-full">Start setup →</Button></a>
            <div className="mt-3 text-[12px] text-[var(--color-ink-subtle)]">
              Prefer to talk first? <a className="text-[var(--color-ink)] underline" href="mailto:meinte@jackandai.com">Email Meinte</a>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="px-4 sm:px-6 lg:px-10 py-12 lg:py-20 border-t border-[var(--color-border)]">
        <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] mb-3">FAQ</div>
        <h2 className="text-[24px] sm:text-[28px] lg:text-[36px] font-medium tracking-tight mb-10">Frequently asked.</h2>
        <div className="border-t border-[var(--color-border)] max-w-3xl">
          {FAQ.map((f) => (
            <details key={f.q} className="border-b border-[var(--color-border)] group">
              <summary className="py-5 cursor-pointer flex items-center justify-between text-[15px] list-none">
                <span>{f.q}</span>
                <span className="text-[var(--color-ink-subtle)] group-open:rotate-45 transition-transform">+</span>
              </summary>
              <div className="pb-5 text-[14px] text-[var(--color-ink-muted)] leading-relaxed">{f.a}</div>
            </details>
          ))}
        </div>
      </section>

      <footer className="px-4 sm:px-6 lg:px-10 py-8 lg:py-10 border-t border-[var(--color-border)] flex flex-wrap items-center justify-between gap-4 text-[12px] text-[var(--color-ink-subtle)]">
        <div className="flex items-center gap-6">
          <Logo small />
          <span>built by JackandAI</span>
        </div>
        <div className="flex items-center gap-6">
          <a href="/terms">Terms</a>
          <a href="/privacy">Privacy</a>
          <a href="mailto:hello@jackandai.com">hello@jackandai.com</a>
          <span>© 2026</span>
        </div>
      </footer>
    </div>
  )
}

function TryScanner() {
  const [handle, setHandle] = useState('')
  const [results, setResults] = useState<{ url: string; detected: boolean; confidence: number }[] | null>(null)

  return (
    <div>
      <form
        className="flex gap-2 max-w-md mb-5"
        onSubmit={(e) => {
          e.preventDefault()
          if (!handle) return
          setResults(
            Array.from({ length: 6 }).map((_, i) => ({
              url: `#${i}`,
              detected: i % 2 === 0,
              confidence: 0.6 + (i * 7) / 100,
            })),
          )
        }}
      >
        <Input placeholder="@yourbrand" value={handle} onChange={(e) => setHandle(e.target.value)} className="flex-1" />
        <Button variant="primary" type="submit">Scan now →</Button>
      </form>
      {results && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-px bg-[var(--color-border)] border border-[var(--color-border)] max-w-2xl">
          {results.map((r, i) => (
            <div key={i} className="bg-[var(--color-surface)] aspect-square p-2 relative">
              <div className="absolute inset-2 bg-[var(--color-bg)] border border-[var(--color-border)]" />
              <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between text-[10px]">
                <span className={r.detected ? 'text-[var(--color-good)]' : 'text-[var(--color-ink-subtle)]'}>
                  {r.detected ? '✓ hit' : '— miss'}
                </span>
                <span className="tabular-nums text-[var(--color-ink-muted)]">{(r.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
