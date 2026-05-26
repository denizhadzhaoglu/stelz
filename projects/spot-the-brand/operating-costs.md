# Spot Your Brand · Operating Costs

Last updated: 2026-05-22

Real numbers based on 30-day usage for the STELZ pilot (1 brand, 4.066 creators tracked, daily scan + 4h story scan).

## Usage baseline (last 30 days)

| Metric | Value |
|--------|------:|
| Content items scraped | 23.498 |
| Images cached | 20.721 |
| Vision-AI detections | 24.259 |
| Creators tracked | 4.066 |
| Verified STELZ hits | 2.578 |
| Daily scan runs | 30 |
| 4h story scans | ~180 |

## Monthly cost per service

### Apify (scraping)
| Actor | Volume/mo | Unit price | Cost/mo |
|---|---:|---:|---:|
| Instagram Profile Scraper | ~17.000 results | $2.30 / 1k | ~€36 |
| TikTok Scraper (free actor) | ~6.000 results | €0 | €0 |
| Instagram Stories (now via direct IG API — Apify cost dropped) | n/a | n/a | €0 |
| Hashtag scrapes (Casa STELZ etc.) | ~500 results | $2.30 / 1k | ~€1 |
| **Subtotal Apify** | | | **~€37–€60** |

Note: we just replaced the Apify story actor with a direct IG-API call using our session cookie. That saves ~€40/mo and gives us better data quality.

### Google Gemini (vision AI detection)
| Component | Volume/mo | Cost |
|---|---:|---:|
| Image detections (Gemini 2.5 Flash) | ~24k detections × 51 image inputs (50 refs + 1 target) at 258 tokens each | |
| Total input tokens | ~315M | ~€22 |
| Output tokens | ~5M | ~€1 |
| **Subtotal Gemini** | | **~€25** |

Note: free tier covers a chunk of this. In practice we've been hitting daily quota with 1 brand at scale — we use 2-3 keys with rotation. A single paid key with billing enabled lifts the limit entirely.

### Supabase (database + storage + edge)
| Component | Tier | Cost/mo |
|---|---|---:|
| Database (~50MB indexed) | Pro tier required for daily traffic | $25 = €23 |
| Storage (~1GB cached images) | Included in Pro | €0 |
| Bandwidth (~5GB/mo) | Within Pro limit | €0 |
| **Subtotal Supabase** | | **€23** |

### Hosting
| Service | Use | Cost/mo |
|---|---|---:|
| Vercel Pro | Dashboard + deck hosting | $20 = €18 |
| Railway (cron worker) | Daily scan + story cron + detection | ~€18 |
| Domain (spotyourbrand.com) | Averaged over a year | ~€1 |
| **Subtotal Hosting** | | **~€37** |

### One-off / incidental
| Item | Cost |
|---|---:|
| Higgsfield image generation (deck visuals) | €15 paid, not recurring |
| IG_SESSION_ID cookie | €0 (own account) |
| Domain registration | €12/year |

## Total per brand (current scope)

| Scenario | Apify | Gemini | Infra | **Total/mo** |
|---|---:|---:|---:|---:|
| **Lean** (current STELZ) | €37 | €25 | €60 | **~€122** |
| **Realistic** | €60 | €60 | €80 | **~€200** |
| **Heavy** (10k creators, dense tracking) | €120 | €150 | €120 | **~€390** |

Sweet spot for a single mid-size brand: **~€150–€200/maand** in operating cost.

## Scaling — what changes at N brands

| N brands | Apify | Gemini | Supabase | Vercel + Railway | **Total/mo** | **Per brand** |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | €60 | €60 | €23 | €36 | **€180** | €180 |
| 5 | €250 | €280 | €50 | €40 | **€620** | €124 |
| 10 | €500 | €560 | €100 | €60 | **€1.220** | €122 |
| 25 | €1.200 | €1.300 | €300 | €120 | **€2.920** | €117 |
| 50 | €2.400 | €2.600 | €550 (Team) | €200 | **€5.750** | €115 |
| 100 | €4.800 | €5.200 | €1.100 | €350 | **€11.450** | €114 |

Per-brand cost converges around **€115–€125/maand** at scale. Most of it is variable (Apify + Gemini scale linearly); only Supabase and hosting are step-function.

## Cost per outcome

Based on STELZ pilot:
- **€0.005 per detection** (24k detections, ~€122 total)
- **€0.047 per verified STELZ hit** (2.578 hits, ~€122 total)
- **€0.030 per creator tracked** (4.066 creators)

For comparison, a single influencer post from a tier-2 creator costs €500–€1.500. Spot Your Brand surfaces ~80 organic hits per month per brand at €1–€2 each.

## Margin model (internal — not in deck)

If the product sells at €500/mo per brand:
- Lean COGS: €122 → gross margin **~76%**
- Realistic COGS: €200 → gross margin **~60%**

If the product sells at €1.500/mo per brand:
- Lean COGS: €122 → gross margin **~92%**
- Realistic COGS: €200 → gross margin **~87%**

Healthy SaaS margins start at 70%. Spot Your Brand sits comfortably above that on every tier.

## Cost reduction levers we haven't pulled yet

1. **Gemini cache prompt prefix** — the 50 reference images stay constant. Anthropic-style prompt caching on Gemini Flash would cut Gemini cost by ~80%.
2. **Apify batch consolidation** — combine creators in fewer actor runs. Already partly done; can squeeze another 20%.
3. **Self-host moderator queue** — currently rides on Supabase; a redis micro-instance would shave Supabase egress.
4. **Image compression** — IG CDN images are ~80KB avg. Resampling at cache-time to 720px max could cut storage 50% (irrelevant at current scale, matters at 100+ brands).

## Open questions

- Apify cost above is estimated from current Apify pricing pages. Actual invoice from Apify is the source of truth — pull and reconcile monthly.
- Gemini billing has a free tier with daily quota that we currently rely on across 2-3 keys. Switching to a single paid key with billing removes operational fragility but raises the visible monthly cost.
- Railway worker costs are a guess — verify against actual Railway invoice.
