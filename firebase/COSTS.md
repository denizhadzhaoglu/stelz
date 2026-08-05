# Cost envelope

Working assumption: Stelz scale (1 brand, ~1000 tracked creators, ~800
posts/day scanned, ~150 detections/day).

## Per-scan read/write budget

| Function | Reads | Writes | Pub/Sub msgs | Gemini calls | Apify calls |
|---|---|---|---|---|---|
| `daily_scan_hashtags` | ~1K (existing handles + queue) | ~50 (new candidates + promotions) | 0 | 0 | 5-10 (one per hashtag) |
| `daily_scan_creators` | ~150 (due creators) + dedup checks | ~200 (only new/changed posts + images) | ~150 (new images only) | 0 | ~5 (batched profiles) |
| `on_detect_image` (×N msgs) | 2 per msg (brand + post + cache check) | 1 per msg | 0 | ~80%* of N (rest = cache hits) | 0 |
| `daily_score_creators` | ~200 (server-side filter) + 200 captions (batched) | ~150 (scored creators) | 0 | ~150 | 0 |
| `daily_compute_srs` | ~12K (edges + detections + candidate metas) | ~500 (resonance docs, batched) | 0 | 0 | 0 |

*Cache hit rate climbs to ~30-40% within a week of operation (image hash cache
stores indefinitely).

**Daily total per brand:**
- Reads: ~14K
- Writes: ~900
- Gemini Flash: ~250 calls (~$0.02)
- Apify: ~15 actor runs (~$0.50)

**Firestore free tier (per project):**
- 50K reads/day → we use 14K, **headroom 3.5×**
- 20K writes/day → we use 0.9K, **headroom 22×**
- 1 GB stored → ~5 KB per detection × 700 + ~1 KB per creator × 1000 = ~4 MB. Plenty.

**Cloud Functions free tier:**
- 2M invocations/month → ~25K/month, **headroom 80×**

## What we did to cut costs vs first draft

1. **detect_image** — was: 1 detection doc per image always. Now: skip writes
   for `detected=false AND confidence<0.3` (pure noise). Estimated **~40% fewer
   detection writes** based on Stelz Flash confidence distribution.

2. **detect_image** — denormalized `creatorHandle, platform, postedAt,
   postHashtags, likesCount, postCaption` onto the detection doc. This kills
   compute_resonance's per-detection post lookup (was 700+ N+1 reads/run).

3. **scan_creators** — early exit when post already exists with same
   likesCount AND `hasDetection` is set. Saves the post write + N image writes
   + N Pub/Sub messages + N Cloud Function invocations per duplicate.

4. **score_creator** — was: `creators.limit(400).stream()` then filter in
   Python. Now: server-side `where("lastScoredAt", "<", cutoff)` with proper
   index. ~10× fewer reads on a 1K-creator collection.

5. **score_creator** — was: 1 caption query PER creator (N+1, 200 round trips).
   Now: batched `where("creatorHandle", "in", [chunk-of-30])` queries → 7
   round trips for 200 creators.

6. **compute_resonance** — was: stream all creators (~1K reads), all edges
   (~10K), all detections (~700), then per-detection post fetch (~700 N+1),
   then per-candidate 50-posts fetch (~50K N+1). Total ~60K reads/run.
   Now: streams edges + detections once (hashtags already denormalized), only
   fetches metadata for *candidates with edges or hits*, batched `in` queries.
   Total ~12K reads/run. **5× cheaper.**

7. **compute_resonance** — candidate set narrowed: don't score creators that
   have no edges AND no hits. Was scoring all 1K creators including dead ones.

8. **Detection cache** — `imageHashCache` keyed by sha256, model, prompt
   version. Reposts/duplicates skip Gemini entirely. Adds 1 Firestore read
   per detection to save a $0.000075 Gemini call — break-even at any rate
   since Firestore reads are ~$0.00003 each.

9. **Composite indexes** added for new queries: `(status, lastScoredAt)`,
   `(creatorHandle, postedAt)` on posts subcollection. Avoids in-memory sorts.

## What we still pay for (and why it's fine)

- **Apify** — ~$0.50/day. Largest single cost. yt-dlp swap could save ~$15/mo
  but risks Instagram throttle. Defer.
- **Gemini Flash** — ~$0.02/day. Trivial.
- **Pub/Sub / Cloud Functions** — free tier covers us.
- **Firestore reads** — well under free tier.

## When to revisit

- If we add 5+ active brands → revisit batch sizes (chunked writes, parallel
  Apify batches).
- If detection collection grows past 100K docs → add TTL on imageHashCache
  entries older than 90 days (Firestore has TTL fields).
- If we add video frame detection (script 57) → that's 10× Gemini calls per
  reel. Plan for ~$5-10/month additional.

## Open optimization tickets

1. Materialized brand `hashtagYield` doc — currently recomputed every SRS run.
   Should incrementally update on each detection. (Saves ~5K reads/run.)
2. Image storage to Cloud Storage — currently we re-fetch image bytes for hash
   each time. Caching the hash on the post.image doc would skip the bytes
   download for re-scans. (Saves a few KB per image.)
3. `daily_compute_srs` could be split: Pub/Sub triggered on each new detection,
   incrementally updating just the affected creator's SRS, rather than full
   nightly recompute.
