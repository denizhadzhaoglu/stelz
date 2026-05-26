-- ============================================================
-- STELZ Resonance Algorithm (SRS) — data model
--
-- Replaces a loose pipeline of 11 discovery scripts with a single
-- composite score per creator per brand. Six layers:
--
--   SRS = 0.30·Graph + 0.20·Hashtag + 0.15·Subculture
--       + 0.15·Comment + 0.10·GeoLang + 0.10·Visual
--
-- All weights shift in bootstrap mode (cold/warm/hot) so the same
-- algorithm works for a brand-new client with 0 hits or for STELZ
-- with thousands.
--
-- Three additions:
--   1. creator_edges   — typed directed graph
--   2. resonance_scores — materialized nightly, fast to read
--   3. v_brand_hashtag_yield — per-brand hashtag yield vector
--      (+ v_resonance_ranked convenience view for the dashboard)
-- ============================================================

-- ─── creator_edges ─────────────────────────────────────────
-- Typed directed graph of creator-to-creator connections.
-- Edge types:
--   'mention'    — src's posts @-mention dst
--   'comment'    — src's posts received a comment from dst
--   'tag'        — src tagged dst in a post (Instagram tagged_users)
--   'subculture' — both in the same subculture (light edge)
-- ============================================================

create table if not exists creator_edges (
  brand_id      uuid not null references brands(id) on delete cascade,
  src_creator_id uuid not null references creators(id) on delete cascade,
  dst_handle    text not null,
  dst_platform  text not null,
  edge_type     text not null check (edge_type in ('mention','comment','tag','subculture')),
  weight        numeric not null default 1,
  last_seen_at  timestamptz not null default now(),
  primary key (brand_id, src_creator_id, dst_handle, dst_platform, edge_type)
);

-- Reverse lookup: who points at handle X? (Used by GraphScore.)
create index if not exists idx_creator_edges_dst
  on creator_edges (brand_id, dst_handle, dst_platform);

-- TTL helper: prune edges that haven't been refreshed in 30 days
create index if not exists idx_creator_edges_last_seen
  on creator_edges (brand_id, last_seen_at);

comment on table creator_edges is
  'Typed directed graph used by SRS GraphScore. Edges decay by last_seen_at; refresh nightly via 51_build_edges.py.';

-- ─── resonance_scores ──────────────────────────────────────
-- Per (brand, creator) score, recomputed nightly. Stores both
-- the composite SRS and the per-layer breakdown so the dashboard
-- can show which signals drove the rank.
-- ============================================================

create table if not exists resonance_scores (
  brand_id        uuid not null references brands(id) on delete cascade,
  creator_handle  text not null,
  platform        text not null,
  srs             numeric not null check (srs >= 0 and srs <= 100),
  graph           numeric,
  hashtag         numeric,
  subculture      numeric,
  comment         numeric,
  geo             numeric,
  visual          numeric,
  bootstrap_mode  text check (bootstrap_mode in ('cold','warm','hot')),
  computed_at     timestamptz not null default now(),
  primary key (brand_id, platform, creator_handle)
);

-- Hot-path index: dashboard sorts "top 100 by SRS for brand X".
create index if not exists idx_resonance_scores_brand_srs
  on resonance_scores (brand_id, srs desc);

comment on table resonance_scores is
  'Nightly-materialized SRS per (brand, platform, handle). Read-only for dashboard. Recomputed by 53_compute_resonance.py.';

-- ─── v_brand_hashtag_yield ─────────────────────────────────
-- Per-brand hashtag yield vector. For each hashtag, what fraction
-- of posts using it produced a confirmed STELZ visual hit?
--
-- Used by HashtagFingerprint layer: cosine-similarity between a
-- candidate's last-90-day hashtag distribution and this brand vector.
--
-- Filtered: only hashtags with ≥5 posts in window, to avoid noise.
-- ============================================================

create or replace view v_brand_hashtag_yield as
  with hashtag_post_counts as (
    select ci.brand_id,
           lower(ht) as hashtag,
           ci.id as content_item_id
    from content_items ci
    cross join lateral unnest(coalesce(ci.hashtags, array[]::text[])) as ht
    where ci.posted_at >= now() - interval '180 days'
  ),
  hashtag_hits as (
    select hpc.brand_id, hpc.hashtag, hpc.content_item_id,
           bool_or(d.detected and d.confidence >= 0.5
                   and d.is_false_positive is not true) as had_hit
    from hashtag_post_counts hpc
    left join content_images i on i.content_item_id = hpc.content_item_id
    left join detections d on d.content_image_id = i.id
    group by hpc.brand_id, hpc.hashtag, hpc.content_item_id
  )
  select brand_id,
         hashtag,
         sum(case when had_hit then 1 else 0 end)::numeric
           / nullif(count(*), 0) as yield,
         count(*) as total_count,
         sum(case when had_hit then 1 else 0 end) as hit_count
  from hashtag_hits
  group by brand_id, hashtag
  having count(*) >= 5;

comment on view v_brand_hashtag_yield is
  'Per-brand hashtag yield over last 180 days. yield = hit_rate. Used by SRS HashtagFingerprint layer (cosine-sim against candidate hashtag distribution).';

-- ─── v_resonance_ranked ────────────────────────────────────
-- Dashboard convenience view: joins resonance_scores back to
-- creators + v_creator_stats so the UI can show name, follower
-- count, tier, hit counts alongside the SRS.
-- ============================================================

create or replace view v_resonance_ranked as
  select rs.brand_id,
         rs.creator_handle,
         rs.platform,
         rs.srs,
         rs.graph, rs.hashtag, rs.subculture,
         rs.comment, rs.geo, rs.visual,
         rs.bootstrap_mode,
         rs.computed_at,
         c.id as creator_id,
         c.full_name,
         c.follower_count,
         c.tier,
         c.status,
         c.category,
         c.relevance_score,
         cs.clear_visibility_hits,
         cs.latest_detection_at,
         cs.posts_scraped
  from resonance_scores rs
  join creators c
    on c.brand_id = rs.brand_id
   and c.handle = rs.creator_handle
   and c.platform = rs.platform
  left join v_creator_stats cs
    on cs.creator_id = c.id
  order by rs.srs desc;

comment on view v_resonance_ranked is
  'Dashboard read-model: SRS + per-layer breakdown + creator metadata + hit stats. Order by SRS desc.';

-- ─── pruning helper ─────────────────────────────────────────
-- Edges that haven't been re-seen in 30 days are stale. The
-- nightly 51_build_edges.py refreshes last_seen_at on touch;
-- whatever is older gets dropped here.
-- ============================================================

create or replace function prune_stale_edges(p_age_days int default 30)
returns int language plpgsql as $$
declare
  v_count int;
begin
  delete from creator_edges
  where last_seen_at < now() - make_interval(days => p_age_days);
  get diagnostics v_count = row_count;
  return v_count;
end $$;

comment on function prune_stale_edges is
  'Drop creator_edges with last_seen_at older than N days (default 30). Run after 51_build_edges.py.';
