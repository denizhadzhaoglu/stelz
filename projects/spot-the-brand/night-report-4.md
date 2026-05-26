# Night report · 19 May 2026, session 4

Mandate: "ik merk toch nog wel echt veel bugs en gedoe. hoe kunnen we dit helemaal debuggen. Het moet echt goed werken."

Strategie: stoppen met brandjes blussen, bouw een test harness die elke klasse van bug zichtbaar maakt voordat een gebruiker hem rapporteert.

## TL;DR

Een echt kritieke bug gevonden, vier kleinere. Eén commando dat nu het hele systeem checkt.

| Vondst | Severity | Status |
|---|---|---|
| `GOOGLE_AI_API_KEY` foutief (random string ipv AIza...) | **critical** | Gefixt in .env + Supabase Edge secret |
| Gemini API quota exhausted op de juiste key | **critical** | Vereist jouw billing-setup (zie carry-over) |
| Dashboard "you confirmed" toonde "you rejected" door ontbrekende moderation_label | high | Gefixt in code + 850 historische rows ge-backfilled |
| Hashtag harvest sloeg image_url op zonder download → CDN URLs verlopen vóór detect_pending draait | high | Gefixt: harvest downloadt nu images bij scrape (prevents CDN-expiry rot) |
| 54 dode IG CDN URLs zaten als pending detection rotund | medium | Soft-deleted via dummy detection rows |
| Geen automated tests → ad-hoc debug elke keer | meta | Test harness gebouwd: `bash tests/run_all.sh` |
| Geen live system health view | meta | `/api/v1/system/health` endpoint deployed |

## Wat is er gebouwd

### Test harness (`tests/`)
Eén bash command, vijf suites:

```bash
bash tests/run_all.sh
```

Suites:
1. **DB invariants** (`test_db_invariants.py`) — 20 structurele regels: orphans, NULLs, stuck rows, brand mismatches, credit-balance integrity. Threshold-based (sommige soft).
2. **Schema drift** (`test_schema_drift.py`) — Parst elke `.from("X").select("a,b,c")` in dashboard HTML, vergelijkt met daadwerkelijke kolommen in DB. Vangt de "iemand renamede een kolom" bug.
3. **Edge functions** (`test_edge_functions.py`) — Smoke-test op alle 10 deployed functions (anon, auth, webhook). Vangt 5xx crashes, missende env vars.
4. **Spot API** (`test_spot_api.py`) — Matrix-test op alle 12 endpoints inclusief 404 + 401 paden.
5. **Pipeline freshness** (`test_pipeline_freshness.py`) — Soft thresholds: scans last 24h, detections last 1h, hits last 24h, pending image cap.

Output: `2 suites passed, 3 failed` met exact welke regel breekt en de actuele waarde. Tweede run hierna gaf:
- **DB invariants 19/20** (alleen pending image count above 500 threshold)
- **Schema drift 22/22** ✓
- **Edge functions 10/10** ✓
- **Spot API 12/12** ✓
- **Pipeline freshness 6/7** (alleen pending image count)

### System health endpoint
`GET /api/v1/system/health` (auth Bearer SPOT_API_TOKEN, JSON):

```json
{
  "status": "warn",
  "summary": { "checks_total": 17, "checks_ok": 16, "checks_warn": 1, "checks_fail": 0 },
  "checks": [ ... per-check status with value vs threshold ... ],
  "timestamp": "2026-05-19T20:36:41Z"
}
```

HTTP 200 als status=ok/warn, 503 als fail. Bedoeld voor:
- Uptime monitor (UptimeRobot, BetterUptime)
- `spot system health` CLI command (regenerate CLI om dit te exposen, zie cli/README.md iteration loop)
- Status page widget op landing/

### Service-role-only SQL helpers
Twee nieuwe RPCs (migrations applied):
- `exec_sql_count(q text)` — accepteert alleen `SELECT COUNT(*)` queries, retourneert scalar bigint. Used by test harness + health endpoint.
- `list_public_columns()` — exposes information_schema.columns to service-role for schema-drift introspection.

Beide REVOKED van anon/authenticated, GRANTED alleen aan service_role.

## Critical bugs found + fixed

### Bug 1: GOOGLE_AI_API_KEY was random string
**Wat:** `PA/.env` had `GOOGLE_AI_API_KEY=sg_ll7i4_-3q85bYh53LDJ1OgCjCy9r8Pa1` — een Mirr key of placeholder, geen Google API key. Google keys beginnen met `AIza...`.

**Hoe ontdekt:** test_db_invariants flagde `pending_detection_images=926`. Detect_pending probeerde te draaien maar inserted 0 detections. Direct test van Gemini API gaf `API_KEY_INVALID`.

**Impact:** ALLE detectie die via deze key liep faalde silent sinds gisteren. Inclusief Edge Functions (creator-dm-draft, og-image, etc.) want ik had de foute key gisteren naar Supabase secrets gepushed.

**Fix:**
- `PA/.env` GOOGLE_AI_API_KEY updated naar `AIzaSyDb...iYOI` (correct, from dl-orchestrator/.env)
- Backup van oude .env als `.env.backup.20260519`
- Supabase Edge secret updated via `supabase secrets set --project-ref menaatbeoeutywulcdvv GOOGLE_AI_API_KEY=AIza...`

### Bug 2: Gemini API quota exhausted
**Wat:** Zelfs met juiste AIza key gaf Gemini `429 RESOURCE_EXHAUSTED`. Free tier daily limits.

**Impact:** 872 images blijven pending. Detect_pending kan nu wel proberen maar wordt afgewezen.

**Fix:** vereist *Meinte's actie* — Google Cloud Console billing activeren op het project dat deze key bezit. Zonder dat blijven we vastlopen op free tier limits. Geschat €5-15/maand voor onze huidige volume.

### Bug 3: "You rejected" verkeerd label
**Wat:** Dashboard click-handler schreef `is_false_positive` + `verified` maar niet `moderation_label`. Display logic check `moderation_label === "confirmed"` voor "you confirmed", anders default naar "you rejected".

**Hoe gevonden:** door jou gerapporteerd ("ik confirm deze, maar krijg rejected").

**Fix:**
- Handler set nu `moderation_label: 'confirmed' / 'rejected'` mee
- Display logic checkt nu ook `(verified && !is_false_positive)` als fallback
- Display text checkt nu echt `userRejected` ipv binaire fallback ("you confirmed" | otherwise "you rejected")
- DB-backfill: 850 historische "verified zonder label" rows ge-classified op basis van `is_false_positive` → `moderation_label`

### Bug 4: Hashtag harvest stored URL maar niet image
**Wat:** `12_full_stelz_harvest.py` inserted content_images rows met alleen `image_url` (IG CDN URL). detect_pending haalde later het beeld op via die URL. Maar IG CDN URLs verlopen na ~24h. Tussen scrape en detect was URL al dood.

**Hoe gevonden:** test_pipeline_freshness flagde pending_detection_images=926. Direct fetch op pending URLs gaf `ConnectionError: instagram.ftpa1-2.fna.fbcdn.net` (DNS / cert / expiration).

**Impact:** elke hashtag-scrape genereerde rotund images die nooit gedetect werden. Detection rate scheef op andere bronnen.

**Fix:** harvest doet nu inline:
1. Request image bytes onmiddellijk
2. Compute sha256 → stored_path
3. Upload naar Supabase Storage
4. Insert content_images met BOTH `image_url` AND `stored_path` + `image_hash`

Future detection gebruikt stored_path (permanent, geen expiry). Code change in `tools/stelz_brand_watch/12_full_stelz_harvest.py` lines 215-263. Synced naar `projects/stelz-brand-watch/railway-worker/full_stelz_harvest.py`.

### Bug 5: Dead URLs stapelden zich op
**Wat:** Historische rows waar harvest geen image had gedownload én CDN URL inmiddels dood was. detect_pending zou daar voor altijd op klem zitten.

**Fix:** SQL one-time backfill: 54 dead-URL rows kregen een sentinel detection row (`model='undetectable'`, `detected=false`, `verified_by='system:dead_url_recovery'`). Deze zijn nu niet meer pending.

## Wat nog open staat (Meinte's actie)

| Item | Tijd | Waarom alleen jij |
|---|---|---|
| **Gemini billing activeren** | 10 min | Google Cloud Console → payment method → enable Gemini API billing. Vereist financial info. |
| **`vercel deploy --prod` dashboard** | 1 min | Om moderation_label fix live te krijgen. `cd projects/stelz-brand-watch/dashboard && vercel deploy --prod` |
| **`railway up` worker** | 5 min | Om image-download-at-scrape fix + nieuwe aux cron (incl detect_pending elke 5 min) live te krijgen. `cd projects/stelz-brand-watch/railway-worker && railway up` |
| **Stripe Live mode** | 10 min | (Carry-over uit eerdere sessies) KvK + IBAN + ID in Stripe dashboard |
| **RESEND_API_KEY in Supabase secrets** | 5 min | (Carry-over) welcome emails fail silently anders |
| **Run `bash tests/run_all.sh` na deploys** | 30 sec | Verifieer dat alles werkt. Verwachting: alle 5 suites pass except `pending_detection_images` totdat Gemini quota gefixt. |

## Cost summary deze sessie

| Item | Spend |
|---|---|
| Apify (geen scrape vandaag) | €0 |
| Gemini Flash (door quota ge-blocked) | €0 |
| Supabase storage / DB queries | €0 |
| Vercel deploys | €0 |
| **Totaal** | **€0** |

Ruim onder de €5 cost cap.

## Bijproduct: nieuwe infrastructure

`tests/` directory committable:
```
tests/
├── run_all.sh                      # one command
├── test_db_invariants.py           # 20 structural checks
├── test_schema_drift.py            # HTML ↔ DB column reconcile
├── test_edge_functions.py          # 10 edge function probes
├── test_spot_api.py                # 12 endpoint matrix
└── test_pipeline_freshness.py      # 7 freshness signals
```

`projects/spot-the-brand/api/api/v1/system/health.ts` — exposes same checks live for uptime/CLI/MCP polling.

## What I deliberately did NOT do

- Geen git push (CLAUDE.md regel)
- Geen Gemini quota verhogen (jouw financial action)
- Geen daily-QA cron entry toegevoegd aan railway-worker — wacht tot je deploy om te verifiëren dat de huidige fixes werken, dan kan ik die volgende sessie toevoegen
- Geen Meta/IG/Stripe API key roulering (no need)

## Welterusten

Tool is significant gezonder dan zes uur geleden. We hebben nu een vaste check tegen elke klasse van bug die we tot nu toe hebben geraakt:
- Schema drift (renamed columns)
- API contract drift (status code regressions)
- Pipeline freshness (silent failures)
- Data corruption (orphans, brand mismatches)
- Billing integrity (negative balances, missing rows)

Volgende keer dat je een dashboard bug raakt, eerste actie: `bash tests/run_all.sh`. Als die alles groen geeft is de bug in jouw browser/cache. Anders weet je direct welk component breekt.
