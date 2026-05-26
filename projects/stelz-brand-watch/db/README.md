# STËLZ Brand Watch -- Database

## Setup

1. Create new Supabase project at https://supabase.com/dashboard
   - Project name: `jackandai-brand-watch`
   - Region: `eu-central-1` (Frankfurt) for NL latency
   - Pricing: Pro tier (25 USD/month) -- needed for daily backups and bigger storage
2. From the project dashboard, get:
   - `SUPABASE_URL` (Settings -> API -> Project URL)
   - `SUPABASE_SERVICE_KEY` (Settings -> API -> service_role secret -- backend only, never in frontend)
   - `SUPABASE_ANON_KEY` (Settings -> API -> anon public -- safe for frontend)
3. Add to `/Users/meintestinstra/Documents/Jackandai/PA/.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_SERVICE_KEY=eyJh...
   SUPABASE_ANON_KEY=eyJh...
   ```
4. Run migrations in order:
   - `01_schema.sql` (tables, indexes, views)
   - `02_seed_stelz.sql` (STELZ as first tenant with hashtag pools and product lines)

Migrations can be run from Supabase SQL Editor or via the migration script (see `tools/stelz_brand_watch/09_migrate_to_supabase.py`).

## Schema highlights

- **Multi-tenant**: every entity has `brand_id`. Adding a new brand = 4 INSERTs (brand + product lines + hashtags + prompt) and the entire pipeline works for them.
- **Image hash cache**: `image_detection_cache` table dedupes by SHA256 hash. Reposts and viral content scan once, used many times.
- **Rich detection metadata**: `detections` table stores `confidence`, `product_line`, `size_in_frame`, `is_primary_subject`, `context`, `false_positive_risk`. UI filters on these.
- **Audit trail**: `discovery_runs` logs every scrape with cost and result count.
- **Views**: `v_detections_full` (enriched detections) and `v_creator_stats` (per-creator aggregates) for the dashboard.

## Storage bucket setup

Create one private bucket:
- Name: `brand-watch-thumbnails`
- Public: no (signed URLs from backend)
- File size limit: 5 MB

Used to cache resized image thumbnails so the dashboard doesn't hammer Instagram CDN.

## Row Level Security

RLS is OFF by default in the schema. Backend uses service_role key which bypasses RLS. When client access is enabled (fase 4), policies will be added so each client only sees their own brand's data.
