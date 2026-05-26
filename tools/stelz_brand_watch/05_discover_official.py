#!/usr/bin/env python3
"""Discovery v3: pull followers, taggers, and engagers of @drinkstelz.

Three approaches in order of signal strength:
1. Followers of @drinkstelz (the brand's audience)
2. Users who tag/mention @drinkstelz in their posts
3. Users who comment on @drinkstelz posts

Followers may be rate-limited or require session cookie. Falls back gracefully.

Usage:
    python3 tools/stelz_brand_watch/05_discover_official.py
    python3 tools/stelz_brand_watch/05_discover_official.py --followers-limit 2000
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
OFFICIAL_HANDLE = "drinkstelz"
OFFICIAL_URL = f"https://www.instagram.com/{OFFICIAL_HANDLE}/"

ACTOR_PROFILE = "apify/instagram-profile-scraper"
ACTOR_FOLLOWERS = "apify/instagram-follower-scraper"
ACTOR_COMMENTS = "apify/instagram-comment-scraper"


def apify_run_sync(actor_id: str, run_input: dict, timeout: int = 300) -> list:
    if not APIFY_TOKEN:
        sys.exit("APIFY_API_TOKEN not set")
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()


def get_profile_and_posts() -> dict:
    print(f"Fetching profile + recent posts for @{OFFICIAL_HANDLE}...", file=sys.stderr)
    try:
        items = apify_run_sync(ACTOR_PROFILE, {
            "usernames": [OFFICIAL_HANDLE],
            "resultsLimit": 50,
        })
        if not items:
            return {}
        return items[0]
    except Exception as e:
        print(f"  profile fetch failed: {e}", file=sys.stderr)
        return {}


def get_followers(limit: int) -> list:
    print(f"Fetching followers of @{OFFICIAL_HANDLE} (limit {limit})...", file=sys.stderr)
    try:
        items = apify_run_sync(ACTOR_FOLLOWERS, {
            "usernames": [OFFICIAL_HANDLE],
            "resultsLimit": limit,
        }, timeout=600)
        print(f"  got {len(items)} followers", file=sys.stderr)
        return items
    except Exception as e:
        print(f"  follower fetch failed: {e}", file=sys.stderr)
        return []


def get_commenters(post_urls: list[str], per_post: int = 30) -> list:
    if not post_urls:
        return []
    print(f"Fetching commenters for {len(post_urls)} posts...", file=sys.stderr)
    try:
        items = apify_run_sync(ACTOR_COMMENTS, {
            "directUrls": post_urls[:30],
            "resultsLimit": per_post,
        }, timeout=300)
        print(f"  got {len(items)} comments", file=sys.stderr)
        return items
    except Exception as e:
        print(f"  comment fetch failed: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--followers-limit", type=int, default=2000)
    parser.add_argument("--skip-followers", action="store_true")
    parser.add_argument("--skip-comments", action="store_true")
    args = parser.parse_args()

    profile = get_profile_and_posts()
    follower_count = profile.get("followersCount")
    print(f"@{OFFICIAL_HANDLE}: {follower_count} total followers", file=sys.stderr)

    latest_posts = profile.get("latestPosts") or profile.get("posts") or []
    print(f"Recent posts fetched: {len(latest_posts)}", file=sys.stderr)

    candidates: dict = defaultdict(lambda: {
        "handle": None,
        "full_name": None,
        "source": set(),
        "is_verified": False,
        "is_private": False,
        "tagged_in_official_posts": 0,
        "commented_on_official_posts": 0,
    })

    # Source 1: followers
    if not args.skip_followers:
        followers = get_followers(args.followers_limit)
        for f in followers:
            handle = f.get("username") or f.get("ownerUsername")
            if not handle:
                continue
            c = candidates[handle]
            c["handle"] = handle
            c["full_name"] = c["full_name"] or f.get("fullName") or f.get("ownerFullName")
            c["source"].add("follower")
            c["is_verified"] = c["is_verified"] or bool(f.get("isVerified"))
            c["is_private"] = c["is_private"] or bool(f.get("isPrivate"))

    # Source 2: tagged users in official posts
    for post in latest_posts:
        for tag in (post.get("taggedUsers") or []):
            handle = tag.get("username")
            if not handle:
                continue
            c = candidates[handle]
            c["handle"] = handle
            c["full_name"] = c["full_name"] or tag.get("fullName")
            c["source"].add("tagged_by_official")
            c["tagged_in_official_posts"] += 1

    # Source 3: commenters on official posts
    if not args.skip_comments and latest_posts:
        post_urls = [p.get("url") for p in latest_posts if p.get("url")][:20]
        comments = get_commenters(post_urls, per_post=50)
        for cm in comments:
            handle = cm.get("ownerUsername")
            if not handle or handle == OFFICIAL_HANDLE:
                continue
            c = candidates[handle]
            c["handle"] = handle
            c["full_name"] = c["full_name"] or cm.get("ownerFullName")
            c["source"].add("commenter_on_official")
            c["commented_on_official_posts"] += 1

    print(f"\nUnique candidates: {len(candidates)}", file=sys.stderr)

    rows = []
    for handle, c in candidates.items():
        source = ",".join(sorted(c["source"]))
        signal = (
            (3 if "follower" in c["source"] else 0)
            + (5 if "tagged_by_official" in c["source"] else 0)
            + (2 if "commenter_on_official" in c["source"] else 0)
            + c["tagged_in_official_posts"] * 2
            + c["commented_on_official_posts"]
        )
        rows.append({
            "handle": handle,
            "full_name": c["full_name"] or "",
            "source": source,
            "signal_score": signal,
            "is_verified": c["is_verified"],
            "is_private": c["is_private"],
            "tagged_count": c["tagged_in_official_posts"],
            "comment_count": c["commented_on_official_posts"],
        })

    rows.sort(key=lambda r: r["signal_score"], reverse=True)

    csv_file = OUTPUT_DIR / "official_audience.csv"
    if rows:
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    by_source: dict = defaultdict(int)
    for r in rows:
        for s in r["source"].split(","):
            by_source[s] += 1

    print(f"\n=== OFFICIAL AUDIENCE SUMMARY ===", file=sys.stderr)
    print(f"Profile: @{OFFICIAL_HANDLE} ({follower_count} followers total)", file=sys.stderr)
    print(f"Total candidates: {len(rows)}", file=sys.stderr)
    print(f"By source: {dict(by_source)}", file=sys.stderr)
    print(f"\nTop 15 by signal:", file=sys.stderr)
    for r in rows[:15]:
        priv = " [private]" if r["is_private"] else ""
        ver = " [verified]" if r["is_verified"] else ""
        print(f"  @{r['handle']:<28} {r['full_name'][:30]:<30} score={r['signal_score']:<3} src={r['source']}{ver}{priv}", file=sys.stderr)
    print(f"\nWrote: {csv_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
