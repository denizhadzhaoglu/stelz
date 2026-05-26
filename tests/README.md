# Spot the Brand · QA test harness

One command to know if the system is healthy:

```bash
bash tests/run_all.sh
```

Output (good day):

```
DB invariants            20 passed, 0 failed
Schema drift             22 passed, 0 failed
Edge functions           10 passed, 0 failed
Spot API                 12 passed, 0 failed
Pipeline freshness        7 passed, 0 failed

FINAL: 5 suites passed, 0 failed
```

Bad day: each suite tells you *exactly* which check fails and the actual
value vs the threshold. No grepping logs, no console-spelunking.

## Why this exists

Bugs were being discovered by Meinte clicking around the dashboard. The
test harness exists to catch them before they ship: schema drift, dead
queries, broken Edge Functions, pipeline stalls, billing-data corruption.

If `bash tests/run_all.sh` exits 0, the system is structurally fine. If it
fails, look at the specific check that broke — the failure mode is in the
test name.

## Suites

### 1. `test_db_invariants.py` — structural rules
Every check should return 0 rows. Examples:
- `creators_no_brand` — no creator should have `brand_id IS NULL`
- `images_orphan` — every content_image must join to a content_item
- `detections_brand_mismatch` — detection.brand_id must equal image.brand_id
- `credit_balance_negative` — no brand can have negative credits

Soft thresholds (use `<=` instead of `=`):
- `pending_detection_images_high` — at most 500 pending (Gemini quota safety)

Add a check here whenever you find a new class of data corruption.

### 2. `test_schema_drift.py` — column existence
Scans every `sb.from("X").select("a,b,c")` call in dashboard HTML and
verifies all referenced columns exist in the DB. Catches the
"someone renamed a column in a migration" bug.

Uses the `list_public_columns()` RPC (service-role only).

### 3. `test_edge_functions.py` — Edge Function smoke
Every deployed Edge Function gets a probe:
- Anon-callable: send empty body, expect input-validation 400
- Auth-required: send no token, expect 401
- Webhook: send no signature, expect 400

Catches: function not deployed, env var missing, import-time crash.

### 4. `test_spot_api.py` — Spot API endpoint matrix
All 12 spot-api endpoints exercised against the production deployment via
`vercel curl` (handles the Vercel SSO bypass automatically). Checks both
happy paths and error paths (404 for unknown brand, 401 for missing auth).

### 5. `test_pipeline_freshness.py` — soft data-freshness signals
The system is "alive" only if data keeps flowing:
- `detections_last_1h >= 1`
- `hits_last_24h >= 1`
- `scans_completed_last_24h >= 1`
- `pending_detection_images <= 500`

Plus structural sanity: `creators_active_brand >= 100`, `active_brands >= 1`.

## Requirements

- Python 3.13 (because `tools/stelz_brand_watch/*.py` use the `google.genai`
  SDK which doesn't run on Python 3.9). Run prefix is automatic in `run_all.sh`.
- `.env` with `SUPABASE_URL` + `SUPABASE_SECRET_KEY` (service-role key).
- Vercel CLI authenticated as the team owner (for the spot-api SSO bypass).

## How to add a new check

Most checks are one-liners. Adding to `test_db_invariants.py`:

```python
CHECKS = [
    ...
    ("orphan_subscriptions", 0, "SELECT COUNT(*) FROM subscriptions WHERE NOT EXISTS (SELECT 1 FROM brands b WHERE b.id=subscriptions.brand_id)"),
]
```

That's it. The runner handles formatting + threshold comparison.

For pipeline freshness with a directional threshold:

```python
CHECKS = [
    ...
    ("new_brands_last_30d", 1, ">=",
        "SELECT COUNT(*) FROM brands WHERE created_at > NOW() - INTERVAL '30 days'"),
]
```

## Production health endpoint

Same checks (a curated subset) are exposed as `GET /api/v1/system/health`
on the spot-api. Status is `"ok"`, `"warn"`, or `"fail"`. HTTP 200 for ok
or warn, 503 for fail. Used by:

- Daily QA cron on the Railway worker (`50_system_health_check.py`) —
  writes failures to `public.system_health_alerts`
- Spot CLI (when extended): `spot system health`
- External uptime monitor (UptimeRobot, BetterUptime)

## Files

| File | Purpose |
|---|---|
| `run_all.sh` | One-shot runner. Returns 0 only if everything green. |
| `test_db_invariants.py` | 20 structural rules |
| `test_schema_drift.py` | HTML ↔ DB column reconciliation |
| `test_edge_functions.py` | 10 Edge Function probes |
| `test_spot_api.py` | 12 spot-api endpoints |
| `test_pipeline_freshness.py` | 7 freshness signals |
| `README.md` | This file |

## When something breaks

1. **DB invariant fails** → real data corruption. Find the script that wrote the bad row. Fix the script and the existing rows.
2. **Schema drift fails** → a migration renamed a column without updating the dashboard. Find the migration, update the HTML.
3. **Edge function fails** → check Supabase Edge Function logs for crashes. Often missing env var.
4. **Spot API fails** → check Vercel deployment logs. Usually a code regression.
5. **Pipeline freshness fails** → the scanner stopped. Check Railway worker logs. Common cause: Gemini quota exhausted (see night-report-4 for that story).
