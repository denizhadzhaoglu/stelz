-- ============================================================
-- STËLZ Brand Watch -- Database Schema
-- Multi-tenant from day one (brand_id everywhere)
-- Image hash cache for cost optimization
-- Rich detection metadata for UI filtering
-- ============================================================

-- ============================================================
-- BRANDS (tenants)
-- ============================================================
create table if not exists brands (
  id          uuid primary key default gen_random_uuid(),
  slug        text not null unique,                        -- 'stelz', 'alpro', 'action'
  name        text not null,
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists brand_product_lines (
  id              uuid primary key default gen_random_uuid(),
  brand_id        uuid not null references brands(id) on delete cascade,
  slug            text not null,                            -- 'hard_lemonade', 'hard_seltzer', 'hard_iced_tea'
  name            text not null,
  description     text,
  reference_image_url text,
  created_at      timestamptz not null default now(),
  unique (brand_id, slug)
);

create table if not exists brand_hashtag_pools (
  id          uuid primary key default gen_random_uuid(),
  brand_id    uuid not null references brands(id) on delete cascade,
  hashtag     text not null,                                -- without '#'
  group_label text,                                          -- 'student_life', 'house_parties', etc
  platform    text not null default 'instagram',
  priority    int  not null default 5,                       -- 1-10
  active      boolean not null default true,
  created_at  timestamptz not null default now(),
  unique (brand_id, hashtag, platform)
);

create table if not exists brand_prompt_config (
  id                  uuid primary key default gen_random_uuid(),
  brand_id            uuid not null references brands(id) on delete cascade,
  version             int  not null default 1,
  prompt_template     text not null,
  model               text not null default 'gemini-2.5-flash',
  confidence_threshold numeric not null default 0.5,
  active              boolean not null default true,
  created_at          timestamptz not null default now(),
  unique (brand_id, version)
);

-- ============================================================
-- CREATORS (people, accounts, businesses we monitor)
-- ============================================================
create table if not exists creators (
  id              uuid primary key default gen_random_uuid(),
  brand_id        uuid not null references brands(id) on delete cascade,
  platform        text not null,                             -- 'instagram', 'tiktok'
  handle          text not null,
  full_name       text,
  bio             text,
  follower_count  int,
  category        text,                                       -- 'person', 'horeca', 'retail', 'festival', 'student_org', 'media', 'other'
  tier            text,                                       -- 'tier_1', 'tier_2', 'tier_3', 'watch'
  status          text not null default 'discovered',         -- 'discovered', 'promoted', 'rejected', 'archived'
  notes           text,
  first_seen_at   timestamptz not null default now(),
  last_scraped_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (brand_id, platform, handle)
);

create index if not exists idx_creators_brand_status on creators(brand_id, status);
create index if not exists idx_creators_brand_tier on creators(brand_id, tier);
create index if not exists idx_creators_brand_category on creators(brand_id, category);

-- Signals captured per creator during discovery (composite_score, nl_signal, etc)
create table if not exists creator_signals (
  id          uuid primary key default gen_random_uuid(),
  creator_id  uuid not null references creators(id) on delete cascade,
  signal_type text not null,                                 -- 'composite_score', 'person_score', 'nl_signal', 'engagement', 'follower_count'
  value       numeric,
  source      text,                                           -- 'discovery_v2', 'hashtag_scrape', 'person_rerank'
  captured_at timestamptz not null default now()
);

create index if not exists idx_creator_signals_creator on creator_signals(creator_id, signal_type);

-- ============================================================
-- CONTENT ITEMS (posts, reels, stories highlights)
-- ============================================================
create table if not exists content_items (
  id            uuid primary key default gen_random_uuid(),
  brand_id      uuid not null references brands(id) on delete cascade,
  creator_id    uuid not null references creators(id) on delete cascade,
  platform      text not null,                                -- 'instagram', 'tiktok'
  external_id   text not null,                                -- shortCode for IG, video id for TT
  content_type  text not null,                                -- 'post', 'reel', 'highlight', 'story', 'tiktok'
  url           text,
  caption       text,
  hashtags      text[],
  mentions      text[],
  posted_at     timestamptz,
  likes_count   int,
  comments_count int,
  views_count   int,
  raw           jsonb,                                         -- full original API response
  scraped_at    timestamptz not null default now(),
  unique (platform, external_id)
);

create index if not exists idx_content_brand_posted on content_items(brand_id, posted_at desc);
create index if not exists idx_content_creator_posted on content_items(creator_id, posted_at desc);

-- ============================================================
-- IMAGES (media inside content_items)
-- ============================================================
create table if not exists content_images (
  id              uuid primary key default gen_random_uuid(),
  content_item_id uuid not null references content_items(id) on delete cascade,
  brand_id        uuid not null references brands(id) on delete cascade,
  image_url       text not null,                              -- original URL on platform CDN
  image_hash      text,                                        -- sha256 of resized bytes (dedup key)
  sequence_idx    int  not null default 0,                    -- carousel order, frame index for video
  stored_path     text,                                        -- supabase storage path if cached
  created_at      timestamptz not null default now()
);

create index if not exists idx_content_images_content on content_images(content_item_id);
create index if not exists idx_content_images_hash on content_images(image_hash);

-- ============================================================
-- DETECTIONS (Gemini visual brand detection results)
-- ============================================================
create table if not exists detections (
  id                  uuid primary key default gen_random_uuid(),
  brand_id            uuid not null references brands(id) on delete cascade,
  content_image_id    uuid not null references content_images(id) on delete cascade,
  model               text not null,                           -- 'gemini-2.5-flash', 'gemini-2.5-pro', 'yolo-v8'
  prompt_version      int,
  detected            boolean not null,
  product_line        text,                                    -- 'hard_lemonade', 'hard_seltzer', 'hard_iced_tea', 'logo_only', 'none'
  confidence          numeric,                                 -- 0.0 to 1.0
  size_in_frame       text,                                    -- 'small', 'medium', 'large', 'dominant'
  is_primary_subject  boolean,
  context             text,                                    -- Gemini's natural language description
  false_positive_risk text,                                    -- 'low', 'medium', 'high'
  verified            boolean,                                 -- manual review flag
  verified_by         text,
  verified_at         timestamptz,
  is_false_positive   boolean,                                 -- override after manual review
  notes               text,
  created_at          timestamptz not null default now()
);

create index if not exists idx_detections_brand_detected on detections(brand_id) where detected = true;
create index if not exists idx_detections_image on detections(content_image_id);
create index if not exists idx_detections_brand_created on detections(brand_id, created_at desc);

-- ============================================================
-- IMAGE HASH CACHE (cost optimization)
-- Same image hash = reuse detection result, skip Gemini call
-- ============================================================
create table if not exists image_detection_cache (
  image_hash       text not null,
  brand_id         uuid not null references brands(id) on delete cascade,
  model            text not null,
  prompt_version   int,
  detection_result jsonb not null,                              -- full parsed JSON from Gemini
  created_at       timestamptz not null default now(),
  primary key (image_hash, brand_id, model, prompt_version)
);

-- ============================================================
-- DISCOVERY RUNS (audit log)
-- ============================================================
create table if not exists discovery_runs (
  id           uuid primary key default gen_random_uuid(),
  brand_id     uuid not null references brands(id) on delete cascade,
  source_type  text not null,                                  -- 'hashtag_scrape', 'profile_scrape', 'manual_seed'
  source_value text,                                            -- which hashtag, which handle
  platform     text,
  started_at   timestamptz not null default now(),
  completed_at timestamptz,
  results_count int,
  cost_usd     numeric,
  status       text not null default 'running',                -- 'running', 'completed', 'failed'
  error        text
);

-- ============================================================
-- VIEWS (convenience for the dashboard)
-- ============================================================

-- All detections enriched with creator + post metadata
create or replace view v_detections_full as
select
  d.id                as detection_id,
  d.brand_id,
  d.detected,
  d.product_line,
  d.confidence,
  d.size_in_frame,
  d.is_primary_subject,
  d.context,
  d.false_positive_risk,
  d.is_false_positive,
  d.verified,
  d.model,
  d.created_at        as detected_at,
  c.platform,
  c.handle            as creator_handle,
  c.full_name         as creator_name,
  c.category          as creator_category,
  c.tier              as creator_tier,
  ci.external_id      as post_id,
  ci.url              as post_url,
  ci.caption          as post_caption,
  ci.hashtags         as post_hashtags,
  ci.posted_at,
  ci.likes_count,
  ci.comments_count,
  img.image_url,
  img.image_hash
from detections d
join content_images ci_img on ci_img.id = d.content_image_id
join content_items ci on ci.id = ci_img.content_item_id
join creators c on c.id = ci.creator_id
join content_images img on img.id = d.content_image_id;

-- Per creator: aggregate detection stats
create or replace view v_creator_stats as
select
  c.id              as creator_id,
  c.brand_id,
  c.platform,
  c.handle,
  c.full_name,
  c.category,
  c.tier,
  count(distinct ci.id)            as posts_scraped,
  count(d.id) filter (where d.detected and coalesce(d.is_false_positive, false) = false) as total_detections,
  count(d.id) filter (where d.detected
                       and coalesce(d.is_false_positive, false) = false
                       and d.product_line in ('hard_lemonade', 'hard_seltzer', 'hard_iced_tea')
                       and (d.is_primary_subject = true or d.size_in_frame in ('medium','large','dominant'))) as clear_visibility_hits,
  max(ci.posted_at) as latest_post_at,
  max(d.created_at) as latest_detection_at
from creators c
left join content_items ci on ci.creator_id = c.id
left join content_images img on img.content_item_id = ci.id
left join detections d on d.content_image_id = img.id
group by c.id;

-- ============================================================
-- ROW LEVEL SECURITY (for future client access)
-- ============================================================
-- alter table brands enable row level security;
-- alter table creators enable row level security;
-- alter table content_items enable row level security;
-- alter table detections enable row level security;

-- Policies will be added when client access is enabled.
-- For now, service_role bypasses RLS for backend operations.
