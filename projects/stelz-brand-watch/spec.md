# STËLZ Brand Watch -- Technical Spec

## Pipeline overview

```
Discovery -> Scraping -> Vision Detection -> Storage -> Dashboard
   (eenmalig)  (Apify)     (Gemini Flash)    (Supabase)  (Next.js)
```

## 1. Discovery (week 1)

Doel: seed list van 100 tot 300 NL creators, fans en merken die regelmatig STËLZ content maken.

Bronnen:
- Hashtag scrape: #stelz, #stelzcider, #stelzhardseltzer en variaties
- Mention scrape: @stelz official account, wie tagt en wie reageert
- Bio scan: wie noemt STËLZ in bio
- Co-occurrence: posts waar STËLZ in context staat van festivals, bars, zomer, NL events

Outputs:
- CSV met handle, platform, follower count, post frequency, locatie indicator, tier (1 most relevant, 3 watch list)
- Handmatige curatie ronde door Meinte voordat we live gaan

Apify actors:
- `apify/instagram-hashtag-scraper`
- `apify/instagram-profile-scraper`
- `clockworks/free-tiktok-scraper`

## 2. Scraping (week 2)

Per creator op seed list:

Eenmalig historisch:
- Alle Instagram Highlights (`apify/instagram-story-scraper` of `dtrungtin/instagram-highlight-scraper`)
- Feed posts laatste 12 maanden (`apify/instagram-profile-scraper`)
- Reels laatste 12 maanden
- TikToks laatste 12 maanden (`clockworks/tiktok-scraper`)

Doorlopend (cron, dagelijks):
- Nieuwe posts, Reels, TikToks van de hele seed list
- Nieuwe Highlights checken (Stories worden vaak na 24h een Highlight)

Storage: alle media (images, video thumbnails) plus metadata in Supabase storage en tabellen.

Belangrijk: video frames samplen, niet hele video door Vision halen. Eerste frame, midden, einde, plus elke 3 seconden tussenpunten voor langere video's.

## 3. Vision Detection (week 2-3)

Gemini 2.5 Flash voor logo en productherkenning.

Per image of frame:
- Prompt met 3 tot 5 referentie-images van STËLZ blik en logo varianten
- Output: detected (bool), confidence (0-1), location in frame (bounding box optioneel), beschrijving context
- Threshold: confidence > 0.7 = hit, 0.4-0.7 = review queue, < 0.4 = miss

Cost optimalisatie:
- Eerst lichte filter via image hashing tegen al gehit content (dedupe)
- Batch processing via Gemini Batch API waar mogelijk
- Pro alleen voor review queue items

Future: eigen YOLO model trainen als volume groot wordt (>100k images per maand).

## 4. Storage (Supabase)

Tabellen:
- `creators` (handle, platform, tier, follower_count, location, last_scraped_at)
- `content_items` (id, creator_id, platform, type, posted_at, url, caption, media_urls, raw_metadata)
- `detections` (content_id, frame_idx, confidence, context, vision_model, created_at)
- `seed_queue` (potential creators uit discovery die nog niet gecureerd zijn)

Storage bucket voor thumbnails en frame samples.

## 5. Dashboard (week 3-4)

Stack: Next.js + Supabase + Vercel (zelfde als andere PA tools).

Views:
- Overview: total hits laatste 7/30/90 dagen, top creators, trending content
- Creator deep dive: alle hits van één creator, timeline, engagement
- Content feed: alle hits met filters (platform, datum, creator tier, confidence)
- Discovery queue: nieuwe potentiele creators uit hashtag scrape, één klik om te promoten naar seed list
- Alerts: tier 1 creator post = WhatsApp notificatie naar Meinte

Filters:
- Platform (IG post, IG Reel, IG Highlight, TikTok)
- Datum range
- Creator tier
- Confidence threshold
- Heeft tag of mention (ja/nee)

## 6. Live monitoring loop

Cron op Vercel of Railway:
- Dagelijks 08:00: nieuwe content van seed list scrapen
- Wekelijks: hashtag refresh voor discovery queue
- Maandelijks: full re-scrape Highlights (in geval nieuwe toegevoegd)

## Tech stack samenvatting

| Layer | Tool |
|-------|------|
| Scraping | Apify (actors per platform) |
| Vision | Gemini 2.5 Flash (Pro voor edge cases) |
| Storage | Supabase (Postgres + Storage) |
| Frontend | Next.js + Vercel |
| Notificaties | WhatsApp via bestaande PA integratie |
| Orchestration | Python scripts in `tools/stelz_brand_watch/` |

## Open vragen voor STËLZ

- Hebben ze al een lijst van bekende creators die we als basis kunnen gebruiken?
- Hebben ze reference images van het product (verschillende blikken, verpakkingen, varianten)?
- Wat is hun primaire vraag: brand health monitoring, creator discovery, of campaign effectiveness?
- Budget en wie betaalt voor de API kosten tijdens de test?

## Open vragen technisch

- Apify rate limits per actor: testen voordat we volledig live gaan
- Gemini Vision accuracy op product detection: pilot doen op 100 bekende STËLZ posts om baseline te krijgen
- Instagram TOS: scrapen via Apify is grijs gebied, voor interne tool acceptabel, voor publiek product juridisch checken
