# Discovery v2 — strategy

The thing that determines whether Spot the Brand is a product or just a dashboard: how well we find creators a brand wouldn't otherwise know about.

This document defines the v2 discovery architecture, what we measure, and which sources we prioritize.

## 1. The strategic claim

> Spot the Brand is a **measured funnel** for creator discovery, not a fire-and-forget scraper.

Every creator we add to a brand's workspace can be attributed to a source. Every source can be evaluated on conversion (did this creator yield a real brand hit?) and quality (did they yield a tier-1 / tier-2 promotion?). The system **learns** which sources are worth more scrape budget for each brand, instead of treating all sources equally.

This is what separates us from competitors. They scrape; we route attention.

## 2. The current state (15 May 2026)

Honest read from the discovery-health report:

| Source | Total | Hit % | Tier 1 | Avg AI | Σ hits | Hits/winner |
|--------|------:|------:|------:|------:|------:|------------:|
| `legacy_seed` | 1892 | 18.1% | 14 | 3.3 | 1432 | 4.2 |
| `subculture_expansion:*` | 113 | 0%* | 0 | – | 0 | – |
| `hashtag:stelz` | 9 | **55.6%** | 0 | 4.6 | 10 | 2.0 |
| `perplexity_scout` | 4 | 0%* | 0 | 10.0 | 0 | – |
| `hashtag:drinkstelz` | 1 | 0%* | 0 | 8.0 | 0 | – |

\* the four sources marked 0% were promoted in the last hour; their creators haven't been scraped yet. Numbers will update after the next daily_scan cycle.

What this tells us:
- **Brand hashtag discovery is gold** (55.6% hit rate, 13× the baseline). Every new brand we onboard should run aggressive hashtag scraping on their own brand-tag + product-line tags from day one.
- **Legacy seed (one-shot harvest)** carries most of our absolute volume but at only 18% conversion. Inefficient.
- **Subculture expansion** is the broadest discovery surface (113 candidates in a few days) but conversion is unproven — that's the next thing we measure.
- **Perplexity scout** wasn't running. Now it is, daily.

## 3. Sources we run today

### 3a. Hashtag discovery (auto_add.py)
Scrape the brand's own hashtag pool (#brand, #product_line, related tags) and add creators that appear N+ times.
- **Strength**: highest hit rate (55%+).
- **Weakness**: only finds people who use the hashtag. Misses the 80%+ who post without tags.
- **Budget**: maintain. Daily cron, per-tag scrape limit 200.

### 3b. Subculture expansion (expand_subculture.py)
For each defined subculture (student_life, vrijmibo, festivals, etc.) the LLM finds creators that fit. Goes into discovery_queue, promoted at signal_count ≥ 2.
- **Strength**: broadest surface. Finds people OUTSIDE the brand-hashtag bubble.
- **Weakness**: unmeasured conversion yet. May find creators whose audience is right but who don't actually post product content.
- **Budget**: maintain. Add new subcultures as brands onboard with their own taxonomy.

### 3c. Creator graph expansion (creator_graph_expand.py)
For each tier_1 creator, mine @-mentions in their brand-hit posts. Their network = potential candidates.
- **Strength**: network effect. Tier-1 creators often hang out with other tier-1 creators.
- **Weakness**: only works once tier-1 creators exist. Useless cold-start. Bootstrap problem.
- **Budget**: maintain. Runs in 5-min aux cycle.

### 3d. Perplexity scout (perplexity_scout.py)
Weekly web intelligence: who has the brand recently partnered with, who's been writing about the brand, who's in the activations.
- **Strength**: finds named creators we wouldn't otherwise see (press coverage, partnerships).
- **Weakness**: parsing-dependent. Extracted handles need validation. False positives common.
- **Budget**: daily run starting now (was previously not scheduled). Tighter handle validation needed.

### 3e. Manual seed (popular_nl_creators.py, etc.)
One-shot lists of known accounts.
- **Strength**: instant relevant baseline for a new brand.
- **Weakness**: one-time, doesn't compound.
- **Budget**: keep for cold-start. Each new brand gets a manual seed pass.

### 3f. TikTok hashtag harvest (tiktok_harvest.py)
Same logic as IG hashtag but TikTok-side.
- **Strength**: TikTok creators dominate younger demographics; brand visibility on video.
- **Weakness**: thumbnail-only detection misses in-video product placement (without keyframe extraction).
- **Budget**: maintain. Add keyframe extraction in v2.1.

## 4. Sources we don't yet have

### 4a. IG Stories scraping (stories_harvest.py — built, awaiting actor activation)
Most "in-the-moment" brand activations happen in Stories. They expire in 24h.
- **Status**: script ready, Apify actor returns 0 (creators aren't posting active stories at test time). Production-test required.
- **Priority**: HIGH. Stories are where festival / Vrijmibo / impromptu brand visibility lives.

### 4b. Cross-platform identity match (link_creator_identities.py — built)
Same person on IG + TikTok counts as one creator with combined reach.
- **Status**: live. 1 STELZ creator linked. Will compound as brand grows.

### 4c. Active-learning training loop (train_from_moderator.py — fixed today)
Moderator decisions feed back as few-shot examples for the next Pro verify pass. Closes the feedback loop.
- **Status**: live. 12+12 STELZ training examples in Storage.

### 4d. Hashtag co-occurrence learning (hashtag_learning.py)
When a creator hits, log all their other hashtags. The ones that co-occur frequently with hits become new pool candidates.
- **Status**: built, not auto-running. Should run weekly.
- **Priority**: MEDIUM. Adds smart hashtag expansion without manual curation.

### 4e. Competitor tracking
A brand opts in to also track 2-3 named competitor brands. Their creators become ours via "anyone tagging competitor + posting our category" cross-reference.
- **Status**: not built.
- **Priority**: MEDIUM. Strong sales hook for brand managers.

### 4f. Time-windowed surge discovery
Pre-scan against known event spikes: King's Day, festival season, exam-week vrijmibo, Christmas markets. Higher scrape budget during the window.
- **Status**: not built.
- **Priority**: LOW. Nice-to-have, marginal impact.

## 5. The v2 architecture decisions

### 5a. Every creator gets a source tag (now live)
`auto_added_via` is required on every insert path. Backfilled `legacy_seed` for pre-attribution data. Three direct-insert scripts patched to set it going forward.

### 5b. Denormalized stats (now live)
`posts_seen`, `hits_seen`, `last_hit_at` refreshed via `refresh_creator_stats()` after every scan + every aux-cycle. Source of truth for funnel measurement.

### 5c. Bulk-promote standing pool (one-shot completed today)
144 stuck pending candidates from subculture_expansion + perplexity got promoted. Going forward, the discovery_queue → creators promotion needs to happen automatically for ALL sources, not just hashtag-based via auto_add.py.

**Open task**: extend `auto_add.py` or split into a separate `48_promote_queue.py` that walks `discovery_queue` for ALL sources where `signal_count >= threshold` and promotes them.

### 5d. Discovery health report (now live)
`49_discovery_health.py --brand <slug>` produces per-source funnel. Run weekly. Decisions about scrape budget per source come from this report.

### 5e. Source-aware budget weighting (next)
Today each hashtag in the pool gets equal scrape attention. v2: weight scrape budget by historical hit rate. If `#stelz` yields 55% and `#weekend` yields 5%, give `#stelz` 5× more scrape calls.

**Status**: not built. Requires per-tag stats roll-up. Quick win once we want it.

### 5f. Source-aware AI scoring (next)
The AI relevance scorer (`21_ai_score_creators.py`) gives every creator a 0-10 score. v2: feed the source into the prompt so AI knows "this creator came from subculture:vrijmibo, evaluate fit against vrijmibo audience". Better signal.

**Status**: not built.

## 6. The KPI dashboard

These metrics should be on the operator's monitoring panel:

| Metric | Target | Reason |
|--------|--------|--------|
| Hit rate per source | track + alert if drops > 5% | source efficiency |
| Median time-to-first-hit per source | track | speed-to-signal |
| Tier 1 conversion rate per source | track + alert if 0% for 4 weeks | quality |
| Total active creators per brand | track | scale |
| Daily scrape cost / total hits | track + cost cap | efficiency |
| Days since last discovery from source X | alert if > 2× usual | freshness |

## 7. What "winning at discovery" looks like 12 months out

- **Per-brand source mix tuned automatically**: each brand has a different optimal blend. Mature brands lean on graph expansion; new brands on hashtag + manual seed; B2C lifestyle on stories; F&B festivals on subculture expansion.
- **No more "1 stuck Perplexity lead"**: every source has measured velocity. Sources that slow down get flagged.
- **Brand-onboarding is parameterized**: when a new brand comes on, the wizard asks 3 questions (your category, your top 3 hashtags, your typical event surface) and configures source weights from those.
- **A test-bed for new sources**: when we want to add a new discovery source (e.g. Reddit, YouTube Shorts, podcast guest lists), we plug it in via the same source attribution + measured funnel pipeline. Within 2 weeks we know if it works for any brand.

## 8. Concrete next steps (next 2 weeks)

### Week 1 (this week)
- [x] Fix posts_seen / hits_seen tracking (done)
- [x] Fix auto_added_via for all paths (done)
- [x] Bulk-promote pending queue (done)
- [x] Schedule Perplexity scout daily (done)
- [x] Build discovery health report (done)
- [ ] Activate IG Stories scraping in production (Apify actor + Instagram session cookie config)
- [ ] Build queue-promotion auto-job for non-hashtag sources

### Week 2
- [ ] Weight hashtag scrape budget by historical hit rate
- [ ] Feed source into AI scoring prompt
- [ ] Add weekly auto-run of discovery_health.py with email summary
- [ ] Onboarding wizard: ask brand for top 3 competitors → seed competitor tracking
- [ ] Add hashtag co-occurrence learning to weekly cron

### Week 3-4
- [ ] First non-STELZ brand fully onboarded via the v2 pipeline
- [ ] Validate the per-source attribution on a clean cohort (new brand from day zero)
- [ ] Iterate based on what we learn

## 9. The strategic narrative for sales

This document also informs how we pitch the product. The key line:

> Most monitoring tools have ONE discovery mode: read the hashtag pool, return creators. We have SIX, and we measure which works best for your specific brand. The system gets sharper the longer you run it.

That's a hard claim for competitors to copy without rebuilding their backend.

Owner: Meinte (strategy direction), Mette + Marleen + Yassin (build), Lukas (sales positioning).
Review cadence: monthly, with the discovery-health report attached.
