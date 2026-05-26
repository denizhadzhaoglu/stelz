-- ============================================================
-- Subcultures: the "scene" layer above creators.
--
-- A brand doesn't just live with individual creators. It lives in
-- communities: students, vrijmibo, festivals, foodies, etc. Lens
-- tracks each of these scenes as a first-class entity so the user
-- can:
--   1. See which scenes the brand is showing up in
--   2. Pause scenes that don't matter (signal hygiene)
--   3. "Expand the oil stain" inside a scene that performs well
--      (find more creators just like the ones already in this scene)
--
-- The user always controls the direction: nothing is auto-expanded.
-- ============================================================

create table if not exists subcultures (
  id          uuid primary key default gen_random_uuid(),
  brand_id    uuid not null references brands(id) on delete cascade,
  slug        text not null,
  name        text not null,
  description text,
  -- Signature signals: hashtags + free-text keywords that mark the scene.
  -- The seed script uses these for hashtag-based classification of existing
  -- creators; the expansion script uses them to direct hashtag-scrapes.
  signature_hashtags  text[] not null default array[]::text[],
  signature_keywords  text[] not null default array[]::text[],
  -- Status drives the dashboard: paused subcultures are hidden from default
  -- views; archived ones are gone but kept for history/reactivation.
  status      text not null default 'active',  -- 'active' | 'paused' | 'archived'
  -- Optional emoji or color for quick visual identification in the UI.
  color       text,
  emoji       text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (brand_id, slug)
);

create index if not exists idx_subcultures_brand_status on subcultures(brand_id, status);

-- Creators can belong to multiple subcultures (a student-life influencer
-- can also be in foodies). The confidence + classified_by columns let us
-- distinguish manual user assignments from AI inferences.
create table if not exists creator_subcultures (
  creator_id     uuid not null references creators(id) on delete cascade,
  subculture_id  uuid not null references subcultures(id) on delete cascade,
  confidence     numeric,
  classified_by  text,                  -- 'manual' | 'hashtag_match' | 'gemini_flash' | 'expansion'
  classified_at  timestamptz not null default now(),
  primary key (creator_id, subculture_id)
);

create index if not exists idx_creator_subcultures_subc on creator_subcultures(subculture_id);

-- Each "olievlek" expansion is an explicit user action. We log it so the
-- dashboard can show the user how each scene has grown, and so we can
-- charge credits against each expansion.
create table if not exists subculture_expansions (
  id              uuid primary key default gen_random_uuid(),
  brand_id        uuid not null references brands(id) on delete cascade,
  subculture_id   uuid not null references subcultures(id) on delete cascade,
  triggered_by    text,                              -- email or system user
  method          text not null,                     -- 'followers_of_seeds' | 'hashtag_scrape' | 'similar_profiles'
  seed_creator_ids uuid[],
  candidates_found int,
  added_to_queue  int,
  cost_credits    int,
  notes           text,
  started_at      timestamptz not null default now(),
  completed_at    timestamptz,
  status          text not null default 'running'    -- 'running' | 'completed' | 'failed'
);

create index if not exists idx_subc_exp_subc on subculture_expansions(subculture_id, started_at desc);

-- Convenience view: per subculture, aggregate metrics.
create or replace view v_subculture_stats as
with creator_counts as (
  select subculture_id, count(*) as creators_count
  from creator_subcultures
  group by subculture_id
),
detection_counts as (
  select
    cs.subculture_id,
    count(d.id) filter (
      where d.detected
      and coalesce(d.is_false_positive, false) = false
    ) as detections_total,
    count(d.id) filter (
      where d.detected
      and coalesce(d.is_false_positive, false) = false
      and d.created_at >= now() - interval '7 days'
    ) as detections_last_7d,
    max(d.created_at) as latest_detection_at
  from creator_subcultures cs
  join content_items ci on ci.creator_id = cs.creator_id
  join content_images img on img.content_item_id = ci.id
  join detections d on d.content_image_id = img.id
  group by cs.subculture_id
),
last_expansion as (
  select distinct on (subculture_id)
    subculture_id, started_at, added_to_queue
  from subculture_expansions
  order by subculture_id, started_at desc
)
select
  s.id, s.brand_id, s.slug, s.name, s.description, s.status, s.color, s.emoji,
  s.signature_hashtags, s.signature_keywords, s.created_at,
  coalesce(cc.creators_count, 0) as creators_count,
  coalesce(dc.detections_total, 0) as detections_total,
  coalesce(dc.detections_last_7d, 0) as detections_last_7d,
  dc.latest_detection_at,
  le.started_at as last_expansion_at,
  le.added_to_queue as last_expansion_added
from subcultures s
left join creator_counts cc on cc.subculture_id = s.id
left join detection_counts dc on dc.subculture_id = s.id
left join last_expansion le on le.subculture_id = s.id;

notify pgrst, 'reload schema';
