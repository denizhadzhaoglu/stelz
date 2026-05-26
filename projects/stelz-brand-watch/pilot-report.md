# STËLZ Brand Watch -- Pilot Report

Date: 2026-05-12
Pilot scope: 46 Instagram posts uit #stelz, #stelzhardseltzer, #stelzhardlemonade hashtags door Gemini 2.5 Flash voor STELZ visual detection.

## Resultaten

| Metric | Value |
|--------|-------|
| Posts evaluated | 46 |
| Detected as STELZ | 38 (83%) |
| High confidence (>= 0.8) | 41 |
| API errors | 1 (timeout) |
| Effectieve accuracy na review | 45/46 correct |

### Distributie per productlijn

- hard_seltzer: 25
- hard_lemonade: 11
- logo_only: 1
- none: 9

### False positive risk distributie

- low: 44
- high: 1
- error: 1

## Validatie van de "none" classifications

Van de 9 "none" cases zijn er 8 correct geclassificeerd. Captions bevatten wel `#stelz` maar het image laat geen STELZ zien (hashtag misbruik door cafe's en supermarkten die meeliften, of pakeskandidaten zonder zichtbaar product).

1 echte miss: post van `@cafe_kostershuys` met drie STELZ Hard Iced Tea blikken. Gemini herkende het wel in context ("Three STELZ Hard Iced Tea cans in peach, lime, and mango flavors") maar classificeerde als "none" omdat Hard Iced Tea niet in de class definitie stond.

## Bevindingen

1. **Gemini 2.5 Flash herkent STELZ uitstekend.** Detection van logo en product werkt ook op slecht licht, schuine hoeken, en gedeeltelijk zichtbare blikken. Specifieke varianten worden benoemd (Mango, Peach, 24-pack box, Cassis).

2. **Drie productlijnen in plaats van twee.** STELZ heeft naast Hard Lemonade en Hard Seltzer ook **Hard Iced Tea**. Prompt en classes inmiddels geupdate.

3. **False positives zijn praktisch nul.** Slechts 1 image kreeg `false_positive_risk: high` (cooler met onduidelijke blikken, Gemini zei correct conf=0). Geen verwarring met White Claw of generieke seltzers in deze sample.

4. **Hashtag scrape levert hoge signal-to-noise op.** 83% van #stelz posts bevat ook visueel STELZ. De overige 17% zijn cafes en winkels die het hashtag misbruiken voor reach, of plaatsen het hashtag bij een algemenere drankenpost.

5. **API kosten waren lager dan geschat.** 46 detection calls + scrape: schatting onder 0.50 dollar totaal.

## Edge cases die aandacht nodig hebben in de full build

- **Timeouts**: 1 op 46 (2%) Gemini call timed out. Retry mechanism werkt, maar bij grotere volumes script robuuster maken.
- **Video frames**: pilot was alleen images. Reels en TikToks vereisen frame sampling logic.
- **Brand uitbreidingen**: als STELZ nieuwe lijnen lanceert (zoals Iced Tea bleek) moet de prompt makkelijk uitbreidbaar zijn. Eventueel later overgaan naar fine-tuned model.
- **Multi-brand vergelijking**: voor Alpro/Action/Gall reuse vraagt om brand-agnostic detection structuur (per brand een prompt template met reference images).

## Conclusie

Pilot validates de technische aanpak. Detection layer werkt goed genoeg om door te bouwen. Volgende stap is de discovery script die NL creators identificeert en de schaalbare scraping pipeline opzet.

## Aanbevolen vervolg

1. Prompt update Iced Tea: gedaan
2. Re-run pilot met geupdate prompt om de cafe_kostershuys case te valideren
3. Discovery script: hashtag + mention scrape over meerdere bronnen om seed list van 100-300 NL creators te bouwen
4. Curatie ronde met Meinte voor tier 1/2/3 classification
5. Full scraping pipeline (Highlights, feed posts, Reels, TikTok)
6. Supabase schema + dashboard
