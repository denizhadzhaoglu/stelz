# Spot Your Brand

AI-driven brand monitoring + cultural intelligence platform. Detects visual brand presence across Instagram and TikTok, ranks creators by Spot Resonance Score (SRS), surfaces emerging fans before they're obvious.

## Stack

**Live stack (Firebase).** Everything the app actually runs on:

- Firestore — brands, creators, posts, detections, resonance
- Cloud Functions (Python 3.11, `firebase/functions/`) — scraping, detection,
  scoring, sentiment; HTTP endpoints for the UI, Pub/Sub workers for the fan-out
- Cloud Storage — cached thumbnails + brand reference images
- React + Vite dashboard (`projects/stelz-brand-watch/web/`)
- Gemini Flash (visual detection, second-look verification, post sentiment),
  Apify (Instagram/TikTok scraping), yt-dlp + ffmpeg (video frames)

**Legacy stack (Supabase + Vercel + Railway).** The Postgres database was
removed in 2026-06 and the frontend reads Firestore only. `tools/stelz_brand_watch/`
(scripts 01-57) still targets Supabase and will not run against the live data —
treat it as history, not as a runnable pipeline. Anything from there that is
still wanted has to be ported to `firebase/functions/handlers/`.

## Repo layout

```
firebase/
  functions/            # LIVE pipeline: handlers/ (scrape, detect, score, sentiment), lib/
  firestore.rules       # read: any signed-in user · write: brand members only
projects/
  spot-the-brand/       # Product: pitch deck, API, brandbook, sales playbook, IG launch
  stelz-brand-watch/    # First brand on the platform — web dashboard, TESTING.md, status docs
tools/
  stelz_brand_watch/    # LEGACY Supabase pipeline (01-57) — see the note above
  create_*.py           # Pitch deck generators, asset renderers
tests/                  # Schema invariants, edge-function health, pipeline freshness (legacy)
```

## Access model

Reads are open to any signed-in account; every write is gated on brand
membership (`/brands/{id}/members/{uid}`), enforced in both
`main.py._require_brand_member` and `firestore.rules`. A person who isn't a
member sees the whole dashboard in read-only mode — that is how testers are
given access. Membership is granted by `bootstrap_brand` only to the first
caller of an unclaimed brand; after that it is a manual decision.

## Resonance Algorithm (SRS)

Composite 0-100 score per candidate. **Six** weighted layers in the live
pipeline — weights shown for `hot` mode:

- **Graph (30%)** — in-degree over mention + tag + comment edges
- **Hashtag (20%)** — cosine of the candidate's tag distribution vs the brand's
  yield vector, with brand-specific tags EXCLUDED (v2): tagging the brand is
  the opposite of the signal this tool sells
- **Comment (15%)** — engagement on tier-1 hit posts
- **Geo/Language (10%)** — NL bio + caption signal
- **Visual (10%)** — embedding cosine vs the brand visual centroid
- **Subculture (15%)** — how brand-dense the hand-curated scenes a creator
  belongs to are (`lib/subcultures.py`, `handlers/seed_subcultures.py`)

The subculture layer spent a long period disabled: its seed data lived in the
Supabase database removed in 2026-06, so `compute_resonance` redistributed the
15% and `ResonanceRow.subculture` was null on every row. The seeding step now
runs on Firestore, and the layer is live **for brands that have run it** —
`api_step_subcultures`, chained before `api_step_srs`. Brands that haven't get
the weight redistributed exactly as before, and `subcultureLayerLive` on each
resonance doc says which happened.

Bootstrap-aware (cold/warm/hot) so it works for new brands from day one without
anchor data — the weights above change per mode, so scores are comparable
between creators of one brand but not across brands at different stages.

Implementation: `firebase/functions/handlers/compute_resonance.py`. Presentation
and per-layer copy: `projects/stelz-brand-watch/web/src/lib/srs.ts` (keep the
weights in the two files in sync). `projects/stelz-brand-watch/SRS_IMPLEMENTATION_STATUS.md`
and `tools/stelz_brand_watch/{51..57}_*.py` describe the older Supabase version.

## Secrets

All credentials live in `.env` (gitignored). Never commit:

- `SUPABASE_SECRET_KEY`
- `APIFY_API_TOKEN`
- `IG_SESSION_ID`
- `GOOGLE_AI_API_KEY` / `GEMINI_API_KEY`
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
