# STËLZ Brand Watch -- Schaal Architectuur

Het pilot is bewezen werkbaar. Hierin staat hoe we van losse Python scripts naar een productized tool gaan die JackandAI als intelligence-laag kan verkopen.

## Het schaal probleem

Wat de pilot doet werkt voor één brand (STELZ), één markt (NL), één platform (IG), losse scripts, manual review. De productized versie moet:

1. **Multi-brand**: Alpro, Action, Gall, Fritz Kola, etc. Elke brand eigen referenties, prompts, hashtag pool, seed list.
2. **Multi-market**: NL nu, BE/DE/UK later. Andere taal, andere hashtags, andere creators.
3. **Multi-platform**: IG + TikTok minimaal. YouTube Shorts en BeReal later.
4. **Continu**: cron-gedreven monitoring met alerts, niet ad hoc scripts.
5. **Multi-user**: STELZ team + JackandAI team + (later) self-service clients.
6. **Cost efficient**: bij schaal worden Apify en Gemini kosten een echt probleem. Dedup, caching, sampling zijn nodig.
7. **Quality controlled**: false positives kosten vertrouwen. Verify pipeline en feedback loop.

## Drie kritische beslissingen NU

Deze keuzes hebben impact op de Supabase schema opzet en de eerste production scripts. Beter goed dan refactor.

### Beslissing 1: Multi-tenant vanaf dag 1

**Voorstel:** ja. Alle tabellen krijgen `brand_id` als foreign key vanaf het begin. Het kost geen extra werk en bespaart een dure migratie als we de tweede brand toevoegen.

**Impact:** Schema krijgt `brands` tabel, alle entities krijgen `brand_id`. Discovery scripts, scrapers, detection allen accepteren `--brand` parameter. Dashboard heeft brand selector.

### Beslissing 2: Source adapter pattern voor platforms

**Voorstel:** nog niet. We hebben nu alleen IG en de adapter laag voegt complexiteit toe zonder voordeel. Wel: de Python scripts moeten platform-agnostic data structure produceren zodat de migratie naar TikTok later schoon is.

**Wat we wel doen:** common content_item schema in Supabase met platform veld. Iedere bron schrijft zelfde structuur.

**Wanneer wel adapter:** zodra TikTok aan boord komt. Dan: source adapter klasse met scrape_hashtag, scrape_profile, scrape_post methods, per platform een implementatie.

### Beslissing 3: Detection caching vanaf dag 1

**Voorstel:** ja. Elk gescand image krijgt een SHA256 hash. Detections worden gekoppeld aan hash, niet aan post. Zelfde image hash = al bekende detection, geen nieuwe Gemini call.

**Waarom nu:** sponsor banners, retail flyers en repost content komen vaak meerdere keren voorbij. Bij 100 candidates en 20 posts each is dedup misschien 10%. Bij 1000 candidates is het 30% en betekent het 30% kostenbesparing. Eenmalig bouwen, oneindig betalen zich uit.

**Impact:** `image_hashes` tabel met `(hash, detection_result, model, scanned_at)`. Detection script checkt eerst hash, alleen miss -> Gemini call.

## Architectuur target state

```
[Brand config in Postgres]
        |
        v
[Discovery worker (cron)] --scrapes--> [Apify]
        |
        v
[Content queue (pg-boss in Postgres)]
        |
        v
[Detection worker (cron)] --batches--> [Gemini Flash]
        |                                       |
        |                            [Hash cache check]
        v                                       |
[Detection results in Postgres] <-- [Verify worker for low conf]
        |
        v
[Dashboard (Next.js)] + [Alert system (WhatsApp/email)]
```

**Tech keuze:**
- **Database**: Supabase Postgres (al in de stack, auth en RLS gratis erbij)
- **Workers**: Railway worker containers. Vercel Cron alleen voor lichte triggers, want Apify run-sync duurt minuten en breekt Vercel timeout.
- **Queue**: pg-boss bovenop Supabase Postgres. Geen aparte queue infrastructure, simpel start.
- **Frontend**: Next.js + Vercel + Supabase auth + RLS voor multi-tenant access
- **Alerts**: WhatsApp via bestaande PA integratie + email fallback

## Database schema target

```sql
-- Brand definitions
brands (id, name, slug, active, created_at)
brand_product_lines (brand_id, name, description, reference_image_url)
brand_prompt_config (brand_id, prompt_template, confidence_threshold, ...)
brand_hashtag_pools (brand_id, hashtag, group_label, platform, priority)

-- Discovery & creators
creators (id, brand_id, platform, handle, full_name, tier, status, ...)
creator_signals (creator_id, source, score, captured_at)  -- followers, hashtag hits, etc

-- Content & detection
content_items (id, brand_id, creator_id, platform, post_url, post_id, posted_at, ...)
content_images (id, content_item_id, image_url, image_hash, sequence)
detections (id, content_image_id, model, product_line, confidence, size_in_frame, 
            is_primary_subject, context, verified, verified_by, ...)

-- Image hash cache (dedup)
image_detection_cache (image_hash PRIMARY KEY, brand_id, detection_json, model, created_at)

-- Discovery runs (audit)
discovery_runs (id, brand_id, source_type, source_id, started_at, completed_at, results_count)
```

## Fasering

### Fase 1 (deze week): pilot afmaken
- Top 100 scan klaar, post-process filter, manual validation
- Top 50 personen scan met geupdate prompt
- Decision: hit rate goed genoeg voor STELZ pitch?

### Fase 2 (volgende 2 weken): MVP voor STELZ
- Supabase schema opzetten (multi-tenant ready, dus met brand_id)
- Migreer pilot data van .tmp/ naar Postgres
- Eerste production scripts: discovery, scrape, detect, alle met --brand flag
- Image hash cache vanaf dag 1
- Dashboard MVP: 1 pagina per brand, hits list met filters
- WhatsApp alerts voor nieuwe tier 1 hits
- Cron op Railway

### Fase 3 (week 3-4): TikTok + verify
- Source adapter pattern introduceren (IG + TikTok)
- TikTok hashtag + profile scraper
- Verify pipeline: Gemini Pro voor low-conf en small-size hits
- Feedback loop: human marks false positive -> stored, prompt nuance

### Fase 4 (maand 2-3): tweede brand
- Onboard Alpro of Action als tweede brand
- Validatie multi-tenant: zelfde tool, andere prompt, andere hashtag pool
- White-label dashboard met brand selector
- Pricing structure voor JackandAI productized

### Fase 5 (maand 4+): self-service
- Onboarding flow voor nieuwe brands
- Client login en read-only access
- Billing en usage limits per tier
- Public landing page voor JackandAI Intelligence

## Cost model bij schaal

Per brand per maand:

| Component | Klein (1 brand, 50 creators) | Medium (5 brands, 200 creators each) | Groot (20 brands, 500 creators each) |
|-----------|------------------------------|--------------------------------------|--------------------------------------|
| Apify | 100 EUR | 400 EUR | 1500 EUR |
| Gemini Flash | 20 EUR | 100 EUR | 400 EUR |
| Supabase Pro | 25 EUR | 25 EUR | 100 EUR |
| Vercel Pro | 20 EUR | 20 EUR | 80 EUR |
| Railway | 5 EUR | 25 EUR | 100 EUR |
| **Totaal** | **170 EUR** | **570 EUR** | **2180 EUR** |
| Per brand | 170 | 114 | 109 |

Met image hash cache: verwacht 25-40% besparing op Gemini calls bij medium+. Caching is dus essentieel voor unit economics.

## Pricing model voorstel voor JackandAI

| Tier | Doelgroep | Prijs/maand | Features |
|------|-----------|-------------|----------|
| Starter | 1 brand, NL | 500 EUR | 1 platform (IG), 100 seed creators, weekly scan, dashboard |
| Pro | 1 brand, multi-market | 1500 EUR | 2 platforms (IG+TT), 500 seed creators, daily scan, alerts |
| Enterprise | Multi-brand | Custom | Custom hashtag pools, verify pipeline, API access, dedicated support |

Marge starter tier: 500 - 170 = 330 EUR/maand per klant. Bij 10 klanten in Pro: 1500 - 250 (geschaalde costs) = 1250 EUR marge per klant. 10 klanten = 12,5k MRR.

## Key risico's

1. **Apify TOS / Instagram rate limits**: scraping is grijs gebied. Bij grote schaal of als Meta crackt, kan dit breken. Mitigatie: meerdere Apify accounts, fallback actors, lange retry windows.

2. **Gemini hallucinaties bij scale**: meer images = meer edge cases. Verify pipeline en feedback loop zijn essentieel.

3. **Concurrent claims**: Storyclash, Brandwatch, Talkwalker zijn er al. Onze positionering moet zijn: cultureel intelligent (JackandAI strategy laag), 70% goedkoper, en het kan brand-presence in NL niche content zien.

4. **Cold start**: nieuwe brand betekent nieuwe reference images, nieuwe hashtag pool, nieuwe seed list. Onboarding tijd is een echt risico. Onboarding template + AI-assist (laat Gemini concurrent brands + relevante hashtags suggereren).

## Volgende concrete bouwactie zodra pilot klaar is

Setup Supabase met de schema's hierboven. Schrijf één migration script dat:
1. Pilot data uit `.tmp/stelz_brand_watch/` leest
2. Brand "stelz" aanmaakt
3. Creators, content_items, detections vult
4. Image hashes berekent en cache vult

Dat is de eerste production deliverable. Geen nieuwe pilots tot dat klaar is.
