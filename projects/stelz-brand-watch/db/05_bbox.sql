-- ============================================================
-- Bounding boxes per detection.
--
-- Gemini Pro can return where in the image it sees the brand
-- so we can show the user a box on the thumbnail. This is the
-- core "vision-first" UX upgrade: "we don't just say we see it,
-- we point to it".
--
-- Format stored: array of objects, each:
--   { "y1": 0-1000, "x1": 0-1000, "y2": 0-1000, "x2": 0-1000, "label": "stelz can" }
-- Coordinates are Gemini's normalized 0-1000 box space.
-- ============================================================

alter table detections add column if not exists bbox jsonb;

create or replace view v_detections_full as
with latest as (
  select distinct on (content_image_id)
    id, brand_id, content_image_id, model, prompt_version,
    detected, product_line, confidence, size_in_frame,
    is_primary_subject, context, false_positive_risk,
    is_false_positive, verified, bbox, created_at
  from detections
  order by content_image_id, prompt_version desc, created_at desc
)
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
  d.prompt_version,
  d.bbox,
  d.created_at        as detected_at,
  c.platform,
  c.handle            as creator_handle,
  c.full_name         as creator_name,
  c.category          as creator_category,
  c.tier              as creator_tier,
  c.follower_count,
  ci.external_id      as post_id,
  ci.url              as post_url,
  ci.caption          as post_caption,
  ci.hashtags         as post_hashtags,
  ci.posted_at,
  ci.likes_count,
  ci.comments_count,
  img.image_url,
  img.image_hash,
  img.stored_path
from latest d
join content_images img on img.id = d.content_image_id
join content_items ci on ci.id = img.content_item_id
join creators c on c.id = ci.creator_id;

-- Track which reference-pack fingerprint each brand was last verified against.
-- When the pack changes (new product variant added, lifestyle photo swapped),
-- 28_reverify_on_ref_update.py triggers a Pro re-verify pass.
create table if not exists reference_pack_versions (
  id           uuid primary key default gen_random_uuid(),
  brand_id     uuid not null references brands(id) on delete cascade,
  fingerprint  text not null,
  verified_at  timestamptz not null default now(),
  unique (brand_id, fingerprint)
);

-- Tell PostgREST to pick up the new column.
notify pgrst, 'reload schema';
