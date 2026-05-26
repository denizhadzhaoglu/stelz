#!/usr/bin/env python3
"""Brand-aware hashtag harvest.

Scrapes all active Instagram hashtags configured in `brand_hashtag_pools`
for a given brand (defaults to stelz for backwards compat). Up to N posts
per hashtag, deduped by shortCode, written into creators / content_items /
content_images. Detection runs in a second pass (`33_detect_pending.py`).

Brand-aware loop reads `brand_hashtag_pools WHERE active=true` ordered by
priority DESC. Falls back to the legacy STELZ hardcoded list if the table
returns nothing for the brand (safety net during migration).

Usage:
    # default — stelz
    python3 tools/stelz_brand_watch/12_full_stelz_harvest.py --per-tag 300

    # specific brand
    python3 tools/stelz_brand_watch/12_full_stelz_harvest.py --brand-slug=acme --per-tag 200

    # all active brands in one go (used by cron)
    python3 tools/stelz_brand_watch/12_full_stelz_harvest.py --all-brands --per-tag 200
"""

import argparse
import hashlib
import io
import os
import sys
import time
import re
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR = "apify/instagram-hashtag-scraper"

# Legacy fallback list — used only if a brand has zero rows in brand_hashtag_pools.
LEGACY_STELZ_HASHTAGS = [
    "stelz", "stelzhardseltzer", "stelzhardlemonade", "stelzhardicedtea",
    "stelzpeach", "stelzlime", "stelzmango", "stelzcassis",
    "stelznl", "drinkstelz",
]

BUSINESS_RE = re.compile(
    r"\b(cafe|caf[eé]|restaurant|bar |club|hotel|hostel|inn|pizza|sushi|frietzaak|"
    r"snackbar|grand cafe|stadscafe|borrelbar|schenkerij|slijterij|wijnhuis|"
    r"markt|winkel|supermarkt|albert heijn|jumbo|lidl|brouwerij|tap )",
    re.IGNORECASE,
)
STUDENT_RE = re.compile(r"\b(svosiris|svoikosnomos|ddvigeo|introweek|eurekaweek|uniwageningen|dispuut|sociëteit|societeit)", re.IGNORECASE)
FESTIVAL_RE = re.compile(r"\b(festival|kermis|tentfeest|koningsdag|zomerfeest|midzomer)", re.IGNORECASE)


def categorize(handle, full_name):
    text = " ".join(filter(None, [handle, full_name or ""])).lower()
    if STUDENT_RE.search(text): return "student_org"
    if FESTIVAL_RE.search(text): return "festival"
    if BUSINESS_RE.search(text): return "horeca"
    return "person"


def apify_run(input_dict, timeout=400):
    url = f"https://api.apify.com/v2/acts/{ACTOR.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(url, json=input_dict, params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}, timeout=timeout+30)
    r.raise_for_status()
    return r.json()


def fetch_hashtags_for_brand(sb, brand_id: str, brand_slug: str) -> list[str]:
    rows = (sb.table("brand_hashtag_pools")
            .select("hashtag, priority")
            .eq("brand_id", brand_id)
            .eq("active", True)
            .eq("platform", "instagram")
            .order("priority", desc=True)
            .execute()).data or []
    tags = [r["hashtag"] for r in rows if r.get("hashtag")]
    if tags:
        return tags
    # Fallback: only the original stelz pilot had hardcoded tags.
    if brand_slug == "stelz":
        print(f"  WARN: no brand_hashtag_pools rows for stelz, falling back to legacy list", file=sys.stderr)
        return LEGACY_STELZ_HASHTAGS
    print(f"  no hashtags configured for {brand_slug}, skipping", file=sys.stderr)
    return []


def harvest_brand(sb, brand_id: str, brand_slug: str, per_tag: int, auto_added_via: str) -> dict:
    """Harvest all configured hashtags for one brand. Returns summary dict."""
    hashtags = fetch_hashtags_for_brand(sb, brand_id, brand_slug)
    if not hashtags:
        return {"brand": brand_slug, "hashtags": 0, "posts": 0, "creators": 0, "images": 0}

    all_posts = []
    for tag in hashtags:
        print(f"  [{brand_slug}] #{tag} (limit {per_tag})...", file=sys.stderr)
        t0 = time.time()
        try:
            items = apify_run({"hashtags": [tag], "resultsLimit": per_tag})
            print(f"    {len(items)} posts in {time.time()-t0:.1f}s", file=sys.stderr)
            for it in items:
                it["_hashtag"] = tag
            all_posts.extend(items)
        except Exception as e:
            print(f"    ERROR: {e}", file=sys.stderr)

    # Dedupe by shortCode
    seen = set()
    unique = []
    for p_ in all_posts:
        sc = p_.get("shortCode") or p_.get("id")
        if not sc or sc in seen: continue
        seen.add(sc)
        unique.append(p_)
    print(f"  [{brand_slug}] {len(unique)} unique posts harvested", file=sys.stderr)

    creators_seen = {}
    new_creators = 0
    new_content = 0
    new_images = 0

    for post in unique:
        handle = post.get("ownerUsername")
        if not handle:
            continue
        full_name = post.get("ownerFullName")

        if handle not in creators_seen:
            cat = categorize(handle, full_name)
            res = sb.table("creators").upsert({
                "brand_id": brand_id,
                "platform": "instagram",
                "handle": handle,
                "full_name": full_name,
                "category": cat,
                "status": "discovered",
                "auto_added_via": auto_added_via,
            }, on_conflict="brand_id,platform,handle").execute()
            creators_seen[handle] = res.data[0]["id"]
            new_creators += 1

        creator_id = creators_seen[handle]
        short = post.get("shortCode") or post.get("id")
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
            content_item_id = ci_res.data[0]["id"]
            new_content += 1
        except Exception as e:
            print(f"  content upsert failed for {short}: {e}", file=sys.stderr)
            continue

        # Apify schema varies by post type. Carousel posts often have
        # `displayUrl` empty at the top level and the real images live in
        # `images[]` or `childPosts[].displayUrl`. Reels often hand back
        # only `videoUrl`+`videoCoverUrl`. Walk the candidates so we never
        # silently drop a post from the detection pipeline.
        image_urls: list[str] = []
        for key in ("displayUrl", "imageUrl", "thumbnailUrl"):
            v = post.get(key)
            if isinstance(v, str) and v:
                image_urls.append(v)
        # Carousels: a list of image URLs
        for v in (post.get("images") or []):
            if isinstance(v, str) and v:
                image_urls.append(v)
            elif isinstance(v, dict):
                u = v.get("url") or v.get("displayUrl") or v.get("imageUrl")
                if u:
                    image_urls.append(u)
        # Children of a Sidecar post
        for child in (post.get("childPosts") or []):
            u = child.get("displayUrl") or child.get("imageUrl")
            if u:
                image_urls.append(u)
        # Reels / videos: fall back to cover image
        vm = post.get("videoMeta") or {}
        for u in (vm.get("coverUrl"), post.get("videoCoverUrl"), post.get("cover")):
            if isinstance(u, str) and u:
                image_urls.append(u)

        # Dedupe while preserving order
        seen_urls = set()
        ordered_urls = []
        for u in image_urls:
            if u and u not in seen_urls:
                seen_urls.add(u)
                ordered_urls.append(u)

        if not ordered_urls:
            print(f"  WARN: no image url for {short} (type={post.get('type')})", file=sys.stderr)
            continue

        for idx, url_i in enumerate(ordered_urls[:5]):  # cap at 5 images per post
            # Download + cache to Storage NOW. IG/TikTok CDN URLs expire in
            # ~24h. If we wait for detect_pending to fetch later the URL is
            # often dead. Downloading at scrape time guarantees we always
            # have stored_path before the URL rots.
            stored_path = None
            image_hash = None
            try:
                resp = requests.get(url_i, timeout=15)
                if resp.ok and resp.content:
                    data = resp.content
                    image_hash = hashlib.sha256(data).hexdigest()
                    stored_path = f"{brand_slug}/{image_hash[:2]}/{image_hash}.jpg"
                    try:
                        sb.storage.from_("brand-watch-thumbnails").upload(
                            path=stored_path, file=data,
                            file_options={"content-type": "image/jpeg", "upsert": "true"},
                        )
                    except Exception as e:
                        # Already exists or transient upload error — non-fatal.
                        msg = str(e).lower()
                        if "duplicate" not in msg and "exists" not in msg and "already" not in msg:
                            print(f"  storage upload err for {short}/{idx}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  image fetch err for {short}/{idx}: {str(e)[:100]}", file=sys.stderr)

            # Dedup BY IMAGE_HASH (not image_url — IG/TikTok CDN URLs rotate
            # per scrape so URL-based dedup misses true duplicates).
            # The unique partial index on (content_item_id, image_hash) is
            # a DB-level guard; this check just avoids a wasted INSERT round-trip.
            if image_hash:
                existing = (sb.table("content_images")
                              .select("id")
                              .eq("content_item_id", content_item_id)
                              .eq("image_hash", image_hash)
                              .limit(1)
                              .execute())
                if existing.data:
                    continue
            else:
                # No hash (download failed) — fall back to URL-based dedup.
                existing = (sb.table("content_images")
                              .select("id")
                              .eq("content_item_id", content_item_id)
                              .eq("image_url", url_i)
                              .limit(1)
                              .execute())
                if existing.data:
                    continue

            try:
                sb.table("content_images").insert({
                    "content_item_id": content_item_id,
                    "brand_id": brand_id,
                    "image_url": url_i,
                    "sequence_idx": idx,
                    "stored_path": stored_path,
                    "image_hash": image_hash,
                }).execute()
                new_images += 1
            except Exception as e:
                # Catch the unique-index violation: race-condition between
                # our existence check and the INSERT. Non-fatal.
                msg = str(e).lower()
                if "duplicate" in msg or "unique" in msg or "23505" in msg:
                    continue
                print(f"  image insert err for {short}/{idx}: {str(e)[:100]}", file=sys.stderr)

    return {
        "brand": brand_slug,
        "hashtags": len(hashtags),
        "posts": len(unique),
        "creators": new_creators,
        "content": new_content,
        "images": new_images,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-tag", type=int, default=300)
    p.add_argument("--brand-slug", default="stelz")
    p.add_argument("--all-brands", action="store_true",
                   help="Harvest hashtags for all active brands (cron usage)")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.all_brands:
        brands = sb.table("brands").select("id, slug").eq("active", True).execute().data or []
    else:
        b = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).maybe_single().execute().data
        if not b:
            sys.exit(f"brand {args.brand_slug} not found")
        brands = [b]

    print(f"Harvesting hashtags for {len(brands)} brand(s)", file=sys.stderr)
    summaries = []
    for b in brands:
        summary = harvest_brand(sb, b["id"], b["slug"], args.per_tag,
                                auto_added_via=f"hashtag_harvest:{b['slug']}")
        summaries.append(summary)

    print(f"\n=== HARVEST SUMMARY ===", file=sys.stderr)
    for s in summaries:
        print(f"  {s['brand']:<22} hashtags={s['hashtags']:<3} posts={s['posts']:<5} "
              f"creators+={s.get('creators',0):<3} images+={s.get('images',0):<4}", file=sys.stderr)


if __name__ == "__main__":
    main()
