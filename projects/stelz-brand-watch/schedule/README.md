# Daily Scan -- Scheduling

The daily incremental scan refreshes all seed-list creators, detects new STËLZ posts, and stores results in Supabase.

Script: `tools/stelz_brand_watch/18_daily_scan.py`

Three deployment options.

## Option A. Local via macOS launchd (works today, only when your Mac is awake)

1. Copy the plist to LaunchAgents:
   ```
   cp projects/stelz-brand-watch/schedule/com.jackandai.stelz-brand-watch.daily.plist \
      ~/Library/LaunchAgents/
   ```
2. Load it:
   ```
   launchctl load ~/Library/LaunchAgents/com.jackandai.stelz-brand-watch.daily.plist
   ```
3. Verify it's scheduled:
   ```
   launchctl list | grep stelz
   ```
4. Logs land in `.tmp/stelz_brand_watch/daily-scan-stdout.log` and `daily-scan-stderr.log`.

Default schedule: every day at 08:00. Edit `StartCalendarInterval` to change.

To unload:
```
launchctl unload ~/Library/LaunchAgents/com.jackandai.stelz-brand-watch.daily.plist
```

**Limitation**: only runs when your Mac is awake. If sleeping at 08:00 the run is skipped. Fine for development, not production.

## Option B. Railway (production)

1. Create a new Railway project for `stelz-brand-watch`
2. Add a service from this repo (or push as standalone repo)
3. Set environment variables:
   ```
   SUPABASE_URL=https://menaatbeoeutywulcdvv.supabase.co
   SUPABASE_SECRET_KEY=sb_secret_...
   APIFY_API_TOKEN=apify_api_...
   GOOGLE_AI_API_KEY=AIza...   (the real key from dl-orchestrator/.env)
   ```
4. Add cron schedule via Railway dashboard:
   - Schedule: `0 8 * * *` (daily 08:00 UTC)
   - Command: `python tools/stelz_brand_watch/18_daily_scan.py`
5. Verify first run in Railway logs

Cost: ~$5/month. Production-grade reliability.

## Option C. GitHub Actions (also production-grade, free for private repos within 2000 min/mo)

Add `.github/workflows/daily-scan.yml`:

```yaml
name: STELZ Brand Watch -- Daily Scan
on:
  schedule:
    - cron: '0 8 * * *'
  workflow_dispatch:
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.13' }
      - run: pip install -r requirements.txt
      - run: python tools/stelz_brand_watch/18_daily_scan.py
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SECRET_KEY: ${{ secrets.SUPABASE_SECRET_KEY }}
          APIFY_API_TOKEN: ${{ secrets.APIFY_API_TOKEN }}
          GOOGLE_AI_API_KEY: ${{ secrets.GOOGLE_AI_API_KEY }}
```

Add the four secrets in GitHub repo settings -> Secrets.

## Monitoring

Every run writes a row to `discovery_runs` table with:
- `started_at`, `completed_at`
- `status` (running / completed / failed)
- `results_count` (new images detected)
- `error` (if failed)

Dashboard can show a "last scan" indicator pulling from this table.

## Cost estimate per run

- Apify Profile Scraper: ~37 batches @ 25 handles = $5
- Gemini Flash detection: ~100-300 new images = $0.10
- Supabase Storage: $0 (free tier)

**Monthly cost at daily cadence: ~$150 Apify + $3 Gemini = $153/month**

Can be reduced by:
- Scraping only tier 1 creators daily, tier 2 weekly, tier 3 monthly
- Adding `since_timestamp` filter to Apify (skip posts older than last run)
