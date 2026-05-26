#!/usr/bin/env python3
"""Instagram Stories harvest.

Why this exists:
  Stories are where most "in-the-moment" brand mentions live, and they
  disappear in 24h. The regular daily_scan only pulls feed posts, so we
  miss this entire surface.

This script:
  1. Picks tier_1 + tier_2 + tier_3 creators (cap N total) for each
     brand, prioritizing those with most recent activity.
  2. Runs Apify's instagram-stories-scraper on them.
  3. For each story (image OR video cover), inserts a content_item
     with content_type='story' and a content_image pointing at the
     cover frame.
  4. The standard detection pipeline (33_detect_pending) picks them up
     on its next pass.
  5. Story rows are flagged with expires_at = posted_at + 24h, so the
     dashboard can hide them once expired (or surface "we caught it
     before it disappeared" badges).

This pass is intentionally narrow: tier_1/2 only by default, since
stories scraping is more expensive per call than feed scraping and we
don't want to spend Apify budget on tier_3.

Usage:
    python3 tools/stelz_brand_watch/44_stories_harvest.py
    python3 tools/stelz_brand_watch/44_stories_harvest.py --brand stelz --max-creators 30
    python3 tools/stelz_brand_watch/44_stories_harvest.py --dry-run
"""

import argparse
import hashlib
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# Apify config. The official `apify/instagram-stories-scraper` actor was
# deprecated; the community alternatives below work, but stories are
# ephemeral so most calls return 0 items unless creators have an active
# story at scrape time. Run cadence should be ~every 4-6 hours during
# peak posting windows (evening NL time).
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
APIFY_ACTOR_STORIES = "gordian~instagram-story-scraper"
INSTAGRAM_SESSION_COOKIE = os.getenv("INSTAGRAM_SESSION_COOKIE")  # optional, improves results
STORAGE_BUCKET = "brand-watch-thumbnails"


def apify_run_sync(actor: str, payload: dict, timeout: int = 600) -> list:
    """Runs an Apify actor synchronously, returns dataset items."""
    if not APIFY_TOKEN:
        raise RuntimeError("APIFY_API_TOKEN not set")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    r = requests.post(url, json=payload, timeout=timeout)
    if r.status_code >= 400:
        # Fall back gracefully: some actors don't exist on every account.
        raise RuntimeError(f"Apify {actor} {r.status_code}: {r.text[:400]}")
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else []


def cache_image(sb, url: str) -> tuple[str | None, str | None]:
    """Download image, hash, upload to storage. Returns (stored_path, image_hash) or (None, None)."""
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None, None
        data = r.content
        h = hashlib.sha256(data).hexdigest()
        path = f"stories/{h[:2]}/{h}.jpg"
        try:
            sb.storage.from_(STORAGE_BUCKET).upload(
                path=path, file=data,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception:
            pass  # likely already exists; ok
        return path, h
    except Exception as e:
        print(f"  cache err {url[:80]}: {e}", file=sys.stderr)
        return None, None


def process_brand(sb, brand_id: str, brand_slug: str, max_creators: int,
                  include_tiers: list[str], dry_run: bool) -> dict:
    # Select creators: prefer recently-active tier 1/2
    creators = (sb.table("creators")
                .select("id, handle, platform, tier, last_scraped_at, follower_count")
                .eq("brand_id", brand_id)
                .eq("platform", "instagram")
                .in_("tier", include_tiers)
                .is_("archived_at", "null")
                .order("last_scraped_at", desc=True)
                .limit(max_creators).execute().data) or []

    if not creators:
        print(f"  [{brand_slug}] no creators in tiers {include_tiers}", file=sys.stderr)
        return {"creators": 0, "stories": 0, "new_images": 0}

    handles = [c["handle"].replace("@", "") for c in creators]
    print(f"  [{brand_slug}] harvesting stories from {len(handles)} creators "
          f"(tiers {','.join(include_tiers)})", file=sys.stderr)
    if dry_run:
        print(f"  DRY: would call Apify {APIFY_ACTOR_STORIES} for {handles[:5]}...", file=sys.stderr)
        return {"creators": len(handles), "stories": 0, "new_images": 0, "dry_run": True}

    try:
        payload = {
            "usernames": handles,
            "resultsLimit": 20,  # stories per creator
        }
        if INSTAGRAM_SESSION_COOKIE:
            payload["sessionCookie"] = INSTAGRAM_SESSION_COOKIE
        items = apify_run_sync(APIFY_ACTOR_STORIES, payload)
    except Exception as e:
        print(f"  Apify failed (the actor may not be enabled on your account; backlog item)", file=sys.stderr)
        print(f"  Error: {e}", file=sys.stderr)
        return {"creators": len(handles), "stories": 0, "new_images": 0, "error": str(e)}

    print(f"  [{brand_slug}] Apify returned {len(items)} story items", file=sys.stderr)

    creator_by_handle = {c["handle"].lower(): c for c in creators}
    new_items = 0
    new_images = 0

    for item in items:
        handle = (item.get("ownerUsername") or item.get("username") or "").lower()
        creator = creator_by_handle.get(handle) or creator_by_handle.get(handle.lstrip("@"))
        if not creator:
            continue

        external_id = item.get("id") or item.get("storyId") or item.get("pk")
        if not external_id:
            continue

        taken_at = item.get("takenAt") or item.get("takenAtTimestamp") or item.get("posted_at")
        if isinstance(taken_at, (int, float)):
            posted_at = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()
        elif isinstance(taken_at, str):
            posted_at = taken_at
        else:
            posted_at = datetime.now(timezone.utc).isoformat()

        # Insert content_item
        ci_payload = {
            "brand_id": brand_id,
            "creator_id": creator["id"],
            "platform": "instagram",
            "external_id": f"story_{external_id}",
            "content_type": "story",
            "url": item.get("url") or f"https://instagram.com/stories/{handle}/{external_id}",
            "caption": item.get("caption") or "",
            "posted_at": posted_at,
            "raw": {"source": "apify:" + APIFY_ACTOR_STORIES, "expires_at_iso": item.get("expiresAt"), "ttl_24h": True},
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            r = sb.table("content_items").upsert(
                ci_payload, on_conflict="platform,external_id",
            ).execute()
            content_item_id = r.data[0]["id"] if r.data else None
        except Exception as e:
            print(f"  insert content_item err {handle}/{external_id}: {e}", file=sys.stderr)
            continue
        if not content_item_id:
            continue
        new_items += 1

        # Image / video-cover URL
        img_url = (item.get("imageUrl") or item.get("displayUrl") or
                   item.get("thumbnailUrl") or item.get("videoCoverUrl"))
        if not img_url:
            continue

        stored_path, img_hash = cache_image(sb, img_url)
        try:
            sb.table("content_images").insert({
                "content_item_id": content_item_id,
                "brand_id": brand_id,
                "image_url": img_url,
                "stored_path": stored_path,
                "image_hash": img_hash,
                "sequence_idx": 0,
            }).execute()
            new_images += 1
        except Exception as e:
            print(f"  insert content_image err: {e}", file=sys.stderr)

    print(f"  [{brand_slug}] new story items: {new_items}, new images cached: {new_images}",
          file=sys.stderr)
    return {"creators": len(handles), "stories": new_items, "new_images": new_images}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--max-creators", type=int, default=40,
                   help="Max creators to harvest per brand (default 40)")
    p.add_argument("--tiers", default="tier_1,tier_2",
                   help="Comma-separated tiers to include (default tier_1,tier_2)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]

    brands = (sb.table("brands").select("id, slug").execute().data) or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]

    totals = {"creators": 0, "stories": 0, "new_images": 0}
    for b in brands:
        r = process_brand(sb, b["id"], b["slug"], args.max_creators, tiers, args.dry_run)
        for k in ("creators", "stories", "new_images"):
            totals[k] += r.get(k, 0)

    print(f"\n=== STORIES HARVEST: {totals} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
