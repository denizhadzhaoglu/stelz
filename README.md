# Spot Your Brand

AI-driven brand monitoring + cultural intelligence platform. Detects visual brand presence across Instagram and TikTok, ranks creators by Spot Resonance Score (SRS), surfaces emerging fans before they're obvious.

Stack: Supabase (Postgres + Edge Functions + Storage), Vercel (API + dashboard + pitch deck), Railway (Python workers), Gemini Vision (detection), instagrapi + direct IG/TikTok scraping, yt-dlp + ffmpeg (video frame extraction).

## Repo layout

```
projects/
  spot-the-brand/       # Product: pitch deck, API, brandbook, sales playbook, IG launch
  stelz-brand-watch/    # First brand on the platform — dashboard, db migrations, railway workers
tools/
  stelz_brand_watch/    # Python pipeline: scrape, detect, score, mine, expand (01-57)
  create_*.py           # Pitch deck generators, asset renderers
tests/                  # Schema invariants, edge-function health, pipeline freshness
```

## Resonance Algorithm (SRS)

Composite 0-100 score per candidate, six weighted layers:

- **Graph (30%)** — PageRank on mention + comment + subculture edges
- **Hashtag (20%)** — cosine of candidate's tag distribution vs brand-learned yield vector
- **Subculture (15%)** — lift from belonging to high-tier-density subcultures
- **Comment (15%)** — engagement on tier-1 hit-posts
- **Geo/Language (10%)** — NL bio + caption signal
- **Visual (10%)** — embedding cosine vs brand visual centroid (gated to SRS-pre ≥ 50)

Bootstrap-aware (cold/warm/hot mode) so it works for new brands from day one without anchor data.

See `projects/stelz-brand-watch/SRS_IMPLEMENTATION_STATUS.md` for status, `tools/stelz_brand_watch/{51..57}_*.py` for the implementation.

## Secrets

All credentials live in `.env` (gitignored). Never commit:

- `SUPABASE_SECRET_KEY`
- `APIFY_API_TOKEN`
- `IG_SESSION_ID`
- `GOOGLE_AI_API_KEY` / `GEMINI_API_KEY`
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
