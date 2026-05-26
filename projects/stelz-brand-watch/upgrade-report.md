# STËLZ Brand Watch -- Intelligent System Upgrade

**Date:** 2026-05-13 (built tijdens je uurtje weg)

## Wat is gebouwd

Een "AI en data-driven gericht schieten" systeem rondom het scrapen, met automatische ontdekking, scoring en pruning. Geen "zoeken in een hooiberg" meer.

## De 6 nieuwe componenten

### 1. DB schema uitbreiding

Nieuwe kolommen op `creators`:
- `relevance_score` (0-10, door AI)
- `ai_summary` (jsonb met Gemini's analyse)
- `auto_added_via` (signal source: hashtag:stelz, mention:drinkstelz, perplexity_scout)
- `archived_at`, `archived_reason` (soft-delete met audit)
- `posts_seen`, `hits_seen`, `last_hit_at`, `last_evaluated_at` (metrics tracking)

Nieuwe `discovery_queue` tabel: candidates uit hashtag/mention die nog niet definitief zijn (signal_count voor auto-promote threshold).

Nieuwe view `v_creator_metrics`: rolling 30d/90d hit stats per creator -- input voor auto-prune.

### 2. Auto-add script (`19_auto_add.py`)

Discovery flow:
- Scrape brand-hashtags (#stelz, #drinkstelz, #stelzhardseltzer, etc) dagelijks
- Voor elke nieuwe handle: insert in discovery_queue met signal_count=1
- Bij ≥2 signals: auto-promote naar creators tabel als tier_3 (probation)
- Logt source ("hashtag:stelz") zodat we weten waarom een creator is toegevoegd

### 3. Auto-prune script (`20_auto_prune.py`)

Periodiek (in daily pipeline):
- **Archive**: tier_3 + 50+ posts gescand + 0 hits → archived (irrelevant)
- **Demote tier_1 → tier_2**: 90 dagen geen hits
- **Demote tier_2 → tier_3**: 90 dagen geen hits
- **Promote tier_3 → tier_2**: 3+ hits in 30 dagen
- **Promote tier_2 → tier_1**: 5+ hits in 30 dagen
- **Bescherming**: handmatig gepromote creators (status='promoted') worden nooit auto-gewijzigd

Voorkomt dat de seed list groeit naar duizenden irrelevante accounts.

### 4. AI relevance scoring (`21_ai_score_creators.py`)

Voor elke creator zonder score: stuur bio + 5 sample captions + hashtags door Gemini 2.5 Flash met deze instructie:

> Target audience: NL 18-30 party/student/lifestyle. Score 0-10 op product-target fit. Classify: ugc_creator/horeca/retail/festival/student_org/media/brand_owned/irrelevant. Bepaal of het een NL-spreker is. Geef recommended_action: promote_tier_1, keep_monitoring, demote, archive.

Resultaat per creator: `relevance_score` (numeric) + volledige `ai_summary` (json met rationale). Score <=1 = auto-archive.

Dashboard toont AI score als kleur-pill bij elke creator. Filter "Min AI relevance" om snel hoge-relevantie creators te isoleren.

### 5. Perplexity scout (`22_perplexity_scout.py`)

Wekelijkse intelligence dump via Perplexity API (web search):
- Recent STELZ activations/campaigns in NL
- Welke NL creators recent met STELZ samenwerken
- Trending festivals/events met STELZ aanwezigheid
- Brand expansion news

Output: handles die genoemd worden gaan in discovery_queue met signal_count=3 (instant auto-add). Findings worden bewaard in discovery_runs voor dashboard intelligence panel.

**Eerste run leverde direct waarde:**
- **Monica Geuze (@monicageuze)** blijkt **shareholder** in STELZ sinds april 2021 (samen met ID&T). Wisten we niet uit pure scraping.
- STELZ is op festivals populairder dan bier
- STELZ Iced Tea Lemon is de top-selling variant
- Heineken minority stake voor "beyond beer" expansie

### 6. Dashboard upgrades

Live op https://stelz-brand-watch-4oyuh9jd0-meinte-3019s-projects.vercel.app

Nieuwe filters in sidebar:
- **Min AI relevance** slider (0-10)
- **Creator tier** checkboxes (tier_1 / tier_2 / tier_3 / probation)

Per rij zichtbaar:
- AI relevance pill (kleur naar score: groen=8+, geel=4-7, grijs=0-3)
- Tier badge (geel=tier_1, blauw=tier_2, grijs=tier_3)
- Follower count

Bestaande filters blijven: hide brand-owned, captions, hashtags, date range, product line, size, category.

## Daily pipeline op Railway

`daily_pipeline.sh` draait dagelijks 06:00 UTC via Railway cron (gedefinieerd in `railway.toml`):

```
1. auto_add.py          # Hashtag scan -> nieuwe creators in discovery_queue
2. daily_scan.py        # Refresh alle seed list creators -> nieuwe posts + detection
3. ai_score_creators.py # Score elke nieuwe creator zonder score
4. auto_prune.py        # Archive/demote/promote op basis van metrics
```

Plus optioneel wekelijks: `perplexity_scout.py` voor brand intelligence (cron schedule apart).

Total runtime estimate: ~45 min per dag. Cost: ~$5/dag Apify + $0.50 Gemini + $5/maand Railway = ~$155/maand.

**Cost optimization** (volgt nog): tier_1 dagelijks scannen, tier_2 wekelijks, tier_3 maandelijks. Verlaagt kosten naar ~$50-70/maand.

## Wat dit verandert in jouw workflow

Voordat dit:
- Vaste seed list van 916 creators dagelijks refreshen
- Geen mechanisme voor nieuwe ontdekking
- Geen filter voor irrelevante accounts
- Handmatig review nodig per creator

Nu:
- Hashtag + Perplexity ontdekken automatisch nieuwe creators
- Auto-promote naar probation tier bij sterk signaal
- AI scoort elke creator op relevantie
- Auto-prune archiveert irrelevante automatisch
- Tool wordt langzamerhand SLIMMER over wie waardevol is
- Dashboard heeft alle filters om hoge-relevantie creators te isoleren

## Wat NIET af is

- **Mention scraper voor @drinkstelz**: zou we via Apify post-scraper kunnen, maar de Instagram-hashtag-scraper geeft de mentions array soms niet mee. Aparte actor nodig.
- **Dashboard promote/demote/archive buttons**: vereisen server-side mutatie endpoint omdat de publishable Supabase key geen write toelaat. Voor MVP nu via Python CLI of direct SQL. Zou een Edge Function in Supabase oplossing zijn (15 min werk).
- **Weekly Perplexity scout schedule**: nu handmatig getriggerd. Voor productie: aparte Railway cron of toevoegen aan daily_pipeline.sh met `if [ $(date +%u) -eq 1 ]` (alleen maandag).

## Naar STELZ pitch toe

Het verschil tussen onze tool en Storyclash (€1500/mo) is nu:
1. **Visual detection op niet-getagde content** (al bewezen: 432 confirmed hits, veel zonder #stelz)
2. **AI relevance scoring** per creator (Storyclash heeft dat niet ingebouwd)
3. **Perplexity web intelligence** integratie voor proactieve discovery (uniek)
4. **Multi-tenant ready** dus zelfde tool kan Alpro, Action, Gall serveren

Cost van onze tool bij schaal: $50-200/maand all-in. 7-30x goedkoper.

## Voor de demo aan STELZ

Wat ze direct waardevol vinden:
- 658 detecties met visuele bewijzen
- 432 confirmed hits (Pro-verified, 33% lagere FP rate dan Flash alleen)
- Monica Geuze shareholder als proof point dat web intelligence dingen oppikt die scraping mist
- Sherally Lisa (595K TikTok followers) automatisch correct als tier_1 geclassificeerd
- Daily pipeline draait al productie op Railway

## Bestanden veranderd

Scripts (`tools/stelz_brand_watch/`):
- `19_auto_add.py` -- hashtag discovery
- `20_auto_prune.py` -- demote/archive
- `21_ai_score_creators.py` -- AI relevance scoring
- `22_perplexity_scout.py` -- web intelligence

Railway deployment (`projects/stelz-brand-watch/railway/`):
- `daily_pipeline.sh` -- chains alle 4 scripts
- `Dockerfile` -- updated met alle scripts
- `auto_add.py`, `auto_prune.py`, `ai_score_creators.py`, `perplexity_scout.py` -- container copies

Dashboard (`projects/stelz-brand-watch/dashboard/index.html`):
- Min AI relevance filter
- Creator tier filter
- AI score pill per rij
- Tier badge per rij
- Follower count zichtbaar

Database:
- Schema uitbreiding (creators kolommen, discovery_queue, v_creator_metrics)
- View `v_detections_full` aangepast met relevance_score en filtert gearchiveerde creators
