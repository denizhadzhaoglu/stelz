# STËLZ Brand Watch

Eigen monitoringtool voor STËLZ. Detecteert het merk in social content (ook ongetagd) via logo en productherkenning. Schraapt zowel historisch (Highlights, feed posts, Reels, TikTok) als live.

**Client:** STËLZ
**Status:** Spec phase
**Type:** Test build, fundament voor JackandAI productized intelligence module
**Lead:** Meinte
**Team:** TBD (Mette of Yassin voor pipeline, Marleen voor data)

## Doel
Inzicht in wie er content maakt over STËLZ in Nederland (creators, fans, merken) zonder afhankelijk te zijn van mentions of tags. Visuele detectie op logo en productverpakking.

## Scope MVP
- Platforms: Instagram (Highlights, feed, Reels) en TikTok
- Markt: Nederland
- Historisch: tot een jaar terug voor publiek beschikbare content
- Live: dagelijkse crawl van seed list creators
- Output: dashboard met hits, creator profielen, content thumbnails, filters

## Out of scope (voor MVP)
- Live Instagram Stories archive opbouwen (parkeren tot na MVP)
- YouTube en Twitter
- Sentiment analyse
- Multi-tenant (alleen STËLZ in eerste versie)

## Documenten
- `spec.md` De volledige technische spec
- `discovery-plan.md` Hoe we de seed list creators vinden
- `cost-estimate.md` Apify, Gemini, hosting kosten

## Strategische context
Als dit werkt voor STËLZ, herbruikbaar voor Alpro, Action, Gall. Zelfde pipeline, andere logo references. Onderdeel van JackandAI Intelligence layer.
