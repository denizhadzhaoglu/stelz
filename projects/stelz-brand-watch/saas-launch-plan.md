# Lens — SaaS Launch Plan

**Status:** Foundation built, productisatie incompleet
**Date:** 2026-05-13

## Wat staat live nu

### Public landing
- **Marketing site**: https://stelz-brand-watch.vercel.app/landing.html
  - Hero, problem statement, how-it-works (4 stappen), 8 features, demo CTA naar STELZ dashboard, 3-tier pricing, signup form, FAQ.
  - Signup formulier schrijft naar `signup_leads` table in Supabase.
  - Geen concurrenten genoemd. Positionering rond computer vision + AI relevantie scoring + visual-only detectie.

- **Onboarding wizard**: https://stelz-brand-watch.vercel.app/onboarding.html
  - 4 stappen: brand info → product lines + reference upload → hashtags + competitors → plan + premium backfill.
  - Eindigt met success screen en Stripe checkout link (placeholder).
  - Schrijft alles naar `signup_leads` met notes JSON-blob.

- **Checkout placeholder**: https://stelz-brand-watch.vercel.app/checkout.html
  - Plan summary, trial info, Stripe TEST mode banner.
  - Button is placeholder: vereist Edge Function in productie.

### Demo
- **STELZ dashboard**: https://stelz-brand-watch.vercel.app/
  - 436 detections, 545 actieve creators, 4 product lines, daily auto-scan, realtime feed.
  - Public toegankelijk, geen login.
  - STELZ behoudt automatisch Enterprise subscription (10k credits).

### Backend
- **Supabase Postgres** met SaaS schema: `plans`, `subscriptions`, `credit_balances`, `credit_transactions`, `brand_users`, `backfill_jobs`, `reports`, `signup_leads`.
- **Railway daily pipeline**: 06:00 UTC auto-add → daily scan → AI scoring → auto-prune.
- **Auto-report script** (`23_auto_report.py`) genereert markdown/json reports per brand per periode.
- STELZ Enterprise plan + 10k credits seeded.

## Wat fase 2 is (echte productie launch)

### Auth & multi-tenant routing (CRITICAL)
- [ ] Supabase Auth setup: email + Google login
- [ ] `brand_users` linkage met `auth.users`
- [ ] Multi-tenant URL routing: `/app/[brand-slug]` ipv vaste STELZ dashboard
- [ ] Server-side auth check before showing brand data
- [ ] Row Level Security policies aanzetten in Supabase (nu OFF voor pilot)

### Stripe live integratie (CRITICAL)
- [ ] Stripe account in business mode (NL VAT setup)
- [ ] Producten + prices aanmaken in Stripe (Starter, Pro, Enterprise)
- [ ] Stripe Checkout via Supabase Edge Function:
  1. Onboarding → POST naar `/api/create-checkout`
  2. Edge Function maakt Stripe Checkout Session
  3. Returns session URL → frontend redirect
- [ ] Stripe Webhook handler:
  - `checkout.session.completed` → activeer subscription
  - `customer.subscription.updated` → sync status
  - `customer.subscription.deleted` → cancel/disable brand
  - `invoice.payment_failed` → mark past_due
- [ ] Customer Portal voor self-service (upgrade/downgrade/cancel)

### Brand provisioning pipeline
- [ ] Sign-up → automatisch `brands` record met slug, plan, trial period
- [ ] AI generates hashtag pool suggestions uit `notes`
- [ ] Reference image upload naar Supabase Storage bucket per brand
- [ ] Initial discovery run triggered automatic na onboarding completion
- [ ] Welcome email met dashboard link + onboarding call link

### Backfill premium feature
- [ ] Backfill request creates row in `backfill_jobs` met days requested
- [ ] Background worker pakt jobs en runt extended scrape
- [ ] Credits worden afgeschreven: ~50 credits per dag historie
- [ ] Job status update naar dashboard
- [ ] Email notification when done

### Auto-report delivery
- [ ] Schedule per brand (daily voor Pro, weekly voor Starter)
- [ ] HTML email template met de markdown insights renderd
- [ ] PDF export via headless Chrome (Puppeteer in Vercel Function)
- [ ] Recipients lijst in `brand_users` table
- [ ] Slack integratie voor Pro+ tier

### Multi-tenant dashboard
- [ ] Brand selector in dashboard nav als user multi-brand access heeft
- [ ] Per-brand RLS policies in Supabase
- [ ] Brand-specific reference images upload + management UI
- [ ] Brand-specific hashtag pool editor

### Operationeel
- [ ] Status page (statuspage.io)
- [ ] Customer support: Plain.com of Intercom
- [ ] Analytics: Plausible of PostHog
- [ ] Error tracking: Sentry
- [ ] SOC2 prep (Vanta/Drata) voor enterprise sales

### Pricing flexibiliteit
- [ ] Credit top-up flow (extra credits kopen via Stripe)
- [ ] Yearly billing met 20% korting
- [ ] Multi-brand korting (3+ brands = -25%)
- [ ] Custom enterprise SOWs

## Inschatting effort fase 2

Met 1 fulltime developer (Lukas of Yassin):
- **Week 1**: Supabase Auth + multi-tenant routing + RLS policies
- **Week 2**: Stripe live integratie + webhook handler + Edge Functions
- **Week 3**: Brand provisioning + reference upload + initial discovery trigger
- **Week 4**: Auto-report email/PDF + backfill worker + dashboard polish
- **Week 5**: Customer portal + analytics + error tracking
- **Week 6**: Launch readiness + 2 pilot klanten onboarden

Totaal: 6 weken naar productie-launch met 2-3 pilot klanten.

## Cost model bij 10 brand klanten (gemiddeld Pro)

- Apify @ €100/brand: €1.000/maand
- Gemini Flash @ €30/brand: €300/maand
- Gemini Pro verify @ €15/brand: €150/maand
- Supabase Pro: €25/maand
- Vercel Pro: €20/maand
- Railway: €25/maand
- Perplexity API: €50/maand
- **Total cost: ~€1.570/maand**

Revenue: 10 × €1.500 = **€15.000 MRR**.

**Gross margin: ~89%**. Echte SaaS economics.

## Risico's

- **Instagram scraping TOS**: Apify werkt nu maar Meta kan platform-API beleid wijzigen. Mitigatie: fallback actors, mogelijk eigen scraping infra met session cookies.
- **Gemini hallucinaties**: nu 33% FP rate op v4, 0% na Pro verify. Continuous monitoring nodig.
- **GDPR/AVG**: scraping van personal Instagram accounts vereist DPA review. Voor B2B brand monitoring acceptabel argument: legitimate interest. Wel duidelijke privacy policy nodig.
- **Schaalbaarheid Supabase**: huidige Pro plan tot ~10M rows. Bij 50 brands waarschijnlijk upgrade naar Team plan.

## STELZ als referentie klant

Aanpak: STELZ behoudt Enterprise toegang gratis als design partner. Hun feedback drijft v5 features. Hun dashboard URL blijft public als demo zolang ze akkoord zijn.

Plus: STELZ founder Milan Voet of Glenn Cornelisse vragen voor testimonial quote op landing page.

## Naamgeving open

"Lens" is werknaam. Alternatieven:
- BrandPulse, Beacon, BrandLens, Resonate, Signal, Brandsight, Witness
- "Lens by JackandAI" past bij JackandAI productized intelligence layer

Aanbeveling: trademark search voor "Lens" — kan een conflicting brand zijn. Eventueel domain checken (lens.ai, getlens.io, etc).
