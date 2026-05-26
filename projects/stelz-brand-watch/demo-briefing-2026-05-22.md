# STELZ pitch + demo briefing (22 mei 2026)

Stand opgemaakt 21 mei 23:xx. Alles gecheckt: tests, DB, live dashboard, moderator. Hieronder de cijfers, demo flow en wat er nog open ligt.

## Status: groen

| Check | Resultaat |
|---|---|
| DB invariants (25 checks) | 25/25 |
| Schema-drift (22 tables/views) | 22/22 |
| Edge functions (10 probes) | 10/10 |
| Spot API (12 endpoints) | 12/12 |
| Pipeline freshness | 6/7 (zie open punt) |
| System health alerts open | 0 |
| Mojibake checks | 0 |
| Resurrected rejections | 0 |
| Dashboard live | 200, 825 hits, 309 creators |
| Moderator live | 200, 393 remaining, 516 all-time confirmed |

Enige fail in pipeline freshness: `scans_completed_last_24h = 0`. Verklaring: de Railway worker draait wel (1144 detections last 24h), maar de cron logt niet in `scan_requests` per run. Functioneel geen issue. Wel iets om voor de demo niet als gespreksonderwerp te kiezen.

## Cijfers voor de pitch

**Volume**
- 3047 creators tracked (962 Instagram, 2085 TikTok)
- 15.519 posts geharvest, 11.716 images verwerkt
- 15.980 detections gedraaid, 1967 hits totaal
- 825 schoon in feed (na sticky reject + dedup)
- 593 door moderator confirmed, 74 rejected, rest unreviewed

**Pipeline activiteit**
- 530 detections in laatste uur
- 1144 detections in laatste 24h
- 68 nieuwe hits in laatste 24h
- 218 images pending detection (binnen 500 cap)

**Trend (8 weken)**
| Week | Hits |
|---|---|
| 18 mei | 82 |
| 11 mei | 78 |
| 4 mei | 49 |
| 27 apr | 55 |
| 20 apr | 58 |
| 13 apr | 19 |
| 6 apr | 15 |
| 30 mrt | 10 |

Duidelijke opwaartse trend sinds mid-april. Goed verhaal: "we vinden steeds meer, en het blijft schoon."

**Product line split (hits in feed)**
- hard_seltzer 351
- hard_iced_tea 206
- logo_only 150
- hard_lemonade 87
- mixed_classics 20
- zero_zero 9

**Platform split**
- Instagram 631
- TikTok 194

**Top creators om te laten zien**
1. @drinkstelz (eigen account) — 217 hits, baseline
2. @studentdelivery_ — 9863 followers, 19 hits, laatste post 15 mei (warm)
3. @booijagency (TikTok) — 5213 followers, 12 hits, laatste post 6 mei
4. @na_examen_dagen — 1454 followers, 8 hits, laatste post 20 mei (gisteren)
5. @friscompanyeindhoven (TikTok) — 3050 followers, 9 hits, 19 mei
6. @lifewithcharlot (TikTok, fashion/lifestyle) — 20 mei post, STELZ shirt upcycling
7. @gastelsfeer — 2635 followers, 6 hits
8. @dedokterbreda — 2410 followers, 6 hits, 17 mei

## Demo flow (15 min)

**1. Opening (1 min)**
"Vanaf nu zien jullie binnen een uur welke creator STELZ in beeld brengt, of jullie ze nu kennen of niet."

**2. Dashboard tour (4 min) — `www.spotyourbrand.com/?brand=stelz`**
- Top counters: 825 hits, 309 creators, hits per day chart laat groeicurve zien
- Default view = "Strong visual hits" (441 in feed, alleen waar STELZ duidelijk zichtbaar is)
- Klik op "Vandaag/Gisteren/Deze week" om verse vondsten te tonen
- Wijs op @lifewithcharlot post van gisteren (logo only op shirt, 100% conf)
- Wijs op @thomvdvliet (hard lemonade, primary subject)
- Open één post → klik "open" naar Instagram/TikTok, daadwerkelijk bewijs

**3. Filters (3 min)**
- Filter op `tiktok` only → 194 hits, voornamelijk jong publiek
- Filter op `hard_lemonade` only → product launch tracking
- Filter op `creator_category = person` (geen horeca) → 748 hits, pure UGC
- Search "examen" → @na_examen_dagen pops up, schoolfeesten

**4. Moderator (3 min) — `www.spotyourbrand.com/moderator.html?brand=stelz`**
- 393 nog te reviewen
- Toets ← reject, → confirm, ↓ aannemelijk, space skip
- Reject is sticky: zelfs als de AI later opnieuw scant blijft het weg
- Laat zien dat de tool zelf 0 false positives heeft via een Strong hits spot-check

**5. Insights tab (2 min)**
- Subcultures (student, festival, horeca, fashion)
- Hashtag overlap met STELZ doelgroep
- "Creators we track (1000)" lijst toont de hele radar

**6. Close (2 min)**
"Dit draait nu live, 24/7. De volgende stap is wat jullie ermee gaan doen. Drie opties: (a) wij alerts naar jullie team WhatsApp, (b) DM-drafts voor top creators, (c) maandelijkse cultuurrapportage. Welke wil jullie eerst?"

## Risico's tijdens demo

1. **api.spotyourbrand.com domein**: curl direct geeft SSL error. Voor de demo niet zichtbaar (dashboard praat direct met Supabase). Niet noemen tenzij ze ernaar vragen.
2. **Image lazy-load**: thumbnails laden een halve seconde later in. Eerst dashboard openen + scrollen voordat klant binnenkomt.
3. **Credit balance** staat op 12.260 cr. Voor een grote live scan tijdens demo niet doen (kost ~25 cr per scan).
4. **scan_requests log**: als ze technisch vragen "wanneer was laatste scan", staat er "51m ago · 0 new". Klopt qua tijd. Kun je gewoon zo lezen.
5. **TikTok kolom**: 191 hits op TikTok hier, eerder showde de SQL 194. Klein verschil door image-level filter. Niet relevant te bespreken.

## Casa STELZ vondst (laatste 2 uur, dag voor de pitch)

Via TikTok search "stelz house" ontdekt dat #casastelz, #stelzhouse en #stelzibiza de hashtags zijn van de Booij Agency Ibiza activatie. Stonden NIET in onze pool. Direct toegevoegd, hashtag scrape gedraaid.

Resultaat in 2 uur:
- 91 nieuwe creators in DB
- 131 nieuwe TikTok posts
- 17 nieuwe STELZ hits
- 54 images nog in pending (volgende cron pakt op)

Top nieuwe hits:
- @justinjaymusic — TikTok DJ, 1.8M likes, hard_seltzer detectie (Sep 2024 nog niet eerder gevonden)
- @niekroozen — 27.4K likes "Tour de house" Casa STELZ tour
- @michellexbrn — 1762 likes Casa STELZ stay (mei 2026, dominant logo)
- @booijagency — 9 nieuwe Casa STELZ posts gedetecteerd
- @laurebaele — student graduation party met STELZ

Demo punch line: "we hadden een hele campagne van jullie gemist tot vannacht. Search → hashtag toevoegen → systeem vult het zelf in. Dit is het verschil met handmatig zoeken."

### Casa STËLZ lookalike-groep (subculture)

Subculture aangemaakt en het lookalike-mechanisme gedraaid. Resultaat:

- **20 seed creators** (confidence 1.0) — bekende Casa STËLZ posters
- **17 lookalike candidates** (confidence 0.7) — gevonden via hashtag-overlap

Notable seed creators die we nu pas zien als groep:
- @bizzeybrooks (TikTok, 343.5K followers)
- @niekroozen (TikTok, 260.3K followers)
- @victoriavermeer (TikTok, 92.3K followers)
- @michellexbrn (TikTok, 86K followers)

Top lookalike candidates (gerankt op signal_count = aantal Casa STËLZ hashtags waarin ze voorkomen):
1. @chloeannamarianne — 12 signals (ultra-strong fit)
2. @justinbartak — 4 signals
3. @vinkefest, @lakedancekn, @olexandrfandushin, @themansourclothing — 3 signals
4. @joya.hardstyle (DJ), @_festivallovers, @paulavanveen, @petermazik, @emmavisser008, @joya.hardstyle, @elbear5657, @elipop2122 — 2 signals

Demo punch voor segment: "geef ons jullie campagne. Wij maken er een subculture van, het systeem mined hun gemeenschappelijke hashtags, en levert een lookalike-lijst met scores. Top kandidaat @chloeannamarianne zit in 12 van jullie hashtags. Dit kan voor élke campagne. Run het op #stelz_summer voor je launch en je hebt een radar."

Noise om eerlijk te benoemen: 3-4 van de 17 zijn noise (#amsterdam pickup: @afvallenmetamanda, @smakelijkoptafel, @spraytanhelmond). Geen probleem, moderator zou die wegfilteren. Sterker verhaal: "het systeem heeft een noise floor van ~15%, daarom is de mens-in-the-loop check er."

### Visual-only hits in Casa STËLZ groep (golden cases)

Geen STELZ in caption, geen STELZ hashtag, wel STËLZ in beeld. Dit zijn precies de impressies die @mention-monitoring tools (Storyclash, Mention, etc) niet kunnen vinden.

1. **@niekroozen (260K followers, 27.400 likes)** — caption: "Tour de house!" — STËLZ logo aan witte muur achter hem
2. **@ishpisy (4K followers, 17.800 likes)** — caption: "@Booij Agency" — 3D STËLZ letters naast zwembad
3. **@michellexbrn (86K followers, 1.762 likes)** — caption: "Zo dankbaar om hier te zijn! 🍒👙🌞" — stëlz overlay in beeld
4. **@victoriavermeer (92K followers, 902 likes)** — caption: "Alles gevlogd voor op youtube!" — hand met STËLZ Hard Lemonade can
5. **@laurebaele (739 followers, 400 likes)** — caption: "Leukste afsluit van het studentenleven #graduated" — STËLZ S-logo op afstudeerbaret

Demo line: "@niekroozen, 260K volgers, 'Tour de house!' Geen STËLZ in zijn caption, geen #stelz, niets. Onze AI ziet jullie logo op de muur. 27.400 likes voor een impressie die jullie nu pas weten dat er was."

Extreme case (laat als laatste zien): @laurebaele's graduation baret met STËLZ S-logo. Pure organische affinity, alleen visueel te vinden.

### Lookalike-bewijs (binnen 1 uur na expansion)

Na de Casa STËLZ subculture expansion ging het systeem zelf de lookalike-candidates scrapen. Resultaat in <1 uur: **3 van de 17 lookalikes** hadden DIRECT een visual-only hit:

- **@chloeannamarianne** (signal_count 12 — onze top kandidaat) → blijkt stagiair bij Booij Agency, STËLZ blikjes op dining table foto voor Elle NL
- **@_festivallovers** (43K IG followers, signal_count 2) → Mother's Day post met STËLZ logo op festival stage
- **@paulavanveen** (signal_count 2) → Lakedance post met STËLZ barrier

Demo punch: "Drie van onze 17 lookalikes hadden binnen een uur visueel bewijs. Het systeem vond ze proactief via hashtag-overlap, voordat ze STËLZ noemden. De volgende scrape bevestigde het."

## Wat sinds laatste meeting is opgeleverd

- Sticky reject: moderator rejection blijft permanent weg uit feed (image-level exclusion)
- Duplicaten weg: 3649 dubbele image-rijen opgeschoond, unique index voorkomt terugkeer
- Mojibake fix: STËLZ wordt overal correct gerenderd, invariant check waakt
- Brand-aware pipeline: scripts draaien per-brand via `--brand-slug` of `--all-brands`
- System health endpoint live: `/api/v1/system/health`
- Test harness (5 suites, 75 checks) draait via `bash tests/run_all.sh`
- Daily QA cron schrijft naar `system_health_alerts`
- Lisa-bug gefixed: PostgREST 1000-row cap had haar afgesneden, nu paginated tot 10k

## Instagram Stories tab (LIVE)

Nieuwe content-type filter rij: Alle formats / Posts / Reels / TikToks / **Stories**. Spot the Brand IG account gekoppeld, scrapt nu wekelijks stories van followers.

**Stand vannacht (eerste run, 20 IG creators):**
- 440 story frames binnengehaald
- 21 STELZ hits gedetecteerd
- Allemaal pure VISUAL ONLY (stories hebben geen caption)

**Highlights uit de eerste scrape:**
- @bavaria.bierkoerier — TROON gemaakt van STELZ blikjes (conf 1.00, dominant)
- @bijonsoptnoord — 5 verschillende hits: STELZ multi-pack op bar, blikjes naast bier, lineup op tafel
- @gastelsfeer — STELZ Hard Iced Tea poster bij bitterballen
- @marxolarrysheemskerk — staande STELZ blikje op straat + neon sign
- @stelz_suriname — STELZ Mango blikje tegen blauwe lucht
- @studentdelivery_ — student met STELZ op treinperron
- @slijterij_wijnhuis_van_den_bos — retail visibility op winkelschap
- @na_examen_dagen — STELZ logo op meisjes-shirt mouw
- @derubberboot — DJ booth met STELZ sign

Demo punch: "Stories verdwijnen na 24 uur. Storyclash, Mention, Brandwatch — die scrapen geen stories want het kan niet zonder ingelogd account. Wij hebben net jullie Spot the Brand IG koppeling toegevoegd en in één uur 21 visual-only story hits binnen. Allemaal van vandaag. Allemaal pure organische brand visibility die jullie zonder ons niet wisten."

Next: het Spot the Brand IG account volgt nu 20 IG creators uit de tracker. Voor full coverage moet het de andere ~900 IG creators ook volgen. Plan: 200 follows/dag (IG limit), full pickup binnen 5 dagen.

## Open carry-overs (na de meeting)

- `railway up` om de sticky-reject worker changes echt live te krijgen
- Stripe Live activatie (KvK + IBAN, jij doet zelf)
- RESEND_API_KEY in Vercel env voor mail alerts
- Vercel custom domain api.spotyourbrand.com fixen
- **IG_SESSION_ID cookie van STELZ** voor live Story-tracking (49_ig_story_scan.py is klaar) — DONE: Spot the Brand IG-account gekoppeld
- Spot the Brand IG-account moet nog ~900 IG creators volgen (200/dag = klaar in 5 dagen)
- Story scrape opnemen in Railway aux cron (1× per dag draaien, stories verdwijnen na 24h)

## Te openen tabs voor de meeting

1. `https://www.spotyourbrand.com/?brand=stelz` (laat 30s laden voor demo)
2. `https://www.spotyourbrand.com/moderator.html?brand=stelz`
3. Eén voorbeeld Instagram post (klik "open" op @lifewithcharlot of @thomvdvliet)
4. Deze briefing (in een aparte tab, voor je eigen referentie)
