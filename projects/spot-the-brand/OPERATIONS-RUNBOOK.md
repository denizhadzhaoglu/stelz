# Spot the Brand — Operations Runbook (Hermes)

Laatst bijgewerkt: 2026-05-19

## Rolverdeling

| Wie | Rol | Verantwoordelijkheid |
|-----|-----|---------------------|
| Meinte | CEO | Goedkeuring, strategie, klantcontact, final calls |
| Hermes | Operations | Monitoring, development, deploys, marketing prep, rapportage |

**Regel: Hermes bereidt voor, Meinte keurt goed.** Geen live deploys, klantcommunicatie, of betalingswijzigingen zonder akkoord.

---

## Dagelijkse Operations (via cron)

### 1. Health Check (elke 6 uur)
- API status: GET /api/v1/brands (response time + status)
- Worker: check scan queue depth + stuck scans
- Detection rate: FP percentage per brand
- Budget: Apify + AI kosten vs cap

### 2. Ochtend Briefing (08:00 CET)
- Nieuwe detections afgelopen 24u
- Scan throughput + success rate
- Kosten overzicht (Apify, Gemini, totaal)
- Actiepunten die goedkeuring nodig hebben

### 3. Weekly Report (maandag 09:00)
- KPIs: creators gescand, hits gevonden, FP rate, kosten
- Vergelijking met vorige week
- Backlog prioriteiten
- Aanbevelingen voor Meinte

---

## Credentials & Endpoints

| Service | URL | Auth |
|---------|-----|------|
| API | https://spot-api-eight.vercel.app/api/v1 | Bearer token in cli/.local-token |
| Dashboard | https://www.spotyourbrand.com | Supabase auth |
| Supabase | Via SUPABASE_URL in PA/.env | Service role key |
| Worker | Railway (stelz-brand-watch) | Railway dashboard |
| Stripe | Test mode (sk_test_...) | In PA/.env |
| Demo | demo@spotyourbrand.com / SpotTheDemo2026! | — |

---

## Goedkeuringsmatrix

| Actie | Mag Hermes zelfstandig? |
|-------|------------------------|
| Health check / monitoring | ✅ Ja |
| Bug fix in code (non-breaking) | ✅ Ja, rapporteer achteraf |
| Vercel deploy (API) | ⚠️ Alleen na akkoord |
| Railway deploy (worker) | ⚠️ Alleen na akkoord |
| Stripe live mode activeren | ❌ Meinte doet dit |
| Klant emails versturen | ❌ Draft → Meinte review |
| IG posts publiceren | ⚠️ Content prep ja, publicatie na akkoord |
| Nieuwe prospect outreach | ❌ Draft → Meinte review |
| Database migratie | ❌ Alleen na akkoord |
| Pricing wijzigingen | ❌ Alleen Meinte |
| Kosten > €10/dag | ⚠️ Alert naar Meinte |

---

## Project Locaties

| Component | Pad |
|-----------|-----|
| API | .../spot-the-brand/api/ |
| CLI | .../spot-the-brand/cli/ |
| Worker | .../stelz-brand-watch/railway-worker/ |
| Dashboard | .../stelz-brand-watch/dashboard/ |
| Docs | .../spot-the-brand/*.md |
| Env vars | ~/Documents/Jackandai/PA/.env |

Worktree root: ~/Documents/Jackandai/PA/.claude/worktrees/eloquent-kirch-04cfde/projects/

---

## Huidige Prioriteiten

### Sprint 1 (deze week)
1. ☐ Scan rebalancing deployen (lokaal klaar)
2. ☐ Health monitoring cron opzetten
3. ☐ IG @spotyourbrand eerste 5 posts voorbereiden
4. ☐ Stripe live mode checklist voor Meinte
5. ☐ Cold email drafts voor top-5 prospects

### Sprint 2 (volgende week)
1. ☐ Discovery v2: hashtag co-occurrence
2. ☐ Meta Ads account setup
3. ☐ FP rate verlagen naar <15%
4. ☐ Dashboard UX improvements
5. ☐ Tweede brand onboarden (als Meinte prospect binnenhaalt)
