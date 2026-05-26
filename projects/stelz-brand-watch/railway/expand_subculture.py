#!/usr/bin/env python3
"""Expand a subculture's reach: the "olievlek" mechanism.

Given a subculture, find more creators that fit the same scene. Method:
1. Pull the top seed creators in this subculture (highest confidence + most
   STELZ detections so far).
2. Take the union of their post hashtags + the subculture's signature_hashtags.
3. Apify-scrape posts under those hashtags (a fresh sweep).
4. Extract poster handles, de-dupe against creators we already know.
5. Add the new handles to discovery_queue with source='subculture_expansion'.
6. Auto-link them to this subculture with confidence ~0.6 (provisional).
7. The user reviews them through the existing daily_scan / auto_add flow.

The user always triggers expansion explicitly. The tool reports back what
it found before consuming any further credits on detection.

Usage:
    python3 tools/stelz_brand_watch/31_expand_subculture.py --slug student_life
    python3 tools/stelz_brand_watch/31_expand_subculture.py --slug vrijmibo --max-tags 5 --per-tag 100
    python3 tools/stelz_brand_watch/31_expand_subculture.py --slug festivals_events --dry-run
"""

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR = "apify/instagram-hashtag-scraper"


def apify_hashtag(tag, results=80, timeout=180):
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR.replace('/', '~')}/run-sync-get-dataset-items"
    payload = {"hashtags": [tag], "resultsLimit": results}
    r = requests.post(url, json=payload, params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}, timeout=timeout+30)
    r.raise_for_status()
    return r.json() or []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--slug", help="Subculture slug to expand (CLI mode)")
    p.add_argument("--expansion-id", help="Existing subculture_expansions row to process (queue mode)")
    p.add_argument("--max-tags", type=int, default=8, help="Max hashtags to scrape per run")
    p.add_argument("--per-tag", type=int, default=80, help="Posts per hashtag")
    p.add_argument("--dry-run", action="store_true", help="Plan but don't scrape")
    args = p.parse_args()

    if not args.slug and not args.expansion_id:
        sys.exit("Specify either --slug or --expansion-id")

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    # Queue mode: an expansion row already exists (created by RPC + claim).
    # Pull subculture from there.
    existing_exp_id = None
    if args.expansion_id:
        exp_row = sb.table("subculture_expansions").select("*").eq("id", args.expansion_id).execute().data
        if not exp_row:
            sys.exit(f"expansion {args.expansion_id} not found")
        exp_row = exp_row[0]
        existing_exp_id = exp_row["id"]
        brand_id = exp_row["brand_id"]
        subc = sb.table("subcultures").select("*").eq("id", exp_row["subculture_id"]).execute().data[0]
        # Parse max_tags / per_tag from notes if present (RPC stored them)
        notes = exp_row.get("notes") or ""
        import re as _re
        m_max = _re.search(r"max_tags=(\d+)", notes)
        m_per = _re.search(r"per_tag=(\d+)",  notes)
        if m_max: args.max_tags = int(m_max.group(1))
        if m_per: args.per_tag  = int(m_per.group(1))
    else:
        brand = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]
        brand_id = brand["id"]
        subc = sb.table("subcultures").select("*").eq("brand_id", brand_id).eq("slug", args.slug).execute().data
        if not subc:
            sys.exit(f"Subculture '{args.slug}' not found for STELZ")
        subc = subc[0]
    print(f"Expanding: {subc.get('emoji','')} {subc['name']} ({subc['slug']})", file=sys.stderr)

    # 1. Seed creators: top members of this subculture, by detection count.
    seeds = (sb.table("creator_subcultures")
             .select("creator_id, confidence, "
                     "creators!inner(handle, platform, follower_count, brand_id)")
             .eq("subculture_id", subc["id"])
             .order("confidence", desc=True)
             .limit(20)
             .execute().data) or []
    seed_creators = [s for s in seeds if s["creators"]["brand_id"] == brand_id]
    print(f"  seed creators: {len(seed_creators)}", file=sys.stderr)

    # 2. Build hashtag pool: signature + most-used hashtags by the seeds.
    seed_ids = [s["creator_id"] for s in seed_creators]
    seed_hashtags = Counter()
    if seed_ids:
        offset = 0
        while True:
            r = (sb.table("content_items")
                 .select("creator_id, hashtags")
                 .in_("creator_id", seed_ids[:50])  # cap to avoid huge IN list
                 .range(offset, offset+999).execute())
            if not r.data: break
            for ci in r.data:
                for t in (ci.get("hashtags") or []):
                    if t and 3 <= len(t) <= 40:
                        seed_hashtags[t.lower()] += 1
            if len(r.data) < 1000: break
            offset += 1000

    # Drop noise + the brand's own hashtags
    noise = {"fyp","foryou","viral","trending","love","happy","life","reels","reel","tiktok","instagram"}
    brand_tags = {"stelz","drinkstelz","stelzhardseltzer","stelzhardicedtea","stelzhardlemonade","stelzmixedclassics"}
    for t in list(seed_hashtags):
        if t in noise or t in brand_tags:
            del seed_hashtags[t]

    # Merge: signature first, then top organic
    pool = list(dict.fromkeys(
        [t.lower() for t in (subc.get("signature_hashtags") or [])] +
        [t for t, _ in seed_hashtags.most_common(args.max_tags * 2)]
    ))[: args.max_tags]
    print(f"  hashtag pool: {pool}", file=sys.stderr)

    # 3. Log expansion run — either update the existing row (queue mode) or
    #    insert a new one (CLI mode).
    if existing_exp_id:
        sb.table("subculture_expansions").update({
            "seed_creator_ids": seed_ids,
            "notes": f"pool: {','.join(pool)}",
            "status": "running",
        }).eq("id", existing_exp_id).execute()
        exp_id = existing_exp_id
    else:
        exp_row = sb.table("subculture_expansions").insert({
            "brand_id": brand_id,
            "subculture_id": subc["id"],
            "method": "hashtag_scrape",
            "seed_creator_ids": seed_ids,
            "triggered_by": "cli",
            "notes": f"pool: {','.join(pool)}",
            "status": "running",
        }).execute().data[0]
        exp_id = exp_row["id"]

    if args.dry_run:
        print("Dry-run: would scrape and dedupe new handles. Stopping.", file=sys.stderr)
        sb.table("subculture_expansions").update({
            "status": "completed",
            "completed_at": "now()",
            "candidates_found": 0,
            "added_to_queue": 0,
            "notes": "dry-run",
        }).eq("id", exp_id).execute()
        return

    # 4. Scrape hashtags via Apify
    new_handles = Counter()
    apify_errors = []
    for tag in pool:
        print(f"  #{tag}...", file=sys.stderr)
        try:
            t0 = time.time()
            posts = apify_hashtag(tag, results=args.per_tag)
            print(f"    {len(posts)} posts in {time.time()-t0:.1f}s", file=sys.stderr)
            for p_post in posts:
                handle = (p_post.get("ownerUsername") or "").lower()
                if handle:
                    new_handles[handle] += 1
        except Exception as e:
            err_msg = str(e)[:160]
            apify_errors.append(f"#{tag}: {err_msg}")
            print(f"    err: {err_msg}", file=sys.stderr)
            continue

    # If EVERY hashtag failed with Apify, mark expansion failed so the
    # dashboard surfaces the underlying issue (usually quota/limit related)
    # rather than silently claiming "completed with 0 results".
    if apify_errors and len(apify_errors) == len(pool):
        err_summary = " ; ".join(apify_errors[:3])
        sb.table("subculture_expansions").update({
            "status": "failed",
            "completed_at": "now()",
            "notes": f"Apify error on all {len(pool)} hashtags: {err_summary}",
        }).eq("id", exp_id).execute()
        print(f"\n✗ All hashtag scrapes failed: {err_summary}", file=sys.stderr)
        sys.exit(2)

    # 5. Dedupe against existing creators
    existing_handles = set()
    offset = 0
    while True:
        r = sb.table("creators").select("handle").eq("brand_id", brand_id).range(offset, offset+999).execute()
        if not r.data: break
        for c in r.data: existing_handles.add((c["handle"] or "").lower())
        if len(r.data) < 1000: break
        offset += 1000
    candidates = {h: n for h, n in new_handles.items() if h not in existing_handles}
    print(f"\n  total unique handles: {len(new_handles)}", file=sys.stderr)
    print(f"  new (not yet tracked): {len(candidates)}", file=sys.stderr)

    # Need at least 2 signal-hits to be promoted to discovery_queue
    promoted = {h: n for h, n in candidates.items() if n >= 2}
    print(f"  promoted to discovery_queue (>=2 signal hits): {len(promoted)}", file=sys.stderr)

    # 6. Upsert into discovery_queue
    rows = []
    for h, n in promoted.items():
        rows.append({
            "brand_id": brand_id,
            "platform": "instagram",
            "handle": h,
            "source": f"subculture_expansion:{subc['slug']}",
            "signal_count": n,
            "status": "pending",
        })
    if rows:
        for i in range(0, len(rows), 200):
            sb.table("discovery_queue").upsert(
                rows[i:i+200],
                on_conflict="brand_id,platform,handle",
            ).execute()

    # 7. Log expansion result
    sb.table("subculture_expansions").update({
        "candidates_found": len(candidates),
        "added_to_queue": len(promoted),
        "cost_credits": len(pool) * 5,  # rough cost: 5 credits per hashtag scrape
        "completed_at": "now()",
        "status": "completed",
    }).eq("id", exp_id).execute()

    print(f"\n=== EXPANSION COMPLETE ===", file=sys.stderr)
    print(f"  Subculture: {subc['name']}", file=sys.stderr)
    print(f"  Hashtag pool: {len(pool)}", file=sys.stderr)
    print(f"  Unique handles found: {len(new_handles)}", file=sys.stderr)
    print(f"  New handles (not yet tracked): {len(candidates)}", file=sys.stderr)
    print(f"  Promoted to discovery_queue: {len(promoted)}", file=sys.stderr)
    print(f"  Next: run auto_add.py to bring these into creators table", file=sys.stderr)


if __name__ == "__main__":
    main()
