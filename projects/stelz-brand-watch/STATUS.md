# Lens — Live Status

**Datum:** 13 mei 2026
**Status:** Productie-ready voor STELZ als demo + onboarding klaar voor eerste klanten.

## Live URLs (allemaal public)

| Pagina | URL |
|--------|-----|
| Landing | https://stelz-brand-watch.vercel.app/landing.html |
| Signup (OAuth) | https://stelz-brand-watch.vercel.app/signup.html |
| Login | https://stelz-brand-watch.vercel.app/login.html |
| Onboarding wizard | https://stelz-brand-watch.vercel.app/onboarding.html |
| Checkout placeholder | https://stelz-brand-watch.vercel.app/checkout.html |
| Privacy Policy | https://stelz-brand-watch.vercel.app/privacy.html |
| Terms of Service | https://stelz-brand-watch.vercel.app/terms.html |
| **STELZ demo dashboard** | https://stelz-brand-watch.vercel.app/ |

## Backend status

### Supabase Database (productie)
- **Brands**: 1 (STELZ Enterprise)
- **Plans**: 3 (Starter €500, Pro €1500 met Stripe price IDs, Enterprise custom)
- **Subscriptions**: 1 (STELZ Enterprise active until 2027)
- **Credit balances**: STELZ heeft 10.000 credits
- **Creators tracked**: 915 (371 auto-archived irrelevant, 545 active)
- **Detections**: 6.911 totaal (v1+v3+v4+v5+sentiment)
- **Clear product hits**: 436 confirmed, 432 Pro-verified
- **Image cache**: 3.140 thumbnails in Storage

### Stripe (TEST mode)
- Product "Lens Starter" → price_1TWZvD9PujtsRuoO11icZ7RI (€500/mo)
- Product "Lens Pro" → price_1TWZw29PujtsRuoO140kZ8Qj (€1500/mo)
- Linked in `plans.stripe_price_id`
- TODO Edge Function voor checkout sessions + webhooks (zie saas-launch-plan.md)

### Railway daily pipeline
- Cron: `0 6 * * *` UTC (08:00 NL)
- Chains: auto_add → daily_scan → ai_score_creators → auto_prune
- Last run: yesterday 07:02 (75 new images)
- Cost: ~€5/maand Railway + variable Apify/Gemini

## Tools / scripts gebouwd

### Discovery & detection
- `01_scrape_pilot.py` — Apify hashtag scrape proof
- `02_detect_pilot.py` — Gemini Flash baseline
- `03_discover_creators.py` — v1 brand hashtag discovery
- `04_discover_lifestyle.py` — v2 broad NL lifestyle discovery
- `05_discover_official.py` — @drinkstelz audience (failed, IG loginwall)
- `06_visual_scan.py` — original visual scanner
- `07_rerank_persons.py` — person-bias re-rank
- `08_visual_scan_fast.py` — asyncio parallel (4-20x sneller)
- `10_cache_images.py` — Supabase Storage thumbnail cache
- `11_rescan_v3.py` — strikter prompt v3 rescan
- `12_full_stelz_harvest.py` — large-scale #stelz family
- `13_popular_nl_creators.py` — 60 mainstream NL handpicked
- `14_detect_new.py` — incremental detection
- `15_tiktok_harvest.py` — TikTok hashtag scrape
- `16_detect_v4_logo_focus.py` — v4 prompt + rich references (657 hits)
- `17_verify_with_pro.py` — Pro verify pass (33% FP rate caught)

### Intelligent pipeline
- `18_daily_scan.py` — daily refresh seed list
- `19_auto_add.py` — hashtag → discovery_queue → auto-promote
- `20_auto_prune.py` — tier promote/demote/archive
- `21_ai_score_creators.py` — Gemini Flash relevance 0-10
- `22_perplexity_scout.py` — weekly web intelligence (vond Monica Geuze als shareholder)
- `23_auto_report.py` — weekly/monthly markdown report
- `24_sentiment_analysis.py` — positive/neutral/negative/promotional per detection
- `25_provision_brand.py` — signup_leads → brand + subscription + credits
- `26_setup_stripe.py` — Stripe products + prices

### Railway deployment
- `railway/Dockerfile` + `railway.toml` (cron schedule)
- `railway/daily_pipeline.sh` (chained scripts)

## Dashboard features

### Detections view
- Realtime feed met "LIVE" pulsing indicator + auto-refresh 60s
- Time tiles: Today / This week / This month + trend chart (Day/Week/Month toggle)
- Source signal badges: brand-owned / hashtag / mention / visual-only
- Sentiment badges: positive / neutral / negative / promotional
- AI relevance score pill per creator (0-10)
- Creator tier badge (tier_1 / tier_2 / tier_3)
- Image thumbnails (3.140 in cache, 99% coverage)
- Captions + clickable hashtag chips per row
- Date range filter + presets (7d / 30d / 90d / 1y / all)
- Posted-date per row, newest-first sort
- Search across handle, caption, context, hashtags
- CSV export

### Creators view (tab)
- Lijst van 545 actieve creators
- Per row: handle, platform, category, tier, AI score, followers, posts scanned, hits, latest post
- Search en CSV export
- "View hits →" button springt naar detections gefilterd op die creator

### Header
- Scan history dropdown: laatste 15 scans (daily_scan, auto_prune, perplexity_scout) met status en duration
- Live status indicator + new-since-last-refresh counter

## SaaS components live

### Authentication
- Supabase Auth schema actief
- Signup page met Google + Meta OAuth buttons (UI klaar)
- Email/password fallback werkend via Supabase Auth
- **TODO Meinte**: koppel Google OAuth en Meta OAuth providers in Supabase dashboard (zie `oauth-setup.md`)

### Onboarding
- 4-stap wizard live met brand info + product lines + hashtags + plan + premium backfill toggle
- Writes to `signup_leads` table
- Brand provisioning script (`25_provision_brand.py`) maakt brand + subscription + credits van een lead

### Billing
- Stripe products + prices live in TEST mode
- Plans table heeft stripe_price_id voor Starter en Pro
- Checkout placeholder UI klaar
- **TODO Fase 2**: Supabase Edge Function voor checkout sessions + webhooks

### Reports
- `23_auto_report.py` genereert markdown reports per brand per periode
- Schrijft naar `reports` tabel
- **TODO Fase 2**: email/PDF delivery via Resend + headless Chrome

### Backfill premium
- `backfill_jobs` tabel klaar
- Wizard heeft "+€2.500 backfill 1 year" toggle
- **TODO Fase 2**: worker die backfill jobs processed (credits afschrijft + extended scrape)

## Documentation

| Bestand | Inhoud |
|---------|--------|
| `README.md` | Project overview |
| `spec.md` | Pipeline architecture |
| `scale-architecture.md` | Multi-tenant scale plan |
| `saas-launch-plan.md` | Fase 2 backlog en cost model |
| `oauth-setup.md` | Google/Meta provider setup stappen |
| `pilot-report.md` | Pilot resultaten gisteren |
| `night-report.md` | Overnight sprint resultaten |
| `upgrade-report.md` | Tier systeem + AI scoring + Perplexity |
| `STATUS.md` | Dit bestand |

## Wat NU werkt voor een echte demo

1. Open https://stelz-brand-watch.vercel.app/landing.html
2. Klik "Start free trial" → naar signup page
3. Sign up met email/password (OAuth UI klaar maar providers nog niet gekoppeld)
4. Doorlopen naar onboarding wizard
5. Vul brand info, product lines, hashtags in
6. Selecteer plan
7. Lead landt in `signup_leads` tabel
8. Run `python3 tools/stelz_brand_watch/25_provision_brand.py --all-pending` om brand provisioning te doen
9. Brand heeft nu Supabase row + 14-dag trial + 100 credits
10. Klant kan dashboard openen

## Fase 2 — wat productie nodig heeft

Volledig in `saas-launch-plan.md`. Korte versie:
1. **Auth providers koppelen** (Google + Meta) → 30 min Meinte werk
2. **Stripe Checkout Edge Function** → 1 dag dev werk
3. **Stripe Webhook handler** → 1 dag dev werk
4. **Auto-report email delivery** (Resend) → 4 uur dev werk
5. **Backfill worker** → 1 dag dev werk
6. **RLS policies in Supabase** (multi-tenant security) → 1 dag dev werk
7. **Multi-tenant URL routing** /app/[slug] → 1 dag dev werk

Totaal naar productie-launch: ~5 werkdagen.

## Cost vandaag

| Component | Bedrag |
|-----------|--------|
| Apify (pilot + discovery + harvests) | ~€20 |
| Gemini Flash (detection + sentiment + scoring) | ~€10 |
| Gemini Pro (verify pass) | ~€3 |
| Perplexity (scout) | ~€1 |
| Stripe (test mode) | €0 |
| Supabase Pro | €0 (free tier nog) |
| Vercel Pro | €0 (free tier) |
| Railway | €0 (free trial credit) |
| **Totaal** | **~€34** |
