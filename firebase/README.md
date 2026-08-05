# Firebase backend

Cloud Functions (Python 3.11) + Firestore + Cloud Storage for Spot the Brand.

## Architecture

```
Cloud Scheduler ──┐
                  ├─→ daily_scan_hashtags      ──→ Firestore: discoveryQueue, creators
                  ├─→ daily_scan_creators      ──→ Firestore: posts, images
                  │                                ──→ Pub/Sub: detect-image (fan-out)
                  ├─→ daily_score_creators     ──→ Firestore: creators.relevanceScore
                  └─→ daily_compute_srs        ──→ Firestore: resonance

Pub/Sub ──→ on_detect_image ──→ Gemini Flash ──→ Firestore: detections
                                              ──→ Firestore: imageHashCache

HTTP ──→ api_run_scan_now    (UI "Run scan" button)
     └─→ api_rate_detection  (Moderator approve/reject)
```

## Firestore schema

```
/brands/{brandId}
  /members/{uid}                — auth: only members can read
  /creators/{platform_handle}   — handle, platform, tier, status, srs, nextScanAt
  /posts/{platform_extId}
    /images/{idx}               — url, sequenceIdx
  /detections/{postId_imgHash}  — detected, confidence, productLine, verified, ...
  /resonance/{platform_handle}  — srs + 6 layers + bootstrapMode + computedAt
  /edges/{srcId_dstHandle}      — graph edges (mention/tag/comment/subculture)
  /discoveryQueue/{platform_handle}
  /hashtagPool/{platform_tag}
  /referenceImages/{imageId}
  /imageHashCache/{hash}        — avoid re-running Gemini on dup images
  /scanRuns/{runId}             — audit log

/users/{uid}
  /shortlists/{detectionId}
```

## First-time deploy

```bash
cd firebase

# 1. Authenticate
firebase login
firebase use brand-audit-4b2cc

# 2. Set secrets (Gemini + Apify tokens)
firebase functions:secrets:set GOOGLE_AI_API_KEY
firebase functions:secrets:set APIFY_API_TOKEN

# 3. Deploy Firestore rules + indexes
firebase deploy --only firestore

# 4. Deploy functions
cd functions
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd ..
firebase deploy --only functions

# 5. Seed the Stelz brand
GOOGLE_APPLICATION_CREDENTIALS=path/to/sa.json python seed_brand.py --uid <your-firebase-uid>

# 6. Trigger first scan manually
curl -X POST https://europe-west1-brand-audit-4b2cc.cloudfunctions.net/api_run_scan_now \
  -H "Authorization: Bearer <id-token>" \
  -H "Content-Type: application/json" \
  -d '{"brandId":"stelz"}'
```

## Schedules

Cloud Scheduler is auto-created from the `@scheduler_fn.on_schedule` decorators
in `main.py`. To verify:

```bash
gcloud scheduler jobs list --location=europe-west1
```

| Function | Cron (UTC) | What it does |
|---|---|---|
| `daily_scan_hashtags` | 06:00 | Hashtag scrape → discoveryQueue |
| `daily_scan_creators` | 07:00 | Profile scrape → posts → fan out detection |
| `daily_score_creators` | 10:00 | Gemini relevance score |
| `daily_compute_srs` | 11:00 | 6-layer SRS recompute |

## Local dev / emulator

```bash
firebase emulators:start --only functions,firestore,pubsub
```

## Cost model

Free tier covers the Stelz workload (1 brand, ~100 creators/day):
- Firestore: 1 GB free, 50K reads/day, 20K writes/day → enough
- Functions: 2M invocations/month free → enough
- Pub/Sub: 10 GB egress/month free → enough
- Gemini Flash + Apify: same as current (~$3/month)

Scale planning at 100+ brands: ~$50/month all-in.
