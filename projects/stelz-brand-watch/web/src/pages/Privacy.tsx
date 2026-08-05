import type { ReactNode } from 'react'
import { Logo } from '../components/ui'

export default function Privacy() {
  return (
    <LegalShell title="Privacy Policy" updated="Last updated: 13 May 2026 · JackandAI B.V., Amsterdam, the Netherlands">
      <LegalSection n={1} title="What information we collect">
        Account data (email, name), brand setup (slug, hashtags, reference images), public social content we
        scan on your behalf, usage telemetry, and billing data processed by Stripe.
      </LegalSection>
      <LegalSection n={2} title="How we use your information">
        To run scans on your behalf, generate dashboards and reports, process payments, improve detection
        accuracy, and communicate service updates.
      </LegalSection>
      <LegalSection n={3} title="Legal basis (GDPR)">
        Contract (Article 6.1.b) for delivering the service, legitimate interest (6.1.f) for usage analytics
        and product improvement, and consent (6.1.a) for marketing communications.
      </LegalSection>
      <LegalSection n={4} title="Sharing with third parties">
        Processors we use: Supabase (database, auth), Vercel (hosting), Railway (workers), Apify (data
        sourcing), Google AI (Gemini, vision detection), Stripe (payments). We never sell your data.
      </LegalSection>
      <LegalSection n={5} title="Data retention">
        Monitoring data: kept while your subscription is active, then deleted 30 days after cancellation.
        Account data: 2 years after last activity.
      </LegalSection>
      <LegalSection n={6} title="Public creator content">
        If a creator wants to be excluded from our scans, email{' '}
        <a className="underline" href="mailto:privacy@jackandai.com">privacy@jackandai.com</a>. We process
        exclusion requests within 7 business days.
      </LegalSection>
      <LegalSection n={7} title="Your rights">
        Access, rectification, erasure, portability, and objection. You can complain to the Autoriteit
        Persoonsgegevens (Dutch DPA) if we don't respond satisfactorily.
      </LegalSection>
      <LegalSection n={8} title="Security">
        HTTPS everywhere, OAuth-based authentication, encryption at rest, secret rotation every 3 months.
        SOC 2 Type 1 preparation targeted for Q4 2026.
      </LegalSection>
      <LegalSection n={9} title="Cookies">
        Essential cookies only. No analytics or advertising trackers.
      </LegalSection>
      <LegalSection n={10} title="Changes">
        Material changes announced 30 days in advance via email.
      </LegalSection>
      <LegalSection title="Contact">
        <a className="underline" href="mailto:privacy@jackandai.com">privacy@jackandai.com</a>
      </LegalSection>
    </LegalShell>
  )
}

export function LegalShell({
  title,
  updated,
  children,
}: {
  title: string
  updated: string
  children: ReactNode
}) {
  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <header className="h-14 px-10 border-b border-[var(--color-border)] flex items-center bg-[var(--color-surface)]">
        <Logo small />
        <a href="/landing" className="ml-auto text-[12px] text-[var(--color-ink-muted)]">← Back</a>
      </header>
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="text-[36px] font-medium tracking-tight mb-2">{title}</h1>
        <div className="text-[12px] text-[var(--color-ink-subtle)] mb-12">{updated}</div>
        <div className="space-y-10 text-[14px] leading-relaxed text-[var(--color-ink)]">{children}</div>
      </div>
    </div>
  )
}

export function LegalSection({ n, title, children }: { n?: number; title: string; children: ReactNode }) {
  return (
    <section>
      <div className="flex items-baseline gap-3 mb-3">
        {typeof n === 'number' && (
          <span className="text-[11px] uppercase tracking-widest text-[var(--color-ink-subtle)] tabular-nums">
            {String(n).padStart(2, '0')}
          </span>
        )}
        <h2 className="text-[18px] font-medium tracking-tight">{title}</h2>
      </div>
      <div className="text-[var(--color-ink-muted)]">{children}</div>
    </section>
  )
}
