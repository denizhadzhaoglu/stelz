#!/usr/bin/env python3
"""TikTok profile scan: for known tier-1/tier-2 TikTok creators, scrape their
recent feed and detect brand presence on the video cover-image.

The hashtag harvester (15_tiktok_harvest.py) discovers NEW TikTok creators
through tag scraping. This script closes the monitoring loop on the known
creators we already care about — same role as 18_daily_scan.py does for IG.

Strategy:
1. Pull TikTok creators with hits_seen >= 1 (or all tier_1 manually flagged)
2. For each handle, scrape their 10 most recent videos via clockworks actor
3. Upsert content_items (video) and content_images (cover thumbnail)
4. Detection happens via 33_detect_pending.py on the next aux cycle

Limitation: we only scan the cover image (default thumbnail), not video
keyframes. Keyframe extraction would 5x Apify cost and 5x Gemini cost. Will
revisit when TikTok hit rate climbs and the cost/value ratio justifies it.

Usage:
    python3 tools/stelz_brand_watch/48_tiktok_profile_scan.py
    python3 tools/stelz_brand_watch/48_tiktok_profile_scan.py --brand-slug stelz --max-creators 50
    python3 tools/stelz_brand_watch/48_tiktok_profile_scan.py --all-brands
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_CANDIDATES = [
    "clockworks/free-tiktok-scraper",
    "clockworks/tiktok-scraper",
]


def apify_run(actor: str, payload: dict, timeout: int = 240):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(
        url,
        json=payload,
        params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024},
        timeout=timeout + 30,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def scrape_profile(handle: str, results_per_page: int = 10):
    """Scrape one TikTok profile. Returns list of video dicts, or [] on failure."""
    payloads = {
        "clockworks/free-tiktok-scraper": {
            "profiles": [handle],
            "resultsPerPage": results_per_page,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        },
        "clockworks/tiktok-scraper": {
            "profiles": [handle],
            "resultsPerPage": results_per_page,
            "shouldDownloadVideos": False,
        },
    }
    for actor in ACTOR_CANDIDATES:
        try:
            items = apify_run(actor, payloads[actor])
            if items:
                return items
        except Exception as e:
            print(f"    {actor} err: {e}", file=sys.stderr)
    return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand-slug", default="stelz")
    p.add_argument("--all-brands", action="store_true")
    p.add_argument("--max-creators", type=int, default=40,
                   help="Cap per brand to avoid Apify cost blowups (default 40)")
    p.add_argument("--min-hits", type=int, default=1,
                   help="Minimum hits_seen to include creator (default 1)")
    p.add_argument("--posts-per-creator", type=int, default=10)
    p.add_argument("--skip-recent-hours", type=int, default=12,
                   help="Skip creators last scraped within N hours (default 12)")
    args = p.parse_args()

    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN missing")

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.all_brands:
        brands = sb.table("brands").select("id, slug").eq("active", True).execute().data or []
    else:
        b = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).maybe_single().execute().data
        if not b:
            sys.exit(f"brand {args.brand_slug} not found")
        brands = [b]

    grand_creators = 0
    grand_videos = 0
    grand_images = 0

    for b in brands:
        brand_id = b["id"]
        brand_slug = b["slug"]
        # Pick the top hit-producing TikTok creators that have an Apify-scrapable
        # handle. Order by hits_seen desc (real signal first), then by oldest
        # last_scraped_at (fair rotation among tied creators).
        cutoff_iso = None
        if args.skip_recent_hours > 0:
            from datetime import timedelta
            cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=args.skip_recent_hours)).isoformat()

        q = (sb.table("creators")
             .select("id, handle, last_scraped_at, hits_seen")
             .eq("brand_id", brand_id)
             .eq("platform", "tiktok")
             .in_("status", ["discovered", "promoted"])
             .gte("hits_seen", args.min_hits)
             .order("hits_seen", desc=True)
             .order("last_scraped_at", nullsfirst=True)
             .limit(args.max_creators))
        creators = q.execute().data or []
        if cutoff_iso:
            creators = [c for c in creators if not c.get("last_scraped_at") or c["last_scraped_at"] < cutoff_iso]
        if not creators:
            print(f"[{brand_slug}] no TikTok creators to scan (min_hits={args.min_hits})", file=sys.stderr)
            continue
        print(f"[{brand_slug}] TikTok profile scan: {len(creators)} creators × {args.posts_per_creator} posts", file=sys.stderr)

        new_videos = 0
        new_images = 0
        scanned = 0

        for c in creators:
            handle = c["handle"]
            t0 = time.time()
            videos = scrape_profile(handle, args.posts_per_creator)
            if not videos:
                continue
            scanned += 1
            print(f"  @{handle:<25} {len(videos)} videos ({time.time()-t0:.1f}s)", file=sys.stderr)

            for v in videos:
                vid = v.get("id") or v.get("videoMeta", {}).get("id")
                if not vid:
                    continue
                url = v.get("webVideoUrl") or f"https://www.tiktok.com/@{handle}/video/{vid}"
                try:
                    posted_at = None
                    ts = v.get("createTime")
                    if isinstance(ts, (int, float)) and ts > 1000000000:
                        posted_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    ci_res = sb.table("content_items").upsert({
                        "brand_id": brand_id,
                        "creator_id": c["id"],
                        "platform": "tiktok",
                        "external_id": str(vid),
                        "content_type": "tiktok",
                        "url": url,
                        "caption": (v.get("text") or "")[:5000],
                        "hashtags": [h.get("name") for h in (v.get("hashtags") or []) if h.get("name")],
                        "posted_at": posted_at,
                        "likes_count": v.get("diggCount"),
                        "comments_count": v.get("commentCount"),
                        "views_count": v.get("playCount"),
                    }, on_conflict="platform,external_id").execute()
                    ci_id = ci_res.data[0]["id"]
                    new_videos += 1
                except Exception as e:
                    print(f"    content err {vid}: {e}", file=sys.stderr)
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

            # Bump last_scraped_at so we respect the skip window next time.
            sb.table("creators").update({
                "last_scraped_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", c["id"]).execute()

        print(f"[{brand_slug}] scanned={scanned} videos+={new_videos} images+={new_images}",
              file=sys.stderr)
        grand_creators += scanned
        grand_videos += new_videos
        grand_images += new_images

    print(f"\n=== TIKTOK PROFILE SCAN SUMMARY ===", file=sys.stderr)
    print(f"Creators scanned: {grand_creators}", file=sys.stderr)
    print(f"New videos: {grand_videos}", file=sys.stderr)
    print(f"New cover images: {grand_images}", file=sys.stderr)


if __name__ == "__main__":
    main()
