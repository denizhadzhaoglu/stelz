import { LegalSection, LegalShell } from './Privacy'

export default function Terms() {
  return (
    <LegalShell title="Terms of Service" updated="Last updated: 13 May 2026 · JackandAI B.V., Amsterdam">
      <LegalSection n={1} title="The service">
        Spot the Brand is an AI-powered brand monitoring platform operated by JackandAI B.V. ("we", "us").
        It scans public social content (currently Instagram and TikTok) to detect visual mentions of your
        brand and rank creators by relevance.
      </LegalSection>
      <LegalSection n={2} title="Account and access">
        Accounts are intended for users 18 and older. You're responsible for keeping your credentials secure.
        One subscription covers one brand workspace. Account sharing across organizations is not permitted.
      </LegalSection>
      <LegalSection n={3} title="Subscriptions and payment">
        Subscriptions are billed monthly via Stripe. A 14-day free trial is available on first signup.
        Cancellation is effective at the end of the current billing period. VAT is added where applicable.
        Failed payments may pause your scans until resolved.
      </LegalSection>
      <LegalSection n={4} title="Credits">
        Each plan includes a monthly credit allowance for scans and detections. Unused credits roll over for
        one month, then expire.
      </LegalSection>
      <LegalSection n={5} title="Acceptable use">
        You agree not to: harass creators, resell our data, or use the service to scrape content for purposes
        unrelated to brand monitoring. We may suspend accounts that violate these terms.
      </LegalSection>
      <LegalSection n={6} title="Data ownership">
        You own the configuration and reference data you upload. We own the detection metadata we produce.
        You may export all data anytime. After cancellation we retain your data for 30 days, then delete it.
      </LegalSection>
      <LegalSection n={7} title="Service availability">
        We target 99.5% uptime. Scheduled maintenance is announced 48 hours in advance. SLA credits are
        available on Enterprise plans.
      </LegalSection>
      <LegalSection n={8} title="Third-party services">
        We rely on Instagram and TikTok as data sources. Their APIs may change without notice; we'll provide
        7 days' notice where possible if affected.
      </LegalSection>
      <LegalSection n={9} title="Limitation of liability">
        The service is provided as-is. We don't guarantee detection accuracy. Maximum liability is capped at
        12 months of fees paid.
      </LegalSection>
      <LegalSection n={10} title="Termination">
        You can cancel anytime via the dashboard. We may terminate accounts for violation of these terms or
        non-payment.
      </LegalSection>
      <LegalSection n={11} title="Confidentiality">
        You agree not to share detection data publicly in a way that identifies our platform as the source
        without permission.
      </LegalSection>
      <LegalSection n={12} title="Governing law">
        These terms are governed by Dutch law. Disputes are resolved in the courts of Amsterdam.
      </LegalSection>
      <LegalSection n={13} title="Changes">
        We may update these terms. Material changes are announced via email at least 30 days before they take
        effect.
      </LegalSection>
      <LegalSection title="Contact">
        Questions: <a className="underline" href="mailto:legal@jackandai.com">legal@jackandai.com</a>
      </LegalSection>
    </LegalShell>
  )
}
