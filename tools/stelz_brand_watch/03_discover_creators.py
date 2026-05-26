#!/usr/bin/env python3
"""Discovery: build a seed list of Dutch STELZ creators.

Scrapes a wider hashtag net plus the official @stelz account followers/mentions,
aggregates by creator, and auto-categorizes each handle (retail/horeca,
individual creator, brand/business, media, unknown).

Outputs a ranked CSV ready for manual curation.

Usage:
    python3 tools/stelz_brand_watch/03_discover_creators.py
    python3 tools/stelz_brand_watch/03_discover_creators.py --posts-per-tag 200
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_HASHTAG = "apify/instagram-hashtag-scraper"

HASHTAGS = [
    "stelz",
    "stelzhardseltzer",
    "stelzhardlemonade",
    "stelzhardicedtea",
    "stelzcassis",
    "stelzpeach",
    "stelzlime",
    "stelzmango",
]

# Heuristics for auto-categorization
RETAIL_KEYWORDS = [
    "albert heijn", "ah ", "jumbo", "lidl", "dirk", "plus", "spar", "aldi",
    "coop", "vomar", "slijterij", "slijter", "winkel", "supermarkt", "deals",
    "korting", "aanbieding", "prospekt", "flyer", "wijnhuis",
]
HORECA_KEYWORDS = [
    "cafe ", "café", "restaurant", "bar ", "kroeg", "snackbar", "frietzaak",
    "lounge", "club", "kantine", "bistro", "brouwerij", "tap", "grandcafe",
    "grand cafe", "eetbar", "borrel", "feest", "tentfeest", "kermis",
    "uitgaansgelegenheid", "discotheek", "nightlife", "bowling", "beach club",
    "festival",
]
MEDIA_KEYWORDS = ["nieuws", "rtl", "nos", "ad ", "telegraaf", "blog", "magazine"]
BRAND_KEYWORDS = ["official", "brand", "company", "bv ", " bv", "merk"]


def apify_run_sync(actor_id: str, run_input: dict, timeout: int = 240) -> list:
    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN not set")
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()


def categorize(handle: str, bio: str | None, full_name: str | None) -> str:
    text = " ".join(filter(None, [handle, bio, full_name])).lower()
    for kw in RETAIL_KEYWORDS:
        if kw in text:
            return "retail"
    for kw in HORECA_KEYWORDS:
        if kw in text:
            return "horeca"
    for kw in MEDIA_KEYWORDS:
        if kw in text:
            return "media"
    for kw in BRAND_KEYWORDS:
        if kw in text:
            return "brand"
    if handle.lower() in {"stelz", "stelzhardseltzer"}:
        return "official"
    return "individual_or_unknown"


def nl_signal(caption: str | None, bio: str | None) -> bool:
    nl_words = ["bier", "borrel", "lekker", "gezellig", "geweldig", "vriend",
                "kroeg", "feest", "weekend", "morgen", "zaterdag", "vrijdag",
                "vandaag", "binnenkort", "proost", "ijskoud", "smaak", "blik"]
    text = " ".join(filter(None, [caption or "", bio or ""])).lower()
    return any(w in text for w in nl_words)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--posts-per-tag", type=int, default=150)
    args = parser.parse_args()

    print(f"Discovering creators across {len(HASHTAGS)} hashtags, {args.posts_per_tag} per tag", file=sys.stderr)

    all_posts = []
    for tag in HASHTAGS:
        print(f"  #{tag}...", file=sys.stderr)
        try:
            items = apify_run_sync(ACTOR_HASHTAG, {
                "hashtags": [tag],
                "resultsLimit": args.posts_per_tag,
            })
            print(f"    {len(items)} posts", file=sys.stderr)
            for it in items:
                it["_hashtag"] = tag
            all_posts.extend(items)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)

    raw_file = OUTPUT_DIR / "discovery_raw_posts.json"
    raw_file.write_text(json.dumps(all_posts, ensure_ascii=False, indent=2))
    print(f"Saved {len(all_posts)} raw posts -> {raw_file}", file=sys.stderr)

    # Aggregate per creator
    creators: dict = defaultdict(lambda: {
        "handle": None,
        "platform": "instagram",
        "full_name": None,
        "bio": None,
        "post_count": 0,
        "hashtags_seen": set(),
        "first_seen": None,
        "last_seen": None,
        "total_likes": 0,
        "total_comments": 0,
        "sample_urls": [],
        "sample_captions": [],
        "owner_id": None,
        "is_verified": False,
        "nl_hits": 0,
    })

    for p in all_posts:
        handle = p.get("ownerUsername")
        if not handle:
            continue
        c = creators[handle]
        c["handle"] = handle
        c["full_name"] = c["full_name"] or p.get("ownerFullName")
        c["owner_id"] = c["owner_id"] or p.get("ownerId")
        c["post_count"] += 1
        c["hashtags_seen"].add(p["_hashtag"])
        ts = p.get("timestamp")
        if ts:
            if not c["first_seen"] or ts < c["first_seen"]:
                c["first_seen"] = ts
            if not c["last_seen"] or ts > c["last_seen"]:
                c["last_seen"] = ts
        c["total_likes"] += p.get("likesCount") or 0
        c["total_comments"] += p.get("commentsCount") or 0
        if len(c["sample_urls"]) < 3 and p.get("url"):
            c["sample_urls"].append(p["url"])
        cap = p.get("caption") or ""
        if cap and len(c["sample_captions"]) < 2:
            c["sample_captions"].append(cap[:150])
        if nl_signal(cap, None):
            c["nl_hits"] += 1

    print(f"\nUnique creators: {len(creators)}", file=sys.stderr)

    # Categorize and rank
    rows = []
    for handle, c in creators.items():
        cat = categorize(handle, c["bio"], c["full_name"])
        rows.append({
            "handle": handle,
            "platform": "instagram",
            "category": cat,
            "post_count": c["post_count"],
            "hashtags_count": len(c["hashtags_seen"]),
            "hashtags_seen": ",".join(sorted(c["hashtags_seen"])),
            "first_seen": c["first_seen"],
            "last_seen": c["last_seen"],
            "total_likes": c["total_likes"],
            "total_comments": c["total_comments"],
            "avg_engagement": round((c["total_likes"] + c["total_comments"]) / max(c["post_count"], 1), 1),
            "nl_signal_hits": c["nl_hits"],
            "full_name": c["full_name"] or "",
            "sample_url_1": c["sample_urls"][0] if c["sample_urls"] else "",
            "sample_url_2": c["sample_urls"][1] if len(c["sample_urls"]) > 1 else "",
            "sample_caption_1": c["sample_captions"][0] if c["sample_captions"] else "",
        })

    # Rank: more posts + more hashtags + more engagement = higher
    rows.sort(key=lambda r: (r["post_count"], r["hashtags_count"], r["avg_engagement"]), reverse=True)

    csv_file = OUTPUT_DIR / "discovery_creators.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    by_cat: dict = defaultdict(int)
    for r in rows:
        by_cat[r["category"]] += 1
    print(f"\n=== DISCOVERY SUMMARY ===", file=sys.stderr)
    print(f"Total creators: {len(rows)}", file=sys.stderr)
    print(f"By category:", file=sys.stderr)
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}", file=sys.stderr)
    print(f"\nTop 10 by post count:", file=sys.stderr)
    for r in rows[:10]:
        print(f"  {r['handle']:<35} {r['category']:<25} posts={r['post_count']} hashtags={r['hashtags_count']} eng={r['avg_engagement']}", file=sys.stderr)
    print(f"\nWrote: {csv_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
