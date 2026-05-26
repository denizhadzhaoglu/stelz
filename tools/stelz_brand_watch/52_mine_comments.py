#!/usr/bin/env python3
"""52_mine_comments.py — Mine comment authors from tier_1/tier_2 hit-posts.

POST-APIFY VERSION (2026-05-26). Replaces Apify instagram-comment-scraper with
instagrapi (open-source Python lib, free, mobile-API wrapper). Login via
IG_SESSION_ID cookie. Battle-tested handling of csrf/device/auth state that
the raw mobile API endpoint refused with our session.

Weekly job that:
  1. Picks the top N highest-comment-count posts from creators in tier_1/tier_2
     that ALSO have a confirmed STELZ visual hit.
  2. For each post: shortcode → media_id → comments via instagrapi.
  3. Stores comment authors as creator_edges rows with edge_type='comment',
     weight = comment_count_for_that_author_on_that_post.

Cost: €0. Rate-limited (1-3s delay between calls) to stay under IG's radar.
Used by: 53_compute_resonance.py CommentEngagement layer.

Usage:
    python3 tools/stelz_brand_watch/52_mine_comments.py
    python3 tools/stelz_brand_watch/52_mine_comments.py --brand stelz --top-posts 50
    python3 tools/stelz_brand_watch/52_mine_comments.py --min-comment-count 20 --dry-run
"""

import argparse
import os
import re
import sys
import time
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# instagrapi
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ClientError, MediaNotFound

IG_SESSION_ID = os.getenv("IG_SESSION_ID")

# Reuse handle-quality logic
BRAND_OWNED = {"drinkstelz", "stelz", "stelz_official", "stelz.official", "stelz_int", "spotyourbrand"}
HANDLE_OK = re.compile(r"^[a-zA-Z0-9_.]{2,30}$")
DOMAIN_LIKE = re.compile(r"\.(com|nl|org|net|io|co|de|be|fr|uk|info|biz|app|tv|me)$")
MULTI_DOT = re.compile(r"\.[a-z]{2,}\.")


def normalize_handle(h: str) -> str:
    return (h or "").strip().lstrip("@").lower()


def is_real_handle(h: str) -> bool:
    if not h or not HANDLE_OK.match(h): return False
    if h in BRAND_OWNED: return False
    if DOMAIN_LIKE.search(h): return False
    if MULTI_DOT.search(h): return False
    if h.isdigit(): return False
    return True


def make_ig_client():
    """Returns an authenticated instagrapi Client."""
    if not IG_SESSION_ID:
        sys.exit("IG_SESSION_ID missing — set in .env (extract sessionid cookie from instagram.com)")
    cl = Client()
    cl.delay_range = [1, 3]  # random 1-3 s delay between requests, mimicking human pacing
    try:
        cl.login_by_sessionid(IG_SESSION_ID)
        me = cl.account_info()
        print(f"  logged in as @{me.username}", file=sys.stderr)
        return cl
    except (LoginRequired, ClientError) as e:
        sys.exit(f"login failed: {e}")


def fetch_comments_for_post(cl: Client, shortcode: str, max_comments: int = 100):
    """Returns list of comment dicts: {handle, text, likes}."""
    try:
        media_id = cl.media_pk_from_code(shortcode)
    except Exception as e:
        print(f"    media_pk lookup err: {str(e)[:80]}", file=sys.stderr)
        return []
    try:
        # instagrapi handles pagination internally up to amount
        comments = cl.media_comments(media_id, amount=max_comments)
        out = []
        for c in comments:
            out.append({
                "handle": getattr(c.user, "username", ""),
                "text": c.text or "",
                "likes": int(c.like_count or 0),
            })
        return out
    except MediaNotFound:
        print(f"    media not found / private", file=sys.stderr)
        return []
    except Exception as e:
        print(f"    comments fetch err: {str(e)[:100]}", file=sys.stderr)
        return []


def pick_hit_posts(sb, brand_id, top_posts, min_comment_count):
    """Top N posts to mine = posts owned by tier_1/tier_2 creators that have
    a confirmed STELZ visual hit, sorted by comments_count desc.
    IG only (TikTok comments are handled separately; instagrapi is IG-only)."""
    tiered = (sb.table("creators")
              .select("id, handle, platform")
              .eq("brand_id", brand_id)
              .in_("tier", ["tier_1", "tier_2"])
              .eq("platform", "instagram")
              .neq("status", "rejected")
              .execute()).data or []
    tier_ids = [c["id"] for c in tiered]
    tier_meta = {c["id"]: c for c in tiered}
    if not tier_ids:
        return []

    items = []
    for i in range(0, len(tier_ids), 200):
        r = (sb.table("content_items")
             .select("id, creator_id, url, platform, external_id, comments_count, likes_count, posted_at")
             .eq("brand_id", brand_id)
             .eq("platform", "instagram")
             .in_("creator_id", tier_ids[i:i+200])
             .gte("comments_count", min_comment_count)
             .order("comments_count", desc=True)
             .limit(500)
             .execute()).data or []
        items.extend(r)
    if not items:
        return []

    item_ids = [it["id"] for it in items]
    hit_item_ids = set()
    for i in range(0, len(item_ids), 200):
        imgs = (sb.table("content_images")
                .select("id, content_item_id")
                .in_("content_item_id", item_ids[i:i+200])
                .execute()).data or []
        img_to_item = {im["id"]: im["content_item_id"] for im in imgs}
        if not imgs: continue
        img_ids = list(img_to_item.keys())
        for j in range(0, len(img_ids), 200):
            dets = (sb.table("detections")
                    .select("content_image_id, detected, is_false_positive, confidence")
                    .eq("brand_id", brand_id)
                    .eq("detected", True)
                    .gte("confidence", 0.5)
                    .in_("content_image_id", img_ids[j:j+200])
                    .execute()).data or []
            for d in dets:
                if d.get("is_false_positive"): continue
                hit_item_ids.add(img_to_item.get(d["content_image_id"]))

    hit_items = [it for it in items if it["id"] in hit_item_ids]
    hit_items.sort(key=lambda x: x.get("comments_count") or 0, reverse=True)
    selected = hit_items[:top_posts]
    for it in selected:
        it["_creator_meta"] = tier_meta.get(it["creator_id"])
    return selected


def process_brand(sb, brand_id, brand_slug, top_posts, min_comment_count, max_per_post, dry_run):
    posts = pick_hit_posts(sb, brand_id, top_posts, min_comment_count)
    print(f"\n[{brand_slug}] {len(posts)} IG hit-posts to mine "
          f"(tier_1/2 + comments>={min_comment_count} + has visual hit)", file=sys.stderr)
    if not posts:
        return 0

    if dry_run:
        for idx, p in enumerate(posts[:10], 1):
            print(f"  [{idx}] {p.get('external_id')} (cc={p.get('comments_count')}, likes={p.get('likes_count')})", file=sys.stderr)
        return 0

    cl = make_ig_client()
    edge_weights = defaultdict(int)
    total_comments = 0

    for idx, p in enumerate(posts, 1):
        short = p.get("external_id")
        post_url = p.get("url") or f"https://www.instagram.com/p/{short}/"
        print(f"  [{idx}/{len(posts)}] {short} (cc={p.get('comments_count')}, likes={p.get('likes_count')})", file=sys.stderr)
        comments = fetch_comments_for_post(cl, short, max_comments=max_per_post)
        print(f"    +{len(comments)} comments", file=sys.stderr)
        total_comments += len(comments)
        src = p["creator_id"]
        seen_for_post = set()
        for c in comments:
            handle = normalize_handle(c.get("handle", ""))
            if not is_real_handle(handle): continue
            if (src, handle) in seen_for_post: continue
            seen_for_post.add((src, handle))
            edge_weights[(src, "instagram", handle)] += 1
        # Small inter-post pause beyond instagrapi's per-request delay
        time.sleep(random.uniform(2, 5))

    print(f"\n  total comments fetched: {total_comments}", file=sys.stderr)
    print(f"  unique (src, comment-author) pairs: {len(edge_weights)}", file=sys.stderr)

    if not edge_weights:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for (src, platform, dst), w in edge_weights.items():
        rows.append({
            "brand_id": brand_id, "src_creator_id": src,
            "dst_handle": dst, "dst_platform": platform,
            "edge_type": "comment", "weight": w,
            "last_seen_at": now,
        })

    # Dedupe (defensive)
    deduped = {}
    for r in rows:
        k = (r["brand_id"], r["src_creator_id"], r["dst_handle"], r["dst_platform"], r["edge_type"])
        if k not in deduped or r["weight"] > deduped[k]["weight"]:
            deduped[k] = r
    rows = list(deduped.values())

    for i in range(0, len(rows), 500):
        sb.table("creator_edges").upsert(
            rows[i:i+500],
            on_conflict="brand_id,src_creator_id,dst_handle,dst_platform,edge_type"
        ).execute()

    print(f"  inserted/updated: {len(rows)} comment edges", file=sys.stderr)
    return len(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--top-posts", type=int, default=50,
                   help="How many top-comment posts to mine per brand")
    p.add_argument("--min-comment-count", type=int, default=20,
                   help="Skip posts with fewer than N comments")
    p.add_argument("--max-per-post", type=int, default=100,
                   help="Max comments to fetch per post")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = sb.table("brands").select("id, slug").execute().data or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    if not brands:
        print("No brands selected", file=sys.stderr); return

    grand = 0
    t0 = time.time()
    for b in brands:
        grand += process_brand(sb, b["id"], b["slug"],
                               args.top_posts, args.min_comment_count,
                               args.max_per_post, args.dry_run)
    print(f"\n=== COMMENT MINE COMPLETE in {time.time()-t0:.1f}s ===", file=sys.stderr)
    print(f"comment edges added/refreshed: {grand}", file=sys.stderr)


if __name__ == "__main__":
    main()
