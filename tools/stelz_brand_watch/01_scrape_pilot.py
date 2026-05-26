#!/usr/bin/env python3
"""Pilot: scrape Instagram posts under STELZ-related hashtags.

Pulls ~100 recent posts via the apify/instagram-hashtag-scraper actor,
writes a normalized JSON file and downloads the display images locally
for the vision pilot step.

Usage:
    python3 tools/stelz_brand_watch/01_scrape_pilot.py
    python3 tools/stelz_brand_watch/01_scrape_pilot.py --limit 100
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
IMAGES_DIR = OUTPUT_DIR / "images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_ID = "apify/instagram-hashtag-scraper"
HASHTAGS = ["stelz", "stelzhardseltzer", "stelzhardlemonade"]


def apify_run_sync(actor_id: str, run_input: dict, timeout: int = 180) -> list:
    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN not set")
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()


def download_image(url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    try:
        r = requests.get(url, timeout=30, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  image download failed: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Total posts to fetch across hashtags")
    args = parser.parse_args()

    per_tag = max(1, args.limit // len(HASHTAGS))
    print(f"Scraping {len(HASHTAGS)} hashtags, ~{per_tag} posts each", file=sys.stderr)

    all_items = []
    for tag in HASHTAGS:
        print(f"  #{tag}...", file=sys.stderr)
        try:
            items = apify_run_sync(ACTOR_ID, {
                "hashtags": [tag],
                "resultsLimit": per_tag,
            })
            print(f"    got {len(items)} posts", file=sys.stderr)
            for it in items:
                it["_hashtag"] = tag
            all_items.extend(items)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)

    seen = set()
    deduped = []
    for it in all_items:
        sc = it.get("shortCode") or it.get("id") or it.get("url")
        if not sc or sc in seen:
            continue
        seen.add(sc)
        deduped.append(it)
    print(f"After dedupe: {len(deduped)} unique posts", file=sys.stderr)

    normalized = []
    for it in deduped:
        short = it.get("shortCode") or it.get("id") or ""
        display_url = it.get("displayUrl") or ""
        post = {
            "shortCode": short,
            "url": it.get("url"),
            "ownerUsername": it.get("ownerUsername"),
            "caption": it.get("caption"),
            "hashtags": it.get("hashtags") or [],
            "mentions": it.get("mentions") or [],
            "likesCount": it.get("likesCount"),
            "commentsCount": it.get("commentsCount"),
            "timestamp": it.get("timestamp"),
            "displayUrl": display_url,
            "type": it.get("type"),
            "matched_hashtag": it.get("_hashtag"),
            "local_image": None,
        }
        if display_url and short:
            img_path = IMAGES_DIR / f"{short}.jpg"
            if download_image(display_url, img_path):
                post["local_image"] = str(img_path.relative_to(PA_ROOT))
            time.sleep(0.1)
        normalized.append(post)

    out_file = OUTPUT_DIR / "pilot_posts.json"
    out_file.write_text(json.dumps(normalized, ensure_ascii=False, indent=2))

    with_image = sum(1 for p in normalized if p["local_image"])
    print(f"\nWrote {len(normalized)} posts to {out_file}", file=sys.stderr)
    print(f"Downloaded {with_image} images to {IMAGES_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
