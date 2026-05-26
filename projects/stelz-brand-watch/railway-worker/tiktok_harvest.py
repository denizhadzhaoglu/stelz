#!/usr/bin/env python3
"""Sprint D: TikTok hashtag scrape for STELZ + NL lifestyle tags.

Adds tiktok platform to the brand watch. Uses Apify clockworks/free-tiktok-scraper.

Each TikTok has a cover image (thumbnail), which we scan via Gemini. For richer
detection we would frame-sample the video but that triples cost; thumbnail is
sufficient baseline.

Output: creators + content_items + content_images in DB (platform='tiktok').

Usage:
    python3 tools/stelz_brand_watch/15_tiktok_harvest.py
    python3 tools/stelz_brand_watch/15_tiktok_harvest.py --per-tag 200
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
# Two reliable actors for TikTok hashtag scraping
ACTOR_CANDIDATES = [
    "clockworks/free-tiktok-scraper",
    "clockworks/tiktok-scraper",
]

# Legacy fallback only — primary source is brand_hashtag_pools.
LEGACY_STELZ_HASHTAGS = [
    "stelz", "stelzhardseltzer", "stelzhardlemonade", "stelzhardicedtea",
    "drinkstelz", "hardseltzer", "vrijmibo", "studentenleven",
    "huisfeest", "koningsdag",
]


def fetch_tiktok_hashtags_for_brand(sb, brand_id: str, brand_slug: str) -> list[str]:
    rows = (sb.table("brand_hashtag_pools")
            .select("hashtag, priority")
            .eq("brand_id", brand_id)
            .eq("platform", "tiktok")
            .eq("active", True)
            .order("priority", desc=True)
            .execute()).data or []
    tags = [r["hashtag"] for r in rows if r.get("hashtag")]
    if tags:
        return tags
    if brand_slug == "stelz":
        return LEGACY_STELZ_HASHTAGS
    return []


def apify_run(actor, payload, timeout=400):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(url, json=payload, params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}, timeout=timeout+30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def try_scrape_hashtag(tag, per_tag):
    """Try each actor until one works for the hashtag scrape."""
    payloads_per_actor = {
        "clockworks/free-tiktok-scraper": {
            "hashtags": [tag],
            "resultsPerPage": per_tag,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        },
        "clockworks/tiktok-scraper": {
            "hashtags": [tag],
            "resultsPerPage": per_tag,
            "shouldDownloadVideos": False,
        },
    }
    for actor in ACTOR_CANDIDATES:
        try:
            result = apify_run(actor, payloads_per_actor[actor])
            if result is None:
                continue
            return actor, result
        except Exception as e:
            print(f"    {actor} err: {e}", file=sys.stderr)
            continue
    return None, []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-tag", type=int, default=100)
    p.add_argument("--brand-slug", default="stelz")
    p.add_argument("--all-brands", action="store_true",
                   help="Process every active brand's TikTok hashtag pool")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.all_brands:
        brands = sb.table("brands").select("id, slug").eq("active", True).execute().data or []
    else:
        b = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).maybe_single().execute().data
        if not b:
            sys.exit(f"brand {args.brand_slug} not found")
        brands = [b]

    for b in brands:
        brand_id = b["id"]
        brand_slug = b["slug"]
        hashtags = fetch_tiktok_hashtags_for_brand(sb, brand_id, brand_slug)
        if not hashtags:
            print(f"[{brand_slug}] no tiktok hashtags configured, skipping", file=sys.stderr)
            continue
        print(f"[{brand_slug}] TikTok hashtag scrape: {len(hashtags)} tags @ {args.per_tag}/each", file=sys.stderr)
        _harvest_one_brand(sb, brand_id, brand_slug, hashtags, args.per_tag)


def _harvest_one_brand(sb, brand_id: str, brand_slug: str, hashtags: list[str], per_tag: int):
    all_videos = []
    used_actor = None
    for tag in hashtags:
        print(f"  #{tag}...", file=sys.stderr)
        t0 = time.time()
        actor, items = try_scrape_hashtag(tag, per_tag)
        if not items:
            print(f"    no results", file=sys.stderr)
            continue
        used_actor = actor
        print(f"    {len(items)} videos in {time.time()-t0:.1f}s ({actor})", file=sys.stderr)
        for v in items:
            v["_hashtag"] = tag
        all_videos.extend(items)

    if not all_videos:
        print("No TikTok data retrieved. Actors may have changed input schema or be unavailable.", file=sys.stderr)
        return

    # Dedupe by video id
    seen = set()
    unique = []
    for v in all_videos:
        vid = v.get("id") or v.get("videoMeta", {}).get("id") or v.get("webVideoUrl")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        unique.append(v)
    print(f"\n{len(unique)} unique TikToks", file=sys.stderr)

    new_creators = 0
    new_content = 0
    new_images = 0
    creators_cache = {}

    for v in unique:
        author = v.get("authorMeta") or {}
        handle = author.get("name") or author.get("uniqueId") or v.get("authorMeta", {}).get("uniqueId")
        if not handle:
            continue
        full_name = author.get("nickName")
        followers = author.get("fans")

        if handle not in creators_cache:
            res = sb.table("creators").upsert({
                "brand_id": brand_id,
                "platform": "tiktok",
                "handle": handle,
                "full_name": full_name,
                "follower_count": followers,
                "category": "person",
                "status": "discovered",
                "auto_added_via": f"tiktok_hashtag:{v.get('_hashtag', 'unknown')}",
            }, on_conflict="brand_id,platform,handle").execute()
            creators_cache[handle] = res.data[0]["id"]
            new_creators += 1

        creator_id = creators_cache[handle]
        vid = v.get("id") or v.get("videoMeta", {}).get("id")
        url = v.get("webVideoUrl") or f"https://www.tiktok.com/@{handle}/video/{vid}"

        try:
            ci_res = sb.table("content_items").upsert({
                "brand_id": brand_id,
                "creator_id": creator_id,
                "platform": "tiktok",
                "external_id": str(vid),
                "content_type": "tiktok",
                "url": url,
                "caption": (v.get("text") or "")[:5000],
                "hashtags": [h.get("name") for h in (v.get("hashtags") or []) if h.get("name")],
                "posted_at": (
                    __import__("datetime").datetime.fromtimestamp(v["createTime"], tz=__import__("datetime").timezone.utc).isoformat()
                    if isinstance(v.get("createTime"), (int, float)) and v["createTime"] > 1000000000
                    else (__import__("datetime").datetime.fromtimestamp(int(str(vid)) >> 32, tz=__import__("datetime").timezone.utc).isoformat() if vid and str(vid).isdigit() else None)
                ),
                "likes_count": v.get("diggCount"),
                "comments_count": v.get("commentCount"),
                "views_count": v.get("playCount"),
            }, on_conflict="platform,external_id").execute()
            ci_id = ci_res.data[0]["id"]
            new_content += 1
        except Exception as e:
            print(f"  content err {vid}: {e}", file=sys.stderr)
            continue

        cover = (v.get("videoMeta") or {}).get("coverUrl") or v.get("cover")
        if cover:
            existing = sb.table("content_images").select("id").eq("content_item_id", ci_id).limit(1).execute()
            if not existing.data:
                sb.table("content_images").insert({
                    "content_item_id": ci_id,
                    "brand_id": brand_id,
                    "image_url": cover,
                    "sequence_idx": 0,
                }).execute()
                new_images += 1

    print(f"\n=== TIKTOK SUMMARY ===", file=sys.stderr)
    print(f"Actor used: {used_actor}", file=sys.stderr)
    print(f"Unique TikToks: {len(unique)}", file=sys.stderr)
    print(f"New creators: {new_creators}", file=sys.stderr)
    print(f"New content: {new_content}", file=sys.stderr)
    print(f"New images: {new_images}", file=sys.stderr)


if __name__ == "__main__":
    main()
