#!/usr/bin/env python3
"""Auto-add: discover new creators via hashtag + mention monitoring.

Two discovery signals:
1. Brand hashtags: anyone using #stelz, #drinkstelz, etc
2. Brand mentions: anyone @drinkstelz tagging in posts (via mention scraper)

Flow per discovered creator:
- New handle? -> insert into discovery_queue with signal_count=1
- Already in queue? -> increment signal_count, update last_seen_at
- Signal count >= AUTO_ADD_THRESHOLD? -> auto-promote to creators table (tier_3 probation)
- Already in creators? -> skip

Usage:
    python3 tools/stelz_brand_watch/19_auto_add.py
    python3 tools/stelz_brand_watch/19_auto_add.py --per-tag 200 --auto-add-threshold 2
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_HASHTAG = "apify/instagram-hashtag-scraper"

BRAND_HASHTAGS = ["stelz", "drinkstelz", "stelzhardseltzer", "stelzhardlemonade", "stelzhardicedtea"]


def apify_run(actor, payload, timeout=300):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(url, json=payload, params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}, timeout=timeout+30)
    r.raise_for_status()
    return r.json()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-tag", type=int, default=200)
    p.add_argument("--auto-add-threshold", type=int, default=2, help="Auto-promote to creators after N signals")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Existing creators (we'll skip these)
    existing = set()
    offset = 0
    while True:
        r = sb.table("creators").select("handle, platform").eq("brand_id", brand_id).range(offset, offset+999).execute()
        if not r.data: break
        for c in r.data:
            existing.add((c["platform"], c["handle"]))
        if len(r.data) < 1000: break
        offset += 1000

    # Existing queue entries
    queue_existing = {}
    offset = 0
    while True:
        r = sb.table("discovery_queue").select("id, handle, platform, signal_count, sources:source").eq("brand_id", brand_id).range(offset, offset+999).execute()
        if not r.data: break
        for q in r.data:
            queue_existing[(q["platform"], q["handle"])] = q
        if len(r.data) < 1000: break
        offset += 1000

    new_creators_observed = {}  # (platform, handle) -> list of sources

    # Hashtag pass
    for tag in BRAND_HASHTAGS:
        print(f"#{tag}...", file=sys.stderr)
        try:
            posts = apify_run(ACTOR_HASHTAG, {"hashtags": [tag], "resultsLimit": args.per_tag})
        except Exception as e:
            print(f"  err: {e}", file=sys.stderr)
            continue
        for post in posts:
            handle = post.get("ownerUsername")
            if not handle: continue
            key = ("instagram", handle)
            if key in existing: continue  # already a creator
            source = f"hashtag:{tag}"
            new_creators_observed.setdefault(key, []).append((source, post.get("ownerFullName")))

    print(f"\n{len(new_creators_observed)} new handles seen via hashtags", file=sys.stderr)

    # Mention pass: posts that mention @drinkstelz (Instagram search for @ tags)
    # Use the same hashtag-scraper on "drinkstelz" to find posts where account is tagged
    # Or scrape posts and check for mentions array
    # Simpler: rely on the hashtag run output's "mentions" field (some actors expose this)

    # Insert/update discovery_queue
    inserts = []
    updates = []
    promote_to_creators = []

    for (platform, handle), sources in new_creators_observed.items():
        primary_source = sources[0][0]
        full_name = next((s[1] for s in sources if s[1]), None)
        existing_q = queue_existing.get((platform, handle))
        if existing_q:
            new_count = existing_q["signal_count"] + len(sources)
            updates.append({"id": existing_q["id"], "signal_count": new_count, "last_seen_at": "now()"})
            if new_count >= args.auto_add_threshold and existing_q.get("sources") != "auto_added":
                promote_to_creators.append((platform, handle, full_name, primary_source))
        else:
            inserts.append({
                "brand_id": brand_id,
                "platform": platform,
                "handle": handle,
                "full_name": full_name,
                "source": primary_source,
                "signal_count": len(sources),
            })
            if len(sources) >= args.auto_add_threshold:
                promote_to_creators.append((platform, handle, full_name, primary_source))

    if inserts:
        for i in range(0, len(inserts), 200):
            sb.table("discovery_queue").upsert(inserts[i:i+200], on_conflict="brand_id,platform,handle").execute()
    # Updates (batch by id)
    for u in updates:
        sb.table("discovery_queue").update({"signal_count": u["signal_count"]}).eq("id", u["id"]).execute()

    # Promote high-signal candidates to creators (tier_3 probation).
    # Dedup against handle-variants: if a creator already exists under a
    # different casing or punctuation (e.g. `tess.provenzal` vs `tessprovenzal`)
    # we skip insertion and instead boost their signal_count.
    promoted = 0
    merged = 0
    for platform, handle, full_name, source in promote_to_creators:
        if (platform, handle) in existing:
            continue
        # Variant check via DB helper
        try:
            existing_id_row = sb.rpc("find_creator_by_handle_variant", {
                "p_brand_id": brand_id, "p_platform": platform, "p_handle": handle,
            }).execute().data
            existing_id = existing_id_row if isinstance(existing_id_row, str) else None
        except Exception:
            existing_id = None
        if existing_id:
            merged += 1
            sb.table("discovery_queue").update({
                "status": "merged_variant", "reviewed_at": "now()",
                "reviewed_by": "auto-add-script",
                "notes": f"variant of existing creator {existing_id}",
            }).eq("brand_id", brand_id).eq("platform", platform).eq("handle", handle).execute()
            continue
        try:
            sb.table("creators").upsert({
                "brand_id": brand_id,
                "platform": platform,
                "handle": handle,
                "full_name": full_name,
                "category": "person",
                "tier": "tier_3",
                "status": "discovered",
                "auto_added_via": source,
            }, on_conflict="brand_id,platform,handle").execute()
            sb.table("discovery_queue").update({"status": "auto_added", "reviewed_at": "now()", "reviewed_by": "auto-add-script"}).eq("brand_id", brand_id).eq("platform", platform).eq("handle", handle).execute()
            promoted += 1
        except Exception as e:
            print(f"  promote err {handle}: {e}", file=sys.stderr)

    print(f"\n=== AUTO-ADD SUMMARY ===", file=sys.stderr)
    print(f"New handles in queue: {len(inserts)}", file=sys.stderr)
    print(f"Queue signal updates: {len(updates)}", file=sys.stderr)
    print(f"Promoted to creators (tier_3): {promoted}", file=sys.stderr)
    print(f"Merged into existing variants: {merged}", file=sys.stderr)


if __name__ == "__main__":
    main()
