#!/usr/bin/env python3
"""Sprint B: scrape recente posts van ~60 bekende NL accounts in STELZ doelgroep.

Handpicked seed list van mainstream NL party/student/lifestyle/DJ/festival
Instagram accounts. Apify Profile Scraper haalt voor elk de recente 20 posts.

Niet-bestaande handles geven gewoon geen data terug, geen error.

Output gaat in Supabase. Detection volgt in separate pass.

Usage:
    python3 tools/stelz_brand_watch/13_popular_nl_creators.py
"""

import argparse
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR = "apify/instagram-profile-scraper"

# 60 handpicked NL accounts in STELZ target demographic (18-30, party/lifestyle/student)
# Sources: well-known NL Instagram in mainstream entertainment, DJ, festival, student content
HANDLES = [
    # Mainstream lifestyle/entertainment
    "monicageuze", "famkelouise", "annanooshin", "nikkietutorials", "liekevanlexmond",
    "jamielafleur", "yaramichels", "monaibrahim", "kim_kotter", "monique_smit",
    # DJs / Music
    "afrojack", "djsem.fficial", "djmaurice", "tiesto", "ferrycorsten",
    "armiinvanbuuren", "martingarrix", "hardwell", "nickyromero", "headhunterz",
    # Festival accounts
    "defqon1festival", "mysteryland_nl", "intentsfestival", "decibel_outdoor", "thunderdome_official",
    "pinkpopofficial", "lowlandsfestival", "extremamusic", "mysticgardenfestival", "amsterdamopenair",
    # Student / Young entertainment
    "joshhasit", "ronnieflex", "vinkenoog", "kuipertv", "demobshow",
    "vibegirl.xoxo", "festivalbabes_official", "tessmilne", "ferdiisme", "yara_michels",
    # Lifestyle / Vlogger
    "nikkiehofs", "annekephilipps", "janniebeck", "anouk.matton", "robinmartens",
    "bonnieelderhuis", "elles_devoogd", "saaraneellen", "evavanpelt", "anneneijenhuis",
    # Party / Going out (Amsterdam/Rotterdam scene)
    "supperclubcruise", "shelteramsterdam", "escapeamsterdam", "warehouseelementenstraat", "claire_amsterdam",
    "thuiscafenl", "feestjesinamsterdam", "uitgaaninamsterdam", "amsterdamnight", "uitinrotterdam",
]

# Tags to apply for these creators
CATEGORIES = {
    # Festival accounts
    "defqon1festival": "festival", "mysteryland_nl": "festival", "intentsfestival": "festival",
    "decibel_outdoor": "festival", "thunderdome_official": "festival", "pinkpopofficial": "festival",
    "lowlandsfestival": "festival", "extremamusic": "festival", "mysticgardenfestival": "festival",
    "amsterdamopenair": "festival",
}


def apify_run(handles_batch, timeout=400):
    url = f"https://api.apify.com/v2/acts/{ACTOR.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(
        url,
        json={"usernames": handles_batch, "resultsLimit": 20},
        params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024},
        timeout=timeout + 30,
    )
    r.raise_for_status()
    return r.json()


def main():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    print(f"Scraping {len(HANDLES)} popular NL accounts...", file=sys.stderr)

    all_items = []
    batch_size = 20
    for i in range(0, len(HANDLES), batch_size):
        batch = HANDLES[i:i+batch_size]
        print(f"  batch {i//batch_size + 1}: {len(batch)} handles", file=sys.stderr)
        t0 = time.time()
        try:
            items = apify_run(batch)
            print(f"    got {len(items)} items in {time.time()-t0:.1f}s", file=sys.stderr)
            all_items.extend(items)
        except Exception as e:
            print(f"    batch failed: {e}", file=sys.stderr)

    # Apify Profile Scraper returns one item per profile, with latestPosts inside.
    new_creators = 0
    new_content = 0
    new_images = 0
    found_handles = set()

    for profile in all_items:
        handle = profile.get("username") or profile.get("ownerUsername")
        if not handle:
            continue
        if profile.get("error"):
            continue
        found_handles.add(handle)
        full_name = profile.get("fullName")
        bio = profile.get("biography")
        followers = profile.get("followersCount")
        category = CATEGORIES.get(handle, "person")

        res = sb.table("creators").upsert({
            "brand_id": brand_id,
            "platform": "instagram",
            "handle": handle,
            "full_name": full_name,
            "bio": bio[:1000] if bio else None,
            "follower_count": followers,
            "category": category,
            "status": "discovered",
            "auto_added_via": "manual:popular_nl_seed",
        }, on_conflict="brand_id,platform,handle").execute()
        creator_id = res.data[0]["id"]
        new_creators += 1

        posts = profile.get("latestPosts") or []
        for post in posts:
            short = post.get("shortCode") or post.get("id")
            if not short:
                continue
            url = post.get("url") or f"https://www.instagram.com/p/{short}/"
            try:
                ci_res = sb.table("content_items").upsert({
                    "brand_id": brand_id,
                    "creator_id": creator_id,
                    "platform": "instagram",
                    "external_id": short,
                    "content_type": "reel" if post.get("type") == "Video" else "post",
                    "url": url,
                    "caption": (post.get("caption") or "")[:5000],
                    "hashtags": post.get("hashtags") or [],
                    "mentions": post.get("mentions") or [],
                    "posted_at": post.get("timestamp"),
                    "likes_count": post.get("likesCount"),
                    "comments_count": post.get("commentsCount"),
                    "views_count": post.get("videoPlayCount"),
                }, on_conflict="platform,external_id").execute()
                ci_id = ci_res.data[0]["id"]
                new_content += 1
            except Exception as e:
                print(f"  content upsert err {short}: {e}", file=sys.stderr)
                continue

            display_url = post.get("displayUrl")
            if not display_url:
                continue
            existing = sb.table("content_images").select("id").eq("content_item_id", ci_id).limit(1).execute()
            if not existing.data:
                sb.table("content_images").insert({
                    "content_item_id": ci_id,
                    "brand_id": brand_id,
                    "image_url": display_url,
                    "sequence_idx": 0,
                }).execute()
                new_images += 1

    missing = [h for h in HANDLES if h not in found_handles]
    print(f"\n=== POPULAR NL SUMMARY ===", file=sys.stderr)
    print(f"Handles requested: {len(HANDLES)}", file=sys.stderr)
    print(f"Profiles found: {len(found_handles)}", file=sys.stderr)
    print(f"Missing/error: {len(missing)}", file=sys.stderr)
    print(f"New/updated creators: {new_creators}", file=sys.stderr)
    print(f"New content items: {new_content}", file=sys.stderr)
    print(f"New images: {new_images}", file=sys.stderr)
    print(f"\nMissing handles: {missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
