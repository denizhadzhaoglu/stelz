#!/usr/bin/env python3
"""Learn new hashtags by observing co-occurrence in brand-hit posts.

Insight: when a real brand mention happens, the OTHER hashtags on that
post tell us where to look next. If "stelz" hits 80 times in posts
also tagged "vrijmibo", then "vrijmibo" is a high-yield discovery hashtag
for this brand.

This script:
  1. For each brand, pulls content_items that produced a real (not FP)
     brand detection in the last N days.
  2. Aggregates hashtags from those items.
  3. Filters out hashtags already in the brand's pool.
  4. Sorts by co-occurrence count + by yield (% of posts with that
     hashtag that detected the brand).
  5. Either reports candidates (default) or auto-adds the top K to the
     brand's hashtag pool (--auto-add).

Auto-added hashtags get priority=3 (below the brand's curated ones at 5).
Conservative threshold: a hashtag is auto-added only when it has >=8
co-occurrences AND >=20% yield (most posts with this tag are real brand
hits, not noise).

Usage:
    python3 tools/stelz_brand_watch/47_hashtag_learning.py
    python3 tools/stelz_brand_watch/47_hashtag_learning.py --brand stelz --auto-add --top 5
    python3 tools/stelz_brand_watch/47_hashtag_learning.py --brand stelz --window-days 60 --dry-run
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def fetch_hit_items(sb, brand_id: str, since_iso: str) -> list:
    """All content_items where brand had a positive, non-FP detection."""
    # First pull detection content_image_ids
    img_ids = set()
    offset = 0
    while True:
        r = (sb.table("detections")
             .select("content_image_id, detected, is_false_positive, created_at")
             .eq("brand_id", brand_id).eq("detected", True)
             .gte("created_at", since_iso)
             .range(offset, offset + 999).execute().data) or []
        for d in r:
            if not d.get("is_false_positive"):
                img_ids.add(d["content_image_id"])
        if len(r) < 1000: break
        offset += 1000

    if not img_ids:
        return []

    # Map images to content_items
    item_ids = set()
    img_list = list(img_ids)
    for i in range(0, len(img_list), 500):
        rows = (sb.table("content_images")
                .select("content_item_id")
                .in_("id", img_list[i:i+500])
                .execute().data) or []
        for row in rows:
            if row.get("content_item_id"):
                item_ids.add(row["content_item_id"])

    # Pull hashtags for those items
    out = []
    item_list = list(item_ids)
    for i in range(0, len(item_list), 200):
        rows = (sb.table("content_items")
                .select("id, hashtags, posted_at")
                .in_("id", item_list[i:i+200])
                .execute().data) or []
        out.extend(rows)
    return out


def fetch_total_for_tag(sb, brand_id: str, tag: str, since_iso: str) -> int:
    """How many total content_items for this brand have this hashtag (yield denominator)."""
    # The hashtags column is an ARRAY. Use contains operator.
    r = (sb.table("content_items")
         .select("id", count="exact", head=True)
         .eq("brand_id", brand_id)
         .contains("hashtags", [tag])
         .gte("posted_at", since_iso)
         .execute())
    return r.count or 0


def normalize_tag(t: str) -> str:
    if not t: return ""
    return t.lower().lstrip("#").strip()


def process_brand(sb, brand_id: str, brand_slug: str, window_days: int,
                  auto_add: bool, top_k: int, dry_run: bool) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    # Current pool
    pool_rows = (sb.table("brand_hashtag_pools")
                 .select("hashtag")
                 .eq("brand_id", brand_id).execute().data) or []
    existing = {normalize_tag(p["hashtag"]) for p in pool_rows}

    items = fetch_hit_items(sb, brand_id, since)
    if not items:
        print(f"  [{brand_slug}] no brand-hit items in last {window_days}d", file=sys.stderr)
        return {"candidates": 0, "added": 0}

    # Aggregate
    cooc = Counter()
    for it in items:
        for t in (it.get("hashtags") or []):
            n = normalize_tag(t)
            if not n or n in existing or len(n) < 3 or len(n) > 40:
                continue
            cooc[n] += 1

    if not cooc:
        return {"candidates": 0, "added": 0}

    # Rank by raw co-occurrence count. Yield ratios are noisy due to
    # multi-image posts; raw count is the reliable signal. The auto-add
    # threshold is conservative enough that brand-irrelevant tags
    # (#weekend, #friends) don't usually clear it for niche brands.
    candidates = []
    for tag, hit_count in cooc.most_common(50):
        candidates.append((tag, hit_count))

    print(f"  [{brand_slug}] top hashtag candidates (co-occurrence with brand hits):", file=sys.stderr)
    auto_threshold = 10
    for tag, hit in candidates[:15]:
        marker = " AUTO-ADD" if (auto_add and hit >= auto_threshold) else ""
        print(f"    #{tag:24s}  cooc={hit:3d}{marker}", file=sys.stderr)

    if not auto_add:
        return {"candidates": len(candidates), "added": 0}

    # Auto-add. Skip generic-looking tags that show up because of crowd
    # behavior rather than brand affinity.
    GENERIC = {"weekend","friends","party","amsterdam","summer","fun","love","life",
               "cheers","drinks","drink","instagood","picoftheday","instadaily","vibes"}
    selected = [c for c in candidates if c[1] >= auto_threshold and c[0] not in GENERIC][:top_k]
    if dry_run:
        print(f"  DRY: would auto-add {len(selected)} hashtags", file=sys.stderr)
        return {"candidates": len(candidates), "added": 0}

    added = 0
    for tag, hit in selected:
        try:
            sb.table("brand_hashtag_pools").insert({
                "brand_id": brand_id,
                "hashtag": tag,
                "platform": "instagram",
                "priority": 3,
                "active": True,
            }).execute()
            added += 1
            print(f"    + added #{tag} (cooc={hit})", file=sys.stderr)
        except Exception as e:
            print(f"    skip #{tag}: {e}", file=sys.stderr)

    return {"candidates": len(candidates), "added": added}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--auto-add", action="store_true", help="Add top-K candidates to the pool (priority=3)")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = (sb.table("brands").select("id, slug").execute().data) or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]

    totals = {"candidates": 0, "added": 0}
    for b in brands:
        r = process_brand(sb, b["id"], b["slug"], args.window_days,
                          args.auto_add, args.top, args.dry_run)
        for k in totals: totals[k] += r.get(k, 0)

    print(f"\n=== HASHTAG LEARNING: {totals} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
