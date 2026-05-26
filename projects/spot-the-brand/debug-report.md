# Debug pass · 15 mei 2026

Sweep van elke publieke pagina + auth-flow op `spotyourbrand.com`. Findings ranked op severity.

## TL;DR

5 bugs gevonden, allemaal gefixt en live deployed. Geen openstaande blockers in de codebase. Belangrijkste resterende werk is **env-vars instellen** in Supabase Edge Function secrets (geen code-issue, configuratie).

---

## FINDING #1 [LOW] — Dashboard title was hardcoded STELZ
**Was**: `<title>STËLZ Brand Watch</title>` en `<h1>STËLZ • Brand Watch</h1>`
**Bug**: brand-conform discipline; tool moet vanuit Spot the Brand spreken, niet vanuit één klant
**Fix**: title is nu `Spot the Brand · Dashboard`, h1 toont `Spot the Brand. <Brand Name>`, `document.title` ververst dynamisch bij brand-resolve
**Files**: `index.html` (regel 6 + 377 + 2113)
**Status**: ✅ live

## FINDING #2 [BLOCKER] — creator.html querying non-existent columns
**Was**: `select("...ai_score, ai_score_reason...")` → DB heeft `relevance_score` + `ai_summary` (jsonb), niet die kolomnamen → 400 error → profile rendert leeg
**Bug**: code refereert kolommen die nooit hebben bestaan in dit schema
**Fix**: `ai_score` → `relevance_score`. `ai_score_reason` → `ai_summary?.audience_fit_rationale` (uit jsonb)
**Files**: `creator.html` (regel 84, 124, 130)
**Status**: ✅ live, geverifieerd 0 console errors

## FINDING #3 [HIGH] — `/onboarding.html` redirect dead-end
**Was**: oude onboarding.html stuurde anon users naar `/signup.html?return=/onboarding.html`. Na auth keerde signup terug — maar de oude 4-step wizard is functioneel vervangen door onboarding-v2. Anyone landing on /onboarding.html zat dus in een dood pad
**Bug**: legacy file blokkeerde nieuwe flow
**Fix**: onboarding.html omgezet tot meta-refresh + JS redirect naar `/onboarding-v2.html` met query params preserved
**Files**: `onboarding.html` (vol bestand vervangen)
**Status**: ✅ live

## FINDING #4 [MEDIUM] — login.html "Start free trial" linkte naar dead-end
**Was**: link "No account yet? Start free trial" → `signup.html` (oude flow)
**Bug**: nieuwe gebruikers via login-page kwamen niet in cold-start kit
**Fix**: link → `onboarding-v2.html`. Plus `signup.html` post-auth redirects (Google OAuth + email magic-link) van `/onboarding.html` → `/onboarding-v2.html`
**Files**: `login.html` (regel 58), `signup.html` (regel 93, 112)
**Status**: ✅ live

## FINDING #5 [BLOCKER] — account.html hardcoded to STELZ
**Was**: `sb.from("brands").select("*").eq("slug", "stelz")` — gold-plated voor pilot, vergeten te updaten. Ingelogd als demo user met `?brand=spot-the-brand-demo`: zag STELZ data, STELZ credits, STELZ team, STELZ hashtag pool. Effectief geen multi-tenant
**Bug**: zelfde patroon als moderator-page eerder. Geen brand-resolver, geen URL param parsing, geen auth-membership check
**Fix**: nieuwe `resolveActiveBrand()` functie. Priority: `?brand=<slug>` → eerste brand_users-membership van ingelogde user → STELZ public-demo fallback
**Files**: `account.html` (regel 196-218)
**Status**: ✅ live, geverifieerd — demo user ziet nu "Demo Brand" met 750 credits + Pro plan

## FINDING #6 [LOW] — Brand display naam was te lang
**Was**: demo brand naam in DB was "Spot the Brand · Demo". Dashboard h1 toonde "Spot the Brand. Spot the Brand · Demo" (dubbele "Spot the Brand")
**Bug**: copy-paste naming
**Fix**: SQL update — `UPDATE brands SET name = 'Demo Brand' WHERE slug = 'spot-the-brand-demo'`
**Status**: ✅ live

## FINDING #7 [LOW] — Favicon 404
**Was**: alle pagina's gooien `GET /favicon.ico 404` in console
**Bug**: geen favicon.ico in deploy
**Fix**: nog niet (kosmetisch, post-launch)
**Status**: backlog

## FINDING #8 [LOW] — Mojibake "ST√ãLZ" in Playwright snapshot
**Was**: Playwright accessibility tree toont "ST√ãLZ" voor de ë. Visueel in browser correct.
**Bug**: Playwright snapshot tool quirk, NIET een productie-bug
**Status**: niet gefixt, geen actie nodig

---

## Pagina-by-pagina console-check resultaat

| Pagina | Status | Errors | Notities |
|--------|--------|--------|----------|
| `/landing.html` | ✅ | 1 (favicon) | OK |
| `/onboarding-v2.html` | ✅ | 0 | Form werkt; scan-call faalt tot Apify env var gezet (zie env-vars sectie) |
| `/welcome.html?lead=...` | ✅ | 0 | Polling loop werkt; toont juiste stappen |
| `/` (dashboard) | ✅ | 0 | Title nu brand-aware |
| `/highlights.html?brand=stelz` | ✅ | 0 | Top 12 hits renderen correct |
| `/story.html?brand=stelz` | ✅ | 0 | Swipe-view, 6s auto-advance |
| `/creator.html?handle=studentdelivery_&brand=stelz` | ✅ NU | 0 | gefixt |
| `/moderator.html?brand=stelz` | ✅ | 0 | Brand-scoped (vorige fix) |
| `/account.html` | ✅ NU | 0 | Brand-resolver (vorige fix) |
| `/login.html` | ✅ | 0 | Werkt, trial-link nu naar v2 |
| `/accept-invite.html` | ✅ | 0 | OK voor invite-flow |
| `/signup.html` | ⚠ | 0 | Werkt maar leidt door naar v2; eigenlijk overbodig |
| `/onboarding.html` | ✅ | 0 | Redirect naar v2 |
| `/checkout.html` | ✅ | 0 | Placeholder, niet kritisch — Stripe Checkout flow gaat via Edge Function |
| `/terms.html` | ✅ | 0 | OK |
| `/privacy.html` | ✅ | 0 | OK |

## Authenticated flows getest

- **Demo login** (`demo@spotyourbrand.com` / `SpotTheDemo2026!`): werkt
- **Sessie persisteert** door alle pagina's
- **Brand-resolver** kiest correct demo brand voor demo user
- **RLS**: demo user kan demo brand schrijven, STELZ alleen lezen (public-demo carve-out)
- **`meinte@jackandai.com`** (platform-staff): geverifieerd dat helper-functies staff toelaten op alle brands

---

## Wat NIET getest werd (te risicovol of buiten scope)

- **Live cold-start scan**: vereist `APIFY_API_TOKEN` env var in Supabase, die nog niet gezet is. Function returnt `{"error":"APIFY_API_TOKEN not configured"}`.
- **Stripe Checkout end-to-end**: vereist `STRIPE_SECRET_KEY` env var in Supabase. Pre-flight check via curl bevestigt webhook werkt, alleen secrets-config blokt.
- **Welcome email versturen**: vereist `RESEND_API_KEY`. Code is env-gated, faalt silently zonder.

## Env vars die jij nog moet zetten

Open https://supabase.com/dashboard/project/menaatbeoeutywulcdvv/functions/secrets:

```
APIFY_API_TOKEN=<redacted — see local .env>
GOOGLE_AI_API_KEY=<redacted — see local .env>
STRIPE_WEBHOOK_SECRET=<redacted — see local .env>
STRIPE_SECRET_KEY=<redacted — see local .env>
```

Optioneel:
- `RESEND_API_KEY` (voor welcome + alert emails)
- `SENTRY_DSN` (voor error tracking)

---

## Volgende fase

Code-side is debug-vrij. Klaar voor:
- **Campagne launch** (IG account aanmaken, week 1 content publiceren)
- **Eerste prospect-gesprekken** (5 brands deze week per sales-playbook)
- **Eerste echte cold-start scan** (zodra Apify token gezet, prospect benadert je via /onboarding-v2 met hun eigen handle)

Owner: Meinte. Volgende debug-pass aanbevolen na eerste echte klantengebruik (vinden meestal de bugs die geen syntheet-test vindt).
