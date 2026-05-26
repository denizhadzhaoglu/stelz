# Stripe Live Mode Checklist

Status: ⏳ Wacht op Meinte
Laatst bijgewerkt: 2026-05-19

---

## Fase 1: Meinte doet (~10 min)

Open https://dashboard.stripe.com en toggle "Test mode" UIT.

Stripe vraagt "Activate payments". Vul in:

- [ ] Business type: Eenmanszaak of BV
- [ ] KvK nummer
- [ ] Vestigingsadres
- [ ] IBAN voor payouts
- [ ] BTW nummer (indien van toepassing)
- [ ] Identiteitsverificatie (foto ID)
- [ ] Submit → meeste NL accounts worden direct goedgekeurd

Als het live is, stuur Hermes:
1. De nieuwe `sk_live_xxx` key
2. De nieuwe `pk_live_xxx` key

---

## Fase 2: Hermes doet na goedkeuring (~30 min)

### A. Setup script bouwen (MOET NOG GEMAAKT WORDEN)
- [ ] `26_setup_stripe.py --live` script schrijven
  - Products aanmaken: Starter, Pro, Enterprise
  - Prices: €500/mo, €1.500/mo, custom
  - Backfill `plans.stripe_price_id` in Supabase naar live IDs
  - Premium backfill add-on: €2.500 eenmalig

### B. Supabase Edge Functions (MOETEN NOG GEMAAKT WORDEN)
- [ ] `create-checkout-session` function schrijven
  - Ontvangt plan keuze, maakt Stripe Checkout Session
  - Redirect naar success/cancel URL
- [ ] `stripe-webhook` function schrijven
  - Events: checkout.session.completed, customer.subscription.*, invoice.payment_failed
  - Update subscription status in Supabase

### C. Keys & Secrets updaten
- [ ] PA/.env: STRIPE_SECRET_KEY → sk_live_xxx
- [ ] PA/.env: STRIPE_PUBLISHABLE_KEY → pk_live_xxx  
- [ ] PA/.env: STRIPE_PRICE_ID → nieuwe live price IDs (per tier)
- [ ] Supabase Edge Function secrets:
  - STRIPE_SECRET_KEY=sk_live_xxx
  - STRIPE_WEBHOOK_SECRET=whsec_xxx (van webhook setup)

### D. Webhook configureren
- [ ] Stripe dashboard → Webhooks → Add endpoint:
  - URL: https://menaatbeoeutywulcdvv.supabase.co/functions/v1/stripe-webhook
  - Events: checkout.session.completed, customer.subscription.created, customer.subscription.updated, customer.subscription.deleted, invoice.payment_failed
  - Kopieer whsec_xxx signing secret

### E. Frontend updaten
- [ ] "Test mode" banner verwijderen uit checkout pages
- [ ] Checkout buttons koppelen aan echte Stripe Checkout Sessions
- [ ] Publishable key updaten in frontend code

### F. Testen
- [ ] Eén echte checkout starten (€0.50 test of Starter plan)
- [ ] Webhook delivery verifiëren in Stripe dashboard
- [ ] Subscription record checken in Supabase
- [ ] Cancel flow testen

---

## Gaps die ik eerst moet bouwen

| # | Wat | Geschatte tijd | Blocker? |
|---|-----|---------------|----------|
| 1 | 26_setup_stripe.py script | 1-2 uur | Ja -- nodig voor product/price setup |
| 2 | create-checkout-session Edge Function | 2-3 uur | Ja -- nodig voor echte checkout |
| 3 | stripe-webhook Edge Function | 2-3 uur | Ja -- nodig voor subscription tracking |
| 4 | Frontend checkout flow herschrijven | 1-2 uur | Ja -- momenteel stub/simulated |
| 5 | Price IDs per tier (3x) | 10 min | Na script |

**Totaal: ~7-10 uur development voordat Stripe echt live kan.**

---

## Aanbeveling

Meinte, je kunt de Stripe activatie (Fase 1) nu al doen -- dat kost 10 minuten en is onafhankelijk van de development. Zodra je dat gedaan hebt en mij de live keys geeft, bouw ik Fase 2 en hebben we alles binnen 1-2 dagen werkend.

Prioritering:
1. **Jij:** Stripe activatie (10 min, kan vandaag)
2. **Ik:** Edge Functions + setup script bouwen (kan ik starten zonder live keys)
3. **Samen:** Testen met eerste echte checkout
