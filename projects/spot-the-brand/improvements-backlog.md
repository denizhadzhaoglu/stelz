# Spot the Brand · Improvements backlog

Autonomously brainstormed during the overnight extended session (15 May 2026, 01:30 NL). Items prioritized by impact / cost. Top items (★) implemented overnight; rest queued for follow-up.

## 1. Scrape precision

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | **Creator graph expansion**: when a creator becomes tier-1, scan who they tag + are tagged with. Network effect for discovery. | High | Low (no extra API cost, reuses existing Apify) | ★ Implementing |
| 2 | **Handle-variant dedup**: normalize `firstname.lastname` / `firstnamelastname` / `firstname_lastname` so we don't count the same person 3× | High | Trivial | ★ Implementing |
| 3 | Multi-resolution scanning: download original IG photo at full res, not just downscaled thumb. Better for small product placement. | Med | Bandwidth +20% | Backlog |
| 4 | TikTok video keyframe extraction: pull 5 frames/video instead of just thumb. Catches in-video product placement currently missed. | High | Apify +30%, Gemini +30% | Backlog |
| 5 | IG Stories scraping: currently only feed posts. Stories are where most "in-the-moment" brand mentions live. | Very High | Apify dedicated actor | Backlog |
| 6 | Cross-platform identity match: same person @handle on IG = @handle on TikTok, merge their reach numbers | Med | Low | Backlog |
| 7 | Smarter scheduling: learn each creator's posting cadence + only scrape on their active days. | Med | Saves Apify cost | Backlog |
| 8 | Hashtag co-occurrence learning: when a brand-hit happens, log all co-occurring hashtags and auto-suggest them for the brand's pool | Med | Trivial | Backlog |
| 9 | "Discovery weight" per source: track which seed source (hashtag X vs creator Y vs subculture Z) yields the most tier-1 hits, prioritize | High | Trivial | Backlog |

## 2. Detection precision

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | **Crop-and-zoom pass**: for low-confidence detections (0.5-0.7), crop the bounding-box region + re-run Pro at higher res. Catches small but real placements. | High | Pro re-verify ~€0.01/image | ★ Implementing |
| 2 | Per-category-prompt: different prompt for "can in hand" vs "shelf display" vs "screen-in-screen". Currently one-size-fits-all. | Med | None | Backlog |
| 3 | Negative reference packs: explicitly tell the model what looks similar but isn't (lookalike packshots) | High | None | Backlog |
| 4 | OCR text detection on product label: confirms brand name reading in addition to visual recognition | Med | Gemini OCR | Backlog |
| 5 | Color histogram pre-filter: skip pre-detection any image without brand-relevant color signature. Cuts Flash cost ~30%. | Med | None (saves money) | Backlog |
| 6 | Multi-model voting: Flash + Pro + Claude vision → ensemble decision on contested images | Low (Pro already does this) | High Claude cost | Backlog |
| 7 | Active learning: present moderator the top-N "model disagreement" images each day for labeling. Auto-tune prompts. | Very High | Low | Backlog |
| 8 | Confidence calibration: per-product-line accuracy stats, adjust thresholds dynamically | Med | None | Backlog |

## 3. Operational / cost control

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | **Per-brand cost budget + alerts**: track Apify+Gemini spend per brand, alert at 80% of plan credit | High | None | ★ Implementing |
| 2 | Auto-scale: scan_queue depth > N → spin up extra Railway worker replica | Med | Higher Railway cost when busy | Backlog |
| 3 | Health dashboard for ops: scan throughput, error rate, cost/detection trend | Med | None | Backlog |
| 4 | A/B test framework for prompts: shadow-run prompt v5 alongside v4, compare on same images | Med | 2× detection cost during test | Backlog |
| 5 | Auto-archive low-engagement creators more aggressively (currently archived on 0 hits/90d, push to 0 hits/30d for high-volume brands) | Low | None | Backlog |
| 6 | Disaster recovery plan: nightly DB dump to off-site S3 bucket | High (data safety) | €2/mo S3 | Backlog |
| 7 | Privacy: PII redaction option (face blurring) for screenshots in PDF reports | Med (B2B sensitive) | Compute time | Backlog |

## 4. Product / UX

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | Real-time scan progress via Supabase Realtime (websockets) instead of polling | Med | None | Backlog |
| 2 | Creator outreach DM generator: given creator profile, generate a personalized intro DM | High | Gemini call per generation | Backlog |
| 3 | Competitive tracking: brand X also tracks "competitors" so we scan their hashtags + creators | High | Higher Apify cost per brand | Backlog |
| 4 | Trend detection: rising-creators algorithm (week-over-week velocity) | Med | None | Backlog |
| 5 | Geographic heat map of mentions | Low | Need location data | Backlog |
| 6 | Sentiment trend chart per creator (positive/neutral/negative drift) | Med | None (sentiment already scored) | Backlog |
| 7 | PDF report customization per brand (logo, accent color, sections to show/hide) | Med | None | Backlog |
| 8 | CSV/JSON API export for BI tools | Low | None | Backlog |
| 9 | Role-based email digests: owner = summary, editor = full feed, viewer = none | Low | None | Backlog |
| 10 | Slack slash commands (`/spot stelz top creators last week`) | Med | Slack app config | Backlog |

## 5. Sales conversion / growth

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | **"Try with your handle" live preview**: landing page accepts brand IG handle → runs a 30-second mini-scan → shows what we'd find | Very High | Gemini call per preview, ~€0.05 | ★ Implementing |
| 2 | UTM-personalized landing pages: ?utm_brand=heineken → swap STELZ examples for hypothetical Heineken | High | None | Backlog |
| 3 | ROI calculator widget on landing | Med | None | Backlog |
| 4 | Case study auto-generator: turn STELZ data into PDF case-study any sales rep can send | High | Gemini for writing | Backlog |
| 5 | Referral program (give a brand a month, get a month) | High | Stripe coupon logic | Backlog |
| 6 | Public "leaderboard" of brand monitoring stats (top tracked brands, etc.) | Med (SEO + social) | None | Backlog |
| 7 | "Spot the Brand for X" template landing pages: F&B, beauty, automotive | Med | None (manual content) | Backlog |
| 8 | Affiliate program for agencies that resell | High | Stripe Connect | Backlog |

## 6. Multi-tenant scale prep

| # | Idea | Impact | Cost | Status |
|---|------|--------|------|--------|
| 1 | DB partitioning of `detections` by brand_id when row count > 10M | Med | None | Backlog (wait til 50+ brands) |
| 2 | Multi-region scraping: route Apify to NL/DE/FR proxies based on brand HQ | Med | Apify proxy cost | Backlog |
| 3 | Shared cache for celebrity creators: if 5 brands all track Monica Geuze, scrape her once | High (cost savings) | Refactor | Backlog |
| 4 | Brand-scoped reference image bucket (private per brand) instead of shared `brand-watch-thumbnails`. RLS aan op storage. | High (privacy) | Migration work | Backlog |
| 5 | White-label deploys: `watch.brand.com` CNAME → tenant-specific dashboard | High (enterprise sales) | Vercel + DNS | Backlog |

## How items get picked up

- Items marked ★ are being implemented in this autonomous session
- Backlog items live here, surface in weekly review (Meinte + Lukas)
- Each item can be promoted by adding `[Promoted: 2026-XX-XX]` next to it
- When implemented, move into the Spot the Brand changelog
