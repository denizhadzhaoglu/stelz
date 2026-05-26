#!/usr/bin/env python3
"""Instagram Stories harvest. Requires IG_SESSION_ID env var (cookie) because
public stories are login-walled. Setup:
  1. Klant levert IG account waarmee STELZ-relevante stories zichtbaar zijn
  2. Cookie sessionid wordt 1x extract via browser devtools
  3. Token in PA/.env als IG_SESSION_ID=xxx
  4. Cron pakt vanzelf op via aux schedule

Scrapt stories van tier-1/tier-2 IG creators in de brand-monitoring set.
Each story screenshot -> content_images -> detection pipeline picks it up.

Usage:
    python3 tools/stelz_brand_watch/49_ig_story_scan.py --brand-slug stelz
    python3 tools/stelz_brand_watch/49_ig_story_scan.py --all-brands --max-creators 50
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
IG_SESSION_ID = os.getenv("IG_SESSION_ID")  # required for live stories
# Two candidate Apify actors that handle stories given a sessionid cookie.
# We try them in order; first success wins.
ACTOR_CANDIDATES = [
    "apify/instagram-scraper",
    "apify/instagram-stories-scraper",
]


def apify_run(actor: str, payload: dict, timeout: int = 240):
    url = f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    try:
        r = requests.post(
            url, json=payload,
            params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024},
            timeout=timeout + 30,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  actor {actor} failed: {e}", file=sys.stderr)
        return None


def scrape_stories(handles: list[str]) -> list[dict]:
    """Scrape current stories from a list of IG usernames."""
    if not IG_SESSION_ID:
        print("WARNING: IG_SESSION_ID not set. Story scraping requires a logged-in cookie.",
              file=sys.stderr)
        print("Set IG_SESSION_ID in PA/.env (extract sessionid cookie from instagram.com)",
              file=sys.stderr)
        return []

    payloads = {
        "apify/instagram-scraper": {
            "directUrls": [f"https://www.instagram.com/{h}/" for h in handles],
            "resultsType": "stories",
            "resultsLimit": 50,
            "loginCookies": [{"name": "sessionid", "value": IG_SESSION_ID}],
        },
        "apify/instagram-stories-scraper": {
            "usernames": handles,
            "sessionId": IG_SESSION_ID,
        },
    }
    for actor in ACTOR_CANDIDATES:
        items = apify_run(actor, payloads[actor])
        if items:
            print(f"  actor used: {actor}, {len(items)} story frames", file=sys.stderr)
            return items
    return []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand-slug", default="stelz")
    p.add_argument("--all-brands", action="store_true")
    p.add_argument("--max-creators", type=int, default=30)
    p.add_argument("--min-tier", default="tier_2", help="Minimum tier to include")
    args = p.parse_args()

    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN missing")
    if not IG_SESSION_ID:
        print("Note: IG_SESSION_ID env not set — stories cannot be scraped without it.",
              file=sys.stderr)
        print("This script will exit cleanly so the cron stays healthy.", file=sys.stderr)
        return

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.all_brands:
        brands = sb.table("brands").select("id, slug").eq("active", True).execute().data or []
    else:
        b = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).maybe_single().execute().data
        if not b:
            sys.exit(f"brand {args.brand_slug} not found")
        brands = [b]

    grand_stories, grand_images = 0, 0

    for b in brands:
        brand_id, brand_slug = b["id"], b["slug"]
        # Pick top IG creators by hits or tier
        creators = (sb.table("creators")
                    .select("id, handle")
                    .eq("brand_id", brand_id)
                    .eq("platform", "instagram")
                    .in_("tier", ["tier_1", "tier_2"])
                    .order("hits_seen", desc=True)
                    .limit(args.max_creators)
                    .execute()).data or []
        if not creators:
            print(f"[{brand_slug}] no qualifying IG creators", file=sys.stderr)
            continue

        print(f"[{brand_slug}] scraping stories for {len(creators)} creators", file=sys.stderr)
        handles = [c["handle"] for c in creators]
        c_by_handle = {c["handle"]: c for c in creators}
        items = scrape_stories(handles)

        skipped_non_story = 0
        for it in items:
            handle = it.get("ownerUsername") or it.get("username")
            creator = c_by_handle.get(handle)
            if not creator:
                continue

            # Strict story-shape filter: the actor with resultsType=stories sometimes
            # leaks in reels/posts. Reject anything that looks like a feed item.
            # A real story has NO shortCode (posts/reels do), has a numeric id, and
            # typically has expiringAt or takenAt. Reels have a shortCode + caption.
            if it.get("shortCode") or it.get("type") in ("Sidecar",) or it.get("productType") in ("clips", "feed"):
                skipped_non_story += 1
                continue

            story_id = it.get("id") or it.get("storyId") or it.get("mediaId")
            if not story_id or not str(story_id).isdigit():
                skipped_non_story += 1
                continue

            display_url = it.get("displayUrl") or it.get("imageUrl") or it.get("url")
            posted_at = None
            ts = it.get("takenAt") or it.get("takenAtTimestamp") or it.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 1e9:
                posted_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            elif isinstance(ts, str) and ts.strip():
                posted_at = ts

            # Build a proper IG story permalink for the URL field; keep the CDN image
            # URL only on content_images. This stops "open original" from opening a
            # raw image and looking like a reel.
            story_permalink = f"https://www.instagram.com/stories/{handle}/{story_id}/"

            try:
                ci_res = sb.table("content_items").upsert({
                    "brand_id": brand_id,
                    "creator_id": creator["id"],
                    "platform": "instagram",
                    "external_id": str(story_id),
                    "content_type": "story",
                    "url": story_permalink,
                    "caption": "",  # stories rarely have captions
                    "hashtags": [],
                    "posted_at": posted_at,
                }, on_conflict="platform,external_id").execute()
                ci_id = ci_res.data[0]["id"]
                grand_stories += 1
            except Exception as e:
                print(f"  story upsert err {story_id}: {e}", file=sys.stderr)
                continue

            if display_url:
                existing = sb.table("content_images").select("id").eq("content_item_id", ci_id).limit(1).execute()
                if not existing.data:
                    sb.table("content_images").insert({
                        "content_item_id": ci_id,
                        "brand_id": brand_id,
                        "image_url": display_url,
                        "sequence_idx": 0,
                    }).execute()
                    grand_images += 1
        if skipped_non_story:
            print(f"  skipped {skipped_non_story} non-story items leaked through stories actor", file=sys.stderr)

    print(f"\n=== STORY SCAN SUMMARY ===", file=sys.stderr)
    print(f"Stories upserted: {grand_stories}", file=sys.stderr)
    print(f"New images: {grand_images}", file=sys.stderr)


if __name__ == "__main__":
    main()
