-- ============================================================
-- Caption signal + needs_review classification
--
-- Two new computed columns on v_detections_full:
--   stelz_in_caption: true if 'stelz' appears in caption OR hashtags
--   needs_review:     true if low-trust hit (visual-only, no primary subject)
--
-- Default dashboard hides needs_review=true behind a tab.
-- ============================================================

create or replace view v_detections_full as
with latest as (
  select distinct on (content_image_id)
    id, brand_id, content_image_id, model, prompt_version,
    detected, product_line, confidence, size_in_frame,
    is_primary_subject, context, false_positive_risk,
    is_false_positive, verified, created_at
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
  img.stored_path,
  -- Caption signal: STELZ explicitly named in caption or hashtags
  (
    coalesce(lower(ci.caption) ~ '\mstelz\M', false)
    or exists (
      select 1 from unnest(coalesce(ci.hashtags, array[]::text[])) h
      where lower(h) ~ '\mstelz\M'
    )
  ) as stelz_in_caption,
  -- Trust score: caption mention is the strongest signal
  case
    -- Trusted: caption mentions STELZ
    when coalesce(lower(ci.caption) ~ '\mstelz\M', false) then 'trusted'
    when exists (
      select 1 from unnest(coalesce(ci.hashtags, array[]::text[])) h
      where lower(h) ~ '\mstelz\M'
    ) then 'trusted'
    -- Trusted: primary subject in frame
    when d.is_primary_subject = true and d.size_in_frame in ('medium','large','dominant') then 'trusted'
    -- Trusted: clear product line (not logo_only) with decent size
    when d.product_line in ('hard_lemonade','hard_seltzer','hard_iced_tea','mixed_classics')
         and d.size_in_frame in ('medium','large','dominant') then 'trusted'
    -- Otherwise: needs review
    else 'review'
  end as trust_level,
  -- Needs review boolean: hidden by default in dashboard
  not (
    coalesce(lower(ci.caption) ~ '\mstelz\M', false)
    or exists (
      select 1 from unnest(coalesce(ci.hashtags, array[]::text[])) h
      where lower(h) ~ '\mstelz\M'
    )
    or (d.is_primary_subject = true and d.size_in_frame in ('medium','large','dominant'))
    or (d.product_line in ('hard_lemonade','hard_seltzer','hard_iced_tea','mixed_classics')
        and d.size_in_frame in ('medium','large','dominant'))
  ) as needs_review
from latest d
join content_images img on img.id = d.content_image_id
join content_items ci on ci.id = img.content_item_id
join creators c on c.id = ci.creator_id;

-- Aggregate stats now exclude needs_review unless we explicitly include them
create or replace view v_creator_stats as
with latest as (
  select distinct on (content_image_id)
    content_image_id, detected, product_line, confidence,
    size_in_frame, is_primary_subject, is_false_positive, prompt_version
  from detections
  order by content_image_id, prompt_version desc, created_at desc
)
select
  c.id              as creator_id,
  c.brand_id,
  c.platform,
  c.handle,
  c.full_name,
  c.category,
  c.tier,
  c.follower_count,
  count(distinct ci.id) as posts_scraped,
  count(d.content_image_id) filter (
    where d.detected
    and coalesce(d.is_false_positive, false) = false
    and (
      coalesce(lower(ci.caption) ~ '\mstelz\M', false)
      or exists (
        select 1 from unnest(coalesce(ci.hashtags, array[]::text[])) h
        where lower(h) ~ '\mstelz\M'
      )
      or (d.is_primary_subject = true and d.size_in_frame in ('medium','large','dominant'))
      or (d.product_line in ('hard_lemonade','hard_seltzer','hard_iced_tea','mixed_classics')
          and d.size_in_frame in ('medium','large','dominant'))
    )
  ) as total_detections,
  count(d.content_image_id) filter (
    where d.detected
    and coalesce(d.is_false_positive, false) = false
    and d.product_line in ('hard_lemonade', 'hard_seltzer', 'hard_iced_tea')
    and (d.is_primary_subject = true or d.size_in_frame in ('medium','large','dominant'))
  ) as clear_visibility_hits,
  max(ci.posted_at) as latest_post_at
from creators c
left join content_items ci on ci.creator_id = c.id
left join content_images img on img.content_item_id = ci.id
left join latest d on d.content_image_id = img.id
group by c.id;

-- Notify PostgREST to reload schema cache
notify pgrst, 'reload schema';
