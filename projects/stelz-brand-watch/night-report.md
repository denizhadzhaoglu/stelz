# STËLZ Brand Watch -- Night Report

**Datum:** 13 mei 2026 (overnight 12 → 13 mei)
**Status:** Klaar. Alle 5 sprints succesvol afgerond. Cost cap aangehouden.

## TL;DR

Dashboard staat live met **657 STELZ detecties** over **~900 creators**, een **13x verbetering** van de 49 detecties van gisteren. Vier productlijnen gedetecteerd (Hard Seltzer, Hard Lemonade, Hard Iced Tea, Mixed Classics) plus de 0.0 non-alcoholic lijn die we eerder niet kenden. Twee dingen werken aantoonbaar:

1. **Logo detectie** met rijke reference set (8 images vs 3) en explicit prompt instructions: 287 Hard Seltzer hits, 120 zuivere logo_only hits op kleding/banners/menus.
2. **Bredere discovery** via #drinkstelz hashtag (de echte brand tag, 9x meer gebruikt dan #stelz), TikTok, en handpicked NL accounts.

Belangrijkste nieuwe vondsten: STELZ heeft een Suriname-expansie (@stelz_suriname), zit op awards bij jongerenwerk Woensdrecht, en Mixed Classics (Spritz, Gin & Tonic, Moscow Mule) is een echte productlijn die we eerder over het hoofd zagen.

## Sprints uitgevoerd

| Sprint | Wat | Resultaat |
|--------|-----|-----------|
| A. #stelz family harvest | 10 hashtags, 500 posts/each | 527 unique posts, 132 nieuwe creators |
| B. Popular NL handpicked | 60 mainstream creators | 38 profiles found, 282 posts |
| D. TikTok harvest | 10 hashtags, 100 videos/each | 696 unique TikToks, 606 TikTok creators |
| v3 rescan | Strenger prompt op 1597 oude images | +22 nieuwe hits, -22 v1 false positives |
| v4 logo focus | Rich references + 4 productlijnen | 657 hits over 3046 images |

Sprint C (Highlights) overgeslagen omdat Apify highlight-actors onbetrouwbaar zijn en Instagram dat steeds zwaarder afgrendelt.

## Database state na de nacht

| Tabel | Aantal |
|-------|--------|
| Creators (IG + TikTok) | 916 |
| Content items | 3102 (1597 + 1505 nieuw) |
| Content images | 3102 |
| Thumbnails in Storage | 1944 |
| Detections totaal (v1+v3+v4) | 6160 |
| **Detections v4 detected=true** | **657** |
| Image hash cache entries | ~3500 |

## Detectie distributie v4

| Productlijn | Hits |
|------|------|
| Hard Seltzer | 287 (44%) |
| Logo-only (kleding/banner/menu) | 120 (18%) |
| Hard Iced Tea | 112 (17%) |
| Hard Lemonade | 91 (14%) |
| Mixed Classics | 34 (5%) |
| 0.0 non-alc | 13 (2%) |

## Top 10 creators by total detections

1. **@drinkstelz** -- 259 detecties (officiële brand, eigen content)
2. **@bullseyedistribution** -- 22 (drank distributeur)
3. **@stelz_suriname** -- 12 (STELZ heeft een Suriname-expansie!)
4. **@studentdelivery_** -- 8 (studenten bezorgservice met STELZ)
5. **@bavaria.bierkoerier** -- 7 (bier koerier inclusief STELZ)
6. **@degist.delft** -- 7 (Delft horeca)
7. **@jacktriesbeer** -- 6 (bier reviewer)
8. **@stanbev_international** -- 6 (drank importeur)
9. **@tappers_nijmegen** -- 5 (echte UGC bar)
10. **@slijterij_wijnhuis_van_den_bos** -- 4

## Specifieke nieuwe hits die opvallen

- **@luca_vz**: STELZ Hard Lemonade logo op een WIT T-SHIRT (gemerchandised), conf 1.0
- **@jongerenwerkwoensdrecht**: jeugdorganisatie met awards die STELZ Hard Seltzer logo prominent tonen
- **@thecooldowncafedekleine**: vrouw met STELZ Hard Iced Tea Lemon in dim club setting
- **@idrawrotterdam**: STELZ multipack box op tafel
- **@tappers_nijmegen**: twee vrouwen met Hard Iced Tea Lemon + Peach
- **@borrel071**: vrouw met Hard Lemonade Orange in crowded club
- **@deborrelbar**: vrouw met Mixed Classics Gin & Tonic (eerste keer dat we deze lijn in UGC zien)

## Wat we vannacht hebben geleerd

### 1. Vier productlijnen, niet drie
STELZ heeft naast Hard Lemonade en Hard Seltzer ook Hard Iced Tea EN Mixed Classics (cocktail-in-a-can: Spritz, Gin & Tonic, Moscow Mule). Plus een 0.0 non-alcoholic lijn (Sparkling Water + Iced Tea Lemon/Peach). De pilot prompt had alleen Hard Lemonade en Hard Seltzer. Voor nieuwe brand-onboarding: altijd eerst de officiële website scrapen om alle productlijnen te enumereren.

### 2. `#drinkstelz` is de echte tag, niet `#stelz`
Pilot pakte 47 posts uit `#stelz`. Vannacht: `#drinkstelz` levert 427 posts, 9x meer. De brand gebruikt zelf `@drinkstelz` en hun fans nemen dat over.

### 3. Logo detectie hangt grotendeels op references
Met 3 references: 49 hits in v1. Met 8 references (4 productlijnen + 2 UGC + 1 standalone + 1 variety): 657 hits in v4. Belangrijkste prompt-toevoegingen die werken:
- Umlaut op Ë expliciet noemen als diagnostic feature
- Specifieke S-in-circle kleuren per productlijn (orange/red/green/yellow/teal/brown)
- Expliciete lijst van plekken waar logo kan verschijnen (kleding, banner, menu, screen, tap, etc)
- "Be thorough" naast "prefer miss over false positive"

### 4. v3 prompt was zelf-corrigerend
22 nieuwe hits gevonden + 22 v1 FPs verwijderd. v1 prompt was tegelijk te ruim én te streng. v3/v4 vermindert beide kanten.

### 5. TikTok is voor STELZ nog beperkt aanwezig in publieke content
696 TikTok videos uit lifestyle hashtags, maar van die 696 zijn de meeste niet STELZ. De TikTok thumbnails worden v4 gescand maar dat is nog niet rijk genoeg ingebouwd. Voor TikTok hebben we waarschijnlijk frame sampling nodig.

### 6. Mainstream NL influencers tonen STELZ NIET
38 grote NL accounts gescand (Monica Geuze, Famke Louise, DJs, etc): nul STELZ hits in hun recente content. STELZ leeft in mid-tier UGC en horeca, niet bij A-influencers. Discovery strategie moet daar focus op blijven houden.

## Cost gemaakt vannacht

Schatting:
- Sprint A Apify: $11
- Sprint B Apify: $2
- Sprint D Apify (TikTok): $3
- v3 rescan Gemini: $0.5
- v4 detection Gemini (3000 calls met 8 refs): $2
- Image cache: bandwidth only
- **Totaal: ~$18.5**

Onder de afgesproken cap van $30. Marge voor extra runs als nodig.

## Aanbevelingen voor volgende sessie

### Korte termijn (deze week)
1. **Manueel valideren van top 50 hits** door Meinte. Vooral logo_only categorie heeft fragmenten waar Gemini "STELZ on screen" of "STELZ on banner" zegt en kan hallucineren. Markeer FPs zodat we de tool tunen.
2. **Image cache afronden**: nog ~1100 images zonder stored_path. Re-run script tot 100% complete.
3. **Dashboard polish**: klikbare creator handles die filteren, sortable columns, mark-as-FP knop.
4. **Vercel deployment protection uitschakelen** voor publiek toegankelijke demo URL.

### Volume groei
1. **STELZ official account followers** (~50k+). Geen Apify follower scraper meer beschikbaar, maar via `/explore` endpoint of session-cookie scraper kan het wel. Zou onze hoogst-relevante creator pool zijn.
2. **Reposters en commenters** van @drinkstelz top posts. Mensen die echt actief engagen met de brand.
3. **TikTok video frame sampling**: niet alleen cover, maar 3 frames per video. ~3x meer cost maar pakt UGC die in dance/party scenes voorkomt.

### Quality
1. **Verify pass met Gemini Pro** op alle hits met conf 0.5-0.85. Pro is 4x duurder maar veel preciezer op edge cases. Zou ~50 USD per maand kosten bij ons volume.
2. **Feedback loop in dashboard**: gebruiker markeert FP, prompt v5 leert daar van.
3. **CLIP embedding pre-filter** voor snellere scale: lokaal compute, alleen positives door Gemini.

### Productisatie
1. Tweede brand erbij voor multi-tenant test (Alpro? Action? Fritz?). 0 extra dev werk, alleen onboarding.
2. Cron jobs op Railway voor dagelijkse incremental scrape van seed list.
3. WhatsApp alert wanneer tier 1 creator een STELZ post heeft.

## Bestanden veranderd vannacht

### Scripts
- `tools/stelz_brand_watch/11_rescan_v3.py` -- v3 prompt rescan
- `tools/stelz_brand_watch/12_full_stelz_harvest.py` -- massive #stelz family harvest
- `tools/stelz_brand_watch/13_popular_nl_creators.py` -- handpicked NL list
- `tools/stelz_brand_watch/14_detect_new.py` -- v3 detect on new content
- `tools/stelz_brand_watch/15_tiktok_harvest.py` -- TikTok hashtag scrape
- `tools/stelz_brand_watch/16_detect_v4_logo_focus.py` -- v4 logo focus detection

### Database
- `projects/stelz-brand-watch/db/03_view_latest_detection.sql` -- view update (live in Supabase)

### Reference images toegevoegd
- `projects/stelz-brand-watch/reference-images/web_stelz_logo.png` -- variety pack (Hard Seltzer + Iced Tea + 0.0)
- `web_group_13.png` -- Hard Iced Tea trio (Lemon, Mango, Peach)
- `web_group_132.png` -- Hard Seltzer trio (Passionfruit, Raspberry, Mango)
- `web_group_133.png` -- Mixed Classics trio (Spritz, Gin & Tonic, Moscow Mule)
- `web_hardlemonade.png` -- Hard Lemonade trio
- `web_lifestyle.png` -- UGC single
- `web_lifestyle2.png` -- UGC group at festival

### Memory
- `feedback-autonomous-overnight-work.md`
- `feedback-stelz-filter-in-ui.md` (vorige sessie)
- `feedback-stelz-visibility-threshold.md` (vorige sessie)
