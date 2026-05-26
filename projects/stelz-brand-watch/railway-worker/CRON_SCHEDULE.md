# Railway cron schedule — STELZ Brand Watch

After SRS rollout, the nightly pipeline order matters:
edges must exist before scoring, scoring must happen before Gemini gate.

## Schedule (Europe/Amsterdam)

```
02:00  python3 tools/stelz_brand_watch/18_daily_scan.py
       # IG profile scrape for all due creators (existing)

02:30  python3 tools/stelz_brand_watch/44_stories_harvest.py
       # IG stories via direct IG API + cookie (existing)

03:00  python3 tools/stelz_brand_watch/51_build_edges.py --prune
       # Refresh creator_edges (mention + subculture from existing data) + prune >30d stale
       # New, fast (<10s), no API cost

03:15  python3 tools/stelz_brand_watch/47_hashtag_learning.py --auto-add
       # Refresh v_brand_hashtag_yield + suggest new hashtags to track (existing)

03:30  python3 tools/stelz_brand_watch/53_compute_resonance.py
       # Compute SRS for every brand. Writes resonance_scores. <2 min.
       # New, no API cost (pure SQL/pandas)

03:35  python3 tools/stelz_brand_watch/19_auto_add.py
       # Promote discovery_queue items with signal_count >= 2 (incl. SRS-promoted) to creators

03:45  python3 tools/stelz_brand_watch/21_ai_score_creators.py --srs-gate 60
       # Gemini-score only creators with SRS >= 60. Cuts ~80% of API calls.
       # Modified: --srs-gate flag added

04:00  python3 tools/stelz_brand_watch/55_score_visual.py --srs-gate 50
       # Gemini multimodal embedding cosine match. Only candidates with SRS_pre >= 50.
       # Future (Fase 3.5), heavy quota — gate aggressively

04:30  python3 tools/stelz_brand_watch/33_detect_pending.py
       # Vision detection on any newly-scraped images (existing)

07:00  python3 tools/stelz_brand_watch/34_daily_email_report.py
       # Now also surfaces top 20 SRS>=75 candidates (modify)
```

## Weekly

```
SUN 04:30  python3 tools/stelz_brand_watch/52_mine_comments.py --top-posts 50
           # Apify comment scrape on tier_1/2 hit-posts. Fills comment-edge layer.
           # ~€5/week for STELZ

SUN 05:00  python3 tools/stelz_brand_watch/41_creator_graph_expand.py
           # Legacy @-mention expansion — still useful for back-compat
```

## Monthly

```
MON-of-month 05:00  python3 tools/stelz_brand_watch/54_visual_centroid.py
                    # Refresh brand's visual centroid from tier_1 9-post grids
                    # Future (Fase 3.5)
```

## Dependency notes

- `53_compute_resonance` requires `creator_edges` to be fresh → must run AFTER `51_build_edges`
- `21_ai_score_creators --srs-gate 60` requires `resonance_scores` populated → must run AFTER `53`
- `19_auto_add` should run AFTER `47_hashtag_learning` (which may produce new discovery_queue rows) but BEFORE `21_ai_score_creators` (which only Gemini-scores already-promoted creators).

## Cost expectations per night (STELZ scale, 4k tracked creators)

| Step | Compute | API |
|---|---|---|
| 51_build_edges | <10s | €0 |
| 47_hashtag_learning | ~30s | €0 |
| 53_compute_resonance | <2 min | €0 |
| 21_ai_score (SRS≥60) | varies | ~€0.50/night (~40 candidates) |
| 33_detect_pending | varies | ~€1-2/night (Gemini vision) |
| 18_daily_scan | ~3 min | ~€1-2/night (Apify) |
| 44_stories_harvest | ~2 min | €0 (direct IG cookie) |

Total nightly: ~€3-5/brand. Weekly comment mining adds ~€5.

## Multi-brand

Every script already loops `brands` table internally. No config change needed when adding a brand — just `INSERT INTO brands ...` and the next cron picks it up.

Bootstrap mode (cold/warm/hot) auto-switches per brand based on `clear_visibility_hits` from `v_creator_stats`. Cold-brand weights emphasize hashtag + geo so a new client surfaces creators within the first 48h without needing a network.
