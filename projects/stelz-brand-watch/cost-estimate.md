# STËLZ Brand Watch -- Cost Estimate

Ruwe inschatting bij seed list van 200 creators, dagelijkse monitoring.

## Apify

Apify rekent in compute units (CU). Per actor verschillend.

Eenmalige historische sweep:
- 200 creators x Instagram profile scrape (12 maanden) = ca. 30 dollar
- 200 creators x Highlight scrape = ca. 20 dollar
- 200 creators x TikTok scrape = ca. 25 dollar
- Hashtag discovery sweep (10 hashtags, 1000 posts each) = ca. 15 dollar
- Totaal eenmalig: ca. 90 dollar

Doorlopend per maand:
- Dagelijkse refresh seed list (200 creators, gemiddeld 5 nieuwe items per dag) = ca. 80 dollar
- Wekelijkse hashtag scan = ca. 30 dollar
- Totaal maandelijks: ca. 110 dollar

## Gemini Vision

Gemini 2.5 Flash prijzen (input/output tokens). Image input is ca. 258 tokens per image.

Schatting:
- 30.000 images per maand door pipeline
- Input cost: ca. 4 dollar
- Output cost: ca. 2 dollar
- Totaal maandelijks: ca. 6 tot 15 dollar

## Supabase

Pro plan: 25 dollar per maand. Voor MVP volume genoeg.

## Vercel

Hobby tier gratis tot we live monitoring veel cron werk doet. Anders Pro: 20 dollar per maand.

## WhatsApp notifications

Via bestaande integratie, geen extra kosten.

## Totaal maandelijks (na build)

| Item | Kosten |
|------|--------|
| Apify | 110 |
| Gemini Flash | 15 |
| Supabase Pro | 25 |
| Vercel Pro | 20 |
| **Totaal** | **170 dollar / maand** |

Plus eenmalig 90 dollar voor historische sweep.

## Vergelijking Storyclash

Storyclash entry plan grofweg 800 tot 1500 euro per maand. Break-even na 1 maand. Plus eigenaarschap data en logica.

## Risico's op kosten

- Apify CU consumption kan tegenvallen als we te veel content per creator pullen. Mitigatie: limits per scrape job.
- Gemini Vision goedkoop op Flash, maar als we Pro nodig hebben voor accuracy gaat het naar ca. 50 tot 100 dollar per maand.
- Supabase storage als we full resolution images bewaren. Mitigatie: alleen thumbnails opslaan, originelen via URL referentie.

## Budget vraag

Voor test fase met STËLZ: wie betaalt? Voorstel: STËLZ betaalt 300 euro per maand tijdens test (3 maanden), dekt alle kosten plus buffer. Daarna pricing als doorontwikkeld product.
