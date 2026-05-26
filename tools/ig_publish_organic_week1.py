"""Publish @spotyourbrand week-1 organic posts via Instagram Graph API.

PREREQUISITES (must all be true before this works):
  1. @spotyourbrand is a Business or Creator account                 ✓ done today
  2. @spotyourbrand is linked to a Facebook Page in Business Manager — TODO
  3. The Facebook Page is owned by Meinte's Business Manager         — TODO
  4. A long-lived access token with these scopes exists in .env:
     - instagram_basic
     - instagram_content_publish
     - pages_read_engagement
     - pages_show_list
     Store as IG_ACCESS_TOKEN
  5. The IG Business Account ID is in .env as IG_USER_ID

How to get token + IG_USER_ID:
  - https://developers.facebook.com/tools/explorer/ → select your app, grant
    the scopes above, generate a User Access Token → exchange for long-lived
    via /oauth/access_token
  - GET /me/accounts → list pages → find Spot the Brand page ID
  - GET /<page_id>?fields=instagram_business_account → returns IG_USER_ID
  - Add IG_ACCESS_TOKEN + IG_USER_ID to .env

USAGE:
  python tools/ig_publish_organic_week1.py --dry-run   # plan only
  python tools/ig_publish_organic_week1.py --publish   # actually post
  python tools/ig_publish_organic_week1.py --only carousel
  python tools/ig_publish_organic_week1.py --only grid-manifesto

Posts handled:
  - Tuesday carousel (6 images, single carousel post)
  - 5 grid filler single-image posts
  - Thursday quote card single-image post

NOT handled (yet):
  - Stories with poll/link stickers (Graph API supports media stories but not
    interactive stickers; do those manually on phone)
  - Reels (need video files from Lukas)

Rate limit: 25 publishes per 24h. We're well under.
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
import requests
from dotenv import load_dotenv

load_dotenv()

GRAPH = "https://graph.facebook.com/v21.0"
IG_USER_ID = os.environ.get("IG_USER_ID")
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN")

URLS_FILE = Path(__file__).resolve().parent.parent / "projects" / "spot-the-brand" / "assets" / "ig-week1" / "organic" / "PUBLIC_URLS.json"
PUBLIC_URLS = json.loads(URLS_FILE.read_text())


# ---------- Captions ---------- #

CAPTIONS = {
    "tuesday_carousel": (
        "Quick audit: how much of your brand's social mentions does your tracking tool actually see?\n\n"
        "Most teams guess 80% or more. The measured number is closer to 20%. The other 80% is in pixels, not text.\n\n"
        "Six slides on why this is breaking your brand monitoring. Save if you've ever wondered what your real social footprint looks like.\n\n"
        "#brandmonitoring #martech #marketingnl #computervision"
    ),
    "grid-stat-split.png": (
        "The gap between what your monitoring tool sees and what your audience sees.\n\n"
        "20% sits in text. 80% sits in pixels: someone's hand at a festival, a kitchen shelf in a vlog, a half-second flash in a reel.\n\n"
        "Most brand teams find out the hard way when a creator goes viral with their product and they only catch it from the screenshot a colleague sends them three days later.\n\n"
        "Daily visual brand monitoring → spotyourbrand.com\n\n"
        "#brandmonitoring #martech #marketingnl"
    ),
    "grid-manifesto.png": (
        "Brands don't live in hashtags. They live in pixels.\n\n"
        "They live in someone's hand at a festival, on a shelf in a YouTube kitchen, in the half-second flash of a TikTok where the product is the punchline but never named.\n\n"
        "Spot the Brand finds all of them. Computer vision for brand monitoring.\n\n"
        "spotyourbrand.com\n\n"
        "#brandnl #martech #brandmonitoring"
    ),
    "grid-definition.png": (
        "The 80% of your brand's mentions your tool can't see because they have no hashtag, no @mention, just your product in someone's frame.\n\n"
        "That's the blind spot. We close it.\n\n"
        "#brandmonitoring #marketingnl #martech"
    ),
    "grid-detection-demo.png": (
        "A real detection from our pilot last week. Zero hashtags. Zero @mentions. Just a product in a creator's hand in a half-second cut.\n\n"
        "Their old tool missed it. Spot the Brand didn't.\n\n"
        "Computer vision scans Instagram and TikTok every 24h for your product in the actual image. First detections within 24 hours of going live on your brand.\n\n"
        "Try it → spotyourbrand.com\n\n"
        "#brandmonitoring #martech #computervision #marketingnl"
    ),
    "grid-principle.png": (
        "Principle 001 from how we built Spot the Brand.\n\n"
        "If your monitoring tool can't see something, your reports tell you it didn't happen. Your strategy meetings discuss a brand that doesn't exist. Your spend goes to the audiences who already mention you in text, not the much bigger audience who shows your product without ever naming it.\n\n"
        "We built Spot the Brand because the brand we love most was disappearing from our own dashboards.\n\n"
        "spotyourbrand.com\n\n"
        "#brandmonitoring #martech #marketingnl"
    ),
    "thu-static-quote.png": (
        "Brands don't live in hashtags. They live in pixels. They live in someone's hand at a festival, on a shelf in the kitchen of a YouTube video, in the half-second flash of a TikTok where the product is the punchline but never named.\n\n"
        "Spot the Brand finds all of them.\n\n"
        "Visual brand monitoring for the way people post in 2026."
    ),
}


# ---------- Graph API helpers ---------- #

def _check_credentials():
    if not IG_USER_ID or not IG_TOKEN:
        sys.exit(
            "Missing IG_USER_ID and/or IG_ACCESS_TOKEN in .env.\n"
            "See header comment for how to obtain them."
        )


def _create_image_container(image_url, caption=None, is_carousel_item=False):
    params = {
        "image_url": image_url,
        "access_token": IG_TOKEN,
    }
    if caption and not is_carousel_item:
        params["caption"] = caption
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    r = requests.post(f"{GRAPH}/{IG_USER_ID}/media", data=params, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _create_carousel_container(child_ids, caption):
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": IG_TOKEN,
    }
    r = requests.post(f"{GRAPH}/{IG_USER_ID}/media", data=params, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _publish_container(creation_id):
    params = {
        "creation_id": creation_id,
        "access_token": IG_TOKEN,
    }
    r = requests.post(f"{GRAPH}/{IG_USER_ID}/media_publish", data=params, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _wait_until_ready(container_id, max_wait_s=90):
    """Poll container status until FINISHED or timeout."""
    for _ in range(max_wait_s // 2):
        r = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code", "access_token": IG_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        status = r.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container {container_id} failed: {r.json()}")
        time.sleep(2)
    raise TimeoutError(f"Container {container_id} not ready within {max_wait_s}s")


# ---------- Publishing flows ---------- #

def publish_single(file_key, dry_run=True):
    url = PUBLIC_URLS[file_key]
    caption = CAPTIONS[file_key]
    print(f"\n[single] {file_key}")
    print(f"  image: {url}")
    print(f"  caption ({len(caption)} chars): {caption[:80]}…")
    if dry_run:
        return None
    _check_credentials()
    cid = _create_image_container(url, caption=caption)
    print(f"  container: {cid} — waiting for IG to fetch image…")
    _wait_until_ready(cid)
    post_id = _publish_container(cid)
    print(f"  ✅ published: post_id={post_id}")
    return post_id


def publish_carousel(file_keys, caption_key, dry_run=True):
    print(f"\n[carousel] {len(file_keys)} slides under '{caption_key}'")
    for fk in file_keys:
        print(f"  - {fk}: {PUBLIC_URLS[fk]}")
    caption = CAPTIONS[caption_key]
    print(f"  caption ({len(caption)} chars): {caption[:80]}…")
    if dry_run:
        return None
    _check_credentials()
    child_ids = []
    for fk in file_keys:
        cid = _create_image_container(PUBLIC_URLS[fk], is_carousel_item=True)
        print(f"  child {fk} → {cid}")
        _wait_until_ready(cid)
        child_ids.append(cid)
    carousel_cid = _create_carousel_container(child_ids, caption=caption)
    print(f"  carousel container: {carousel_cid}")
    _wait_until_ready(carousel_cid)
    post_id = _publish_container(carousel_cid)
    print(f"  ✅ published: post_id={post_id}")
    return post_id


# ---------- Schedule definition ---------- #

PLAN = [
    {
        "id": "carousel-blind-spot",
        "type": "carousel",
        "caption_key": "tuesday_carousel",
        "files": [
            "tue-carousel-01.png",
            "tue-carousel-02.png",
            "tue-carousel-03.png",
            "tue-carousel-04.png",
            "tue-carousel-05.png",
            "tue-carousel-06.png",
        ],
    },
    {"id": "grid-manifesto", "type": "single", "file": "grid-manifesto.png"},
    {"id": "grid-stat-split", "type": "single", "file": "grid-stat-split.png"},
    {"id": "grid-detection-demo", "type": "single", "file": "grid-detection-demo.png"},
    {"id": "grid-definition", "type": "single", "file": "grid-definition.png"},
    {"id": "grid-principle", "type": "single", "file": "grid-principle.png"},
    {"id": "thu-static-quote", "type": "single", "file": "thu-static-quote.png"},
]


def run(only=None, dry_run=True):
    for entry in PLAN:
        if only and entry["id"] != only:
            continue
        if entry["type"] == "carousel":
            publish_carousel(entry["files"], entry["caption_key"], dry_run=dry_run)
        else:
            publish_single(entry["file"], dry_run=dry_run)
    if dry_run:
        print("\n(dry run) Add --publish to actually post.")


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--publish", action="store_true")
    p.add_argument("--only", help="Only publish the entry with this id (see PLAN)")
    args = p.parse_args()
    run(only=args.only, dry_run=not args.publish)


if __name__ == "__main__":
    main()
