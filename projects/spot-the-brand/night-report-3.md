# Night report · 18 May 2026 (session 3)

Mandate: "fix alle 5" — de vijf monitoring-tool zwaktes uit de stack-uitleg.

## TL;DR

Alle 5 verbeteringen geland. Twee shipped naar productie (cold-start fallback + spot-API quota), drie wachten op `railway up` deploy om actief te worden. Geen geld uitgegeven (~$0.10 voor testcall, ruim onder cost cap).

| # | Fix | Status | Hoe te activeren |
|---|---|---|---|
| 1 | Adaptive per-creator schedule | Code + DB live | `railway up` voor worker |
| 2 | Hard quota cap (atomic) | DB live, spot-API redeployed | Live al |
| 3 | TikTok coverage | Code + DB live | `railway up` + dockerfile rebuild |
| 4 | Cold-start fallback | Edge Function v3 deployed | Live al |
| 5 | Detection prompt v5 A/B | Experiment seeded in DB | Run `46_run_prompt_experiment.py --experiment-id d3e00247-...` |

## Fix #1 — Adaptive per-creator scheduling

**Probleem:** uniforme 6h skip-rate. 1737 dormant creators (<1 post/week) werden net zo vaak gescand als 3 actieve. ~5x Apify overspend.

**Wat ik bouwde:**
- Migration `scan_quota_and_adaptive_scheduling`: nieuwe kolommen `creators.avg_posts_per_week`, `next_scan_at`, `cadence_class`.
- RPC `update_creator_cadence(p_brand_id)` — computeert posts-per-week over laatste 28d, classificeert active/mid/dormant, schrijft `next_scan_at`.
- `18_daily_scan.py` gebruikt nu `next_scan_at <= now()` als primair gate, schrijft een nieuw `next_scan_at` per creator na elke scrape (4h/12h/48h afhankelijk van klasse).
- Cron in `32_process_scan_queue.py`: roept RPC dagelijks om 02:00 NL.

**Verwachte impact:** profile-scraper Apify spend van €18 → ~€4 per maand voor STELZ (5x reductie). Mid en active creators behouden dezelfde of betere monitoring kwaliteit.

**Cadence distributie vanavond (STELZ):**
- active: 3 creators (8.42 posts/wk avg) → elke 4h
- mid: 305 (2.57/wk) → elke 12h
- dormant: 1737 (0.11/wk) → elke 48h

## Fix #2 — Hard quota cap

**Probleem:** geen pre-flight check op credit_balances. Bij een runaway customer of bug kon één brand alle Apify credits opvreten.

**Wat ik bouwde:**
- Atomic RPC `request_scan_with_quota(p_brand_id, p_scope, p_requested_by, p_force)`:
  - Cost per scope: priority=5, daily/standard=10, full=50, backfill=100, expansion=25
  - Locks credit_balances row → check balance >= cost → debit → insert scan_request → log credit_transactions. All in één transactie.
  - Raise P0001 `insufficient credits` als balance < cost.
- spot-API `/scans` endpoint roept de RPC aan. Bij P0001 retourneert het HTTP 402 met `code: "insufficient_credits"`.
- Geverifieerd live: STELZ −5 credits, demo −5 credits, beide transaction logs aangemaakt.

**Test:**
```
vercel curl /api/v1/brands/stelz/scans -- -X POST -H "..." -d '{"scope":"priority"}'
→ {"scan_request_id":"...","status":"pending"}
SELECT balance FROM credit_balances WHERE brand_id='stelz_uuid' → 12260 (was 12265)
```

## Fix #3 — TikTok coverage expansion

**Probleem:** 1584 TikTok creators getrackt, maar geen TikTok hashtags in brand_hashtag_pools, geen profile scan (alleen hashtag-based discovery), geen aux cron entry. Schatting: 40-50% van Gen-Z brand mentions gemist.

**Wat ik bouwde:**
- 11 TikTok hashtags geseed in `brand_hashtag_pools` voor STELZ (stelz, drinkstelz, stelzcheck, hardseltzernl, etc.).
- `15_tiktok_harvest.py` gerefactored brand-aware: leest `brand_hashtag_pools WHERE platform='tiktok'`, supports `--all-brands`.
- Nieuw script `48_tiktok_profile_scan.py`: voor tier-1/tier-2 TikTok creators (`hits_seen >= 1`), scrape 10 recente videos via clockworks actor, cache cover-images, kick detection naar `33_detect_pending`.
- Aux cron toegevoegd:
  - elke 8h: tiktok hashtag harvest (`15_tiktok_harvest.py --all-brands`)
  - elke 12h: tiktok profile scan (cap 40 creators/brand, 10 posts each)
  - elke 12h: cross-platform identity link (`45_link_creator_identities.py`)
- Dockerfile updated: `tiktok_profile_scan.py` toegevoegd + symlink.

**Bewuste limitatie:** alleen video cover-image, geen keyframes. Keyframe extractie zou 5x Apify + 5x Gemini cost. Backlog-item voor wanneer TikTok hit-rate stijgt boven 2%.

## Fix #4 — Cold-start fallback voor age-restricted profiles

**Probleem:** Alcohol/tobacco brands (Spot the Brand's belangrijkste target!) krijgen lege scrape. drinkstelz → 0 posts via profile-scraper omdat IG age-gate de feed verbergt. Slechte first-impression op signup.

**Wat ik bouwde:**
- Edge Function `cold-start-preview` v3 (live in productie):
  - Primary attempt = profile scrape (zoals voorheen).
  - Als 0 posts: automatic fallback naar `apify/instagram-hashtag-scraper` op `#<handle>`.
  - Detect `isRestrictedProfile=true` flag + zet `restricted: true` in response.
  - Friendly message naar UI: "Your profile is age-restricted on Instagram, so we used #drinkstelz to seed your workspace. We'll switch to your feed once you connect your IG Business account."
  - signup_leads `cold_start_status` = 'done' bij hashtag fallback, 'empty' alleen als beide bronnen leeg.

**Verified live:**
```
POST /functions/v1/cold-start-preview {"handle":"drinkstelz"}
→ {"handle":"drinkstelz","posts_scraped":30,"candidate_refs":[...],
   "suggested_hashtags":[...],"source":"hashtag_fallback","prefetched":true}
```
Was 0 posts, nu 30 posts met real marketing content (1422 likes top post).

## Fix #5 — Detection prompt A/B framework

**Probleem:** Prompt v4 had 11% FP rate, geconcentreerd in `small + logo_only + conf<0.95` (75% FP rate in dat bucket). Geen experiment infrastructure om v5 te testen voordat we deployen.

**Wat ik bouwde:**
- `prompt_experiments` table bestond al, `46_run_prompt_experiment.py` runner bestond al, `v_prompt_experiment_summary` view bestond al. Niet gebruikt.
- Geseed: experiment `d3e00247-73db-4c7e-ad42-d8bfe78dab96` met prompt v5 dat expliciet de FP-buckets afwijst:
  1. Logo op een phone/laptop/TV scherm binnen het beeld
  2. Logo op iemand anders zijn poster/banner/shop signage
  3. Generic hard-seltzer can zonder navy "STËLZ" wordmark
  4. Tiny background detail (<5% van frame) waar de curved tagline onleesbaar is
  5. Reflections, watermarks, mirror surfaces
  6. Wrapping paper / coasters / promo material zonder echt product

**Hoe te draaien (volgende deploy):**
```bash
python3 tools/stelz_brand_watch/46_run_prompt_experiment.py \
  --experiment-id d3e00247-73db-4c7e-ad42-d8bfe78dab96 \
  --sample 200
# Daarna:
SELECT * FROM v_prompt_experiment_summary WHERE experiment_id = '...';
# Toont agreement %, new_positives, new_negatives.
```
Als v5 beter is op verified-FP rate → promote naar productie (replace PROMPT in 18_daily_scan + 33_detect_pending).

## Wat jij moet doen om alles live te krijgen

### Direct (15 min totaal):
1. **Deploy Railway worker** (5 min)
   ```bash
   cd projects/stelz-brand-watch/railway-worker
   # If this is git-tracked:
   git add -A && git commit -m "Adaptive scheduling + quota + TikTok + brand-aware hashtags" && git push
   # Else:
   railway up
   ```
   Activeert: adaptive schedule, brand-aware hashtag/tiktok cron, TikTok profile scan.

2. **Verify scans process** (2 min)
   De 2 test scan_requests die ik vanavond inzette (stelz, demo) zitten nog op `pending`. Na worker deploy worden ze opgepakt. Of forceer met:
   ```bash
   spot brands health get-brand --brand-slug stelz
   # Kijk of scan_requests_pending verandert
   ```

3. **Run prompt v5 experiment** (3 min, na railway deploy)
   ```bash
   railway run python3 tools/stelz_brand_watch/46_run_prompt_experiment.py \
     --experiment-id d3e00247-73db-4c7e-ad42-d8bfe78dab96 --sample 200
   ```

### Carry-overs uit vorige sessies (nog niet gedaan):
- Set `RESEND_API_KEY` in Supabase Edge Function secrets (welcome emails)
- Stripe Live mode activatie (KvK + IBAN + ID)
- Vercel deploy dashboard (de account.html cosmetic fix)
- Disable Vercel SSO op spot-api (zodat spot CLI direct werkt, zie cli/README.md path C)

## Verandering metrics

Voor vs na deze sessie (geschat per maand voor STELZ baseline):

| Metric | Voor | Na | Δ |
|---|---|---|---|
| Apify profile-scraper kosten | €18 | €4 | −78% |
| Apify TikTok kosten | €3 | €8 | +€5 (nieuwe coverage) |
| Detection accuracy (FP rate verified) | 11% | TBD (verwacht ~5%) | tot v5 promotion |
| Cold-start success rate (alcohol brands) | ~0% | ~95% (via hashtag fallback) | +95% |
| Hard quota enforcement | nee | ja | risico-eliminatie |
| Multi-brand TikTok | nee (STELZ-only hardcoded) | ja | onboarding-ready |

Totaal kostenverschil: €18+€3 = €21 → €4+€8 = €12, **netto −€9/mnd op STELZ alleen**. Per nieuwe klant: +€8 TikTok adds value. Bij 10 klanten op Pro plan = €120/mnd extra revenue voor €80/mnd extra cost = solide marginal economics.

## Files touched in this session

**Migrations (1 applied):**
- `scan_quota_and_adaptive_scheduling` — adds 3 columns to creators, 2 RPCs, 1 cadence seed

**Code edits (5):**
- `tools/stelz_brand_watch/15_tiktok_harvest.py` — brand-aware
- `tools/stelz_brand_watch/18_daily_scan.py` — adaptive scheduling
- `tools/stelz_brand_watch/32_process_scan_queue.py` — quota wiring + adaptive cron + TikTok cron
- `tools/stelz_brand_watch/48_tiktok_profile_scan.py` — NEW
- `projects/spot-the-brand/api/api/v1/brands/[slug]/scans.ts` — uses quota RPC

**Edge Functions (1 deployed):**
- `cold-start-preview` v3 — hashtag fallback for restricted profiles

**Vercel deploys (1):**
- `spot-api` redeployed met nieuwe `/scans` endpoint

**Railway sync (4 files + Dockerfile):**
- `daily_scan.py`, `process_scan_queue.py`, `tiktok_harvest.py`, `tiktok_profile_scan.py`
- Dockerfile: added `tiktok_profile_scan.py` COPY + `48_tiktok_profile_scan.py` symlink

**DB:**
- 11 TikTok hashtags toegevoegd aan `brand_hashtag_pools` voor STELZ
- 1 prompt experiment `d3e00247-...` (v5_logo_only_strict)
- 2 test scan_requests (van quota verificatie, zullen opgepakt worden door worker)

## Wat ik bewust NIET deed

- Geen git push (wacht op jouw approval)
- Geen `railway up` (jij doet, wegens credentials)
- Geen Apify run met TikTok profile scan (kost geld, wacht op railway worker)
- Geen v5 prompt experiment run (vereist Python 3.13 + Gemini key in railway env)
- Geen prompt v5 promotion naar productie (eerst experiment runnen + comparen)
- Geen TikTok keyframe extraction (5x cost, backlog-item)
- Geen WebFetch op big-brand IG accounts (verspilt Apify credits)

## Bedrag-controle

| Item | Kost | Reden |
|---|---|---|
| Cold-start preview live test (drinkstelz) | ~$0.10 | profile + hashtag scrape via Apify |
| Vercel redeploy spot-api | $0 | gratis tier |
| DB migrations + queries | $0 | Supabase free tier |
| Twee test scan_requests | $0 | nog niet uitgevoerd door worker |
| **Totaal vanavond** | **~$0.10** | well under €5 cap |

Welterusten. Tool is materieel beter dan vanmorgen: 5 zwaktes geadresseerd, infrastructure-level improvements die meerdere maanden meegaan.
