#!/usr/bin/env python3
"""Creator graph expansion: mine the social-graph of existing tier-1 creators
to find new candidates the brand hasn't discovered yet.

Logic per brand:
  1. Find tier-1 creators (status not archived).
  2. Pull all content_items by those creators that resulted in a brand hit.
  3. Aggregate the `mentions` array (@-handles in captions) across those posts.
  4. For each @handle that appears N times and is not yet in creators/discovery_queue,
     insert into discovery_queue with `source = 'creator_graph'` + signal_count = N.
  5. The existing auto_add promotion rules pick them up next run.

Bonus: same mining on the official brand handle posts (e.g. @drinkstelz)
captures who the brand itself tags or who tags the brand. Strong signal.

Usage:
    python3 tools/stelz_brand_watch/41_creator_graph_expand.py
    python3 tools/stelz_brand_watch/41_creator_graph_expand.py --brand stelz
    python3 tools/stelz_brand_watch/41_creator_graph_expand.py --min-cooccurrences 2 --dry-run
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

HANDLE_RE = re.compile(r"@?([a-zA-Z0-9_.]{2,30})")


def normalize_handle(h: str) -> str:
    if not h: return ""
    return re.sub(r"[._\-]", "", h.lower()).strip()


def process_brand(sb, brand_id: str, brand_slug: str,
                  min_cooc: int, dry_run: bool) -> int:
    # 1. Existing creator handles (any case/format)
    existing = sb.table("creators").select("handle, platform").eq("brand_id", brand_id).execute().data or []
    seen_norm = set()
    for e in existing:
        seen_norm.add((e["platform"], normalize_handle(e["handle"])))

    # 1b. Existing discovery_queue handles
    queued = sb.table("discovery_queue").select("handle, platform").eq("brand_id", brand_id).execute().data or []
    for q in queued:
        seen_norm.add((q["platform"], normalize_handle(q["handle"])))

    # 2. Tier-1 creators
    tier1 = (sb.table("creators")
             .select("id, handle, platform")
             .eq("brand_id", brand_id)
             .eq("tier", "tier_1")
             .is_("archived_at", "null")
             .execute().data) or []
    if not tier1:
        print(f"  [{brand_slug}] no tier_1 creators yet; skipping graph expansion", file=sys.stderr)
        return 0
    tier1_ids = [c["id"] for c in tier1]

    # 3. Their content_items with a positive brand detection
    # We need: content_items.id JOIN detections WHERE detected AND not is_false_positive
    # Easier path: pull all content_items by tier-1 creators, then filter by detections.
    cooc: Counter = Counter()
    chunk_size = 100
    detection_ids_by_image: dict = {}

    # Pull positively-detected content_image -> content_item map
    dets = (sb.table("detections")
            .select("content_image_id, detected, is_false_positive")
            .eq("brand_id", brand_id)
            .eq("detected", True)
            .limit(20000).execute().data) or []
    hit_image_ids = {d["content_image_id"] for d in dets if not d.get("is_false_positive")}
    if not hit_image_ids:
        return 0

    # Pull content_images that link those to content_item_id
    item_ids: set = set()
    img_list = list(hit_image_ids)
    for i in range(0, len(img_list), 500):
        r = sb.table("content_images").select("content_item_id").in_("id", img_list[i:i+500]).execute().data or []
        for row in r:
            if row.get("content_item_id"):
                item_ids.add(row["content_item_id"])

    if not item_ids:
        return 0

    # Pull content_items by tier-1 creators that are in item_ids
    items_q = (sb.table("content_items")
               .select("creator_id, platform, mentions")
               .in_("creator_id", tier1_ids))
    items = items_q.execute().data or []
    candidate_items = [it for it in items if it.get("creator_id") and it.get("mentions")]

    for it in candidate_items:
        platform = it.get("platform") or "instagram"
        for mention in (it.get("mentions") or []):
            handle = (mention or "").strip().lstrip("@")
            if not handle or len(handle) < 2 or len(handle) > 30:
                continue
            norm = normalize_handle(handle)
            if (platform, norm) in seen_norm:
                continue
            cooc[(platform, handle)] += 1

    # Filter to threshold
    candidates = [(p, h, n) for (p, h), n in cooc.items() if n >= min_cooc]
    candidates.sort(key=lambda x: -x[2])

    print(f"  [{brand_slug}] tier_1={len(tier1)}, hit_items={len(candidate_items)}, "
          f"new_candidates={len(candidates)} (≥{min_cooc} co-occurrences)", file=sys.stderr)
    for p, h, n in candidates[:10]:
        print(f"    @{h} ({p}) co-occurred {n}×", file=sys.stderr)

    if dry_run or not candidates:
        return len(candidates)

    inserts = [{
        "brand_id": brand_id,
        "platform": p,
        "handle": h,
        "source": "creator_graph",
        "signal_count": n,
        "status": "new",
    } for p, h, n in candidates]

    for i in range(0, len(inserts), 200):
        sb.table("discovery_queue").upsert(
            inserts[i:i+200],
            on_conflict="brand_id,platform,handle",
        ).execute()
    return len(candidates)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--min-cooccurrences", type=int, default=2,
                   help="Min times a handle must co-occur with a tier_1's brand hits")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = (sb.table("brands").select("id, slug").execute().data) or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    if not brands:
        print("No brands selected.", file=sys.stderr)
        return

    total = 0
    for b in brands:
        total += process_brand(sb, b["id"], b["slug"], args.min_cooccurrences, args.dry_run)
    print(f"\n=== GRAPH EXPANSION: queued {total} candidates ===", file=sys.stderr)


if __name__ == "__main__":
    main()
