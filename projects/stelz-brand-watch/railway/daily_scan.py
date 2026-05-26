#!/usr/bin/env python3
"""Daily incremental scan: refresh seed list creators and detect new posts.

Pipeline:
1. Pull all creators with status in ('discovered','promoted') from Supabase
2. Batch-scrape their latest 20 posts via Apify Instagram Profile Scraper
3. Upsert new content_items (external_id conflict skips existing)
4. Cache new images to Supabase Storage (sha256-keyed)
5. Run Gemini Flash v4 detection on any new image
6. Log to discovery_runs table

Intended to run once per day via cron (Railway, Vercel Cron, GitHub Actions).

Usage:
    python3 tools/stelz_brand_watch/18_daily_scan.py
    python3 tools/stelz_brand_watch/18_daily_scan.py --max-creators 100 --dry-run
"""

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv, dotenv_values
from google import genai
from google.genai import types as genai_types
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

REF_DIR = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"
REFERENCE_FILES = [
    "web_stelz_logo.png", "web_group_13.png", "web_group_132.png",
    "web_group_133.png", "web_hardlemonade.png", "web_lifestyle.png",
    "web_lifestyle2.png", "a09e6174600a45b9b4da970d4e2cc45a.png",
]
MODEL = "gemini-2.5-flash"
PROMPT_VERSION = 4
STORAGE_BUCKET = "brand-watch-thumbnails"
APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_PROFILE = "apify/instagram-profile-scraper"

# Use the v4 prompt from 16_detect_v4_logo_focus.py (kept in sync)
PROMPT = """You are a visual brand detector for STËLZ, a Dutch alcoholic beverage brand.

STËLZ has four product lines plus 0.0 non-alc: Hard Lemonade, Hard Seltzer, Hard Iced Tea, Mixed Classics, 0.0 (NON ALC variant).

Diagnostic features:
- "STËLZ" text with umlaut on E, navy blue
- S-in-circle ring (orange/red/green/yellow/teal/brown by line)
- Curved tagline: HARD SELTZER / HARD LEMONADE / HARD ICED TEA / MIXED CLASSICS

Return JSON:
{"detected": bool, "product_line": "hard_lemonade"|"hard_seltzer"|"hard_iced_tea"|"mixed_classics"|"zero_zero"|"logo_only"|"none",
 "confidence": 0-1, "size_in_frame": "small"|"medium"|"large"|"dominant",
 "is_primary_subject": bool, "context": "short sentence", "false_positive_risk": "low"|"medium"|"high"}

Be strict: prefer detected=false if any doubt. Don't detect on random clothing prints, generic seltzers, or unrelated logos.
"""


def _get_gemini_key():
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"): return env_key
    for p in [PA_ROOT.parent / "dl-orchestrator" / ".env",
              Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env")]:
        if p.exists():
            for k, v in dotenv_values(p).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                    return v.strip()
    raise RuntimeError("no AIza key")


def apify_run(handles, timeout=400, posts_limit=20):
    url = f"https://api.apify.com/v2/acts/{ACTOR_PROFILE.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(url, json={"usernames": handles, "resultsLimit": posts_limit},
                      params={"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024},
                      timeout=timeout + 30)
    r.raise_for_status()
    return r.json()


async def apify_run_async(handles, posts_limit, sem, timeout=400):
    """Async wrapper that runs Apify in a thread so multiple batches can
    overlap. The Apify run-sync endpoint is the bottleneck (10-30s per batch
    of 25 profiles); running 4-6 batches concurrently scales linearly."""
    async with sem:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: apify_run(handles, timeout, posts_limit))


def resize_bytes(b, max_dim=512):
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def fetch_image(url):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return resize_bytes(r.content)
    except Exception:
        return None


def parse_json(text):
    cleaned = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None


def load_refs():
    parts = []
    for fname in REFERENCE_FILES:
        p = REF_DIR / fname
        if not p.exists(): continue
        data = resize_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


async def detect_one(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT]
        for i, r in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(r)
        contents.extend(["User post:", user])
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                return parse_json(resp.text or "")
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                return None
        return None


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Audit start
    run_res = sb.table("discovery_runs").insert({
        "brand_id": brand_id,
        "source_type": "daily_scan",
        "platform": "instagram",
        "status": "running",
    }).execute()
    run_id = run_res.data[0]["id"]
    print(f"discovery_run {run_id} started", file=sys.stderr)

    try:
        # Get IG creators (we don't scrape TikTok in daily yet)
        creators_q = (sb.table("creators")
                      .select("id, handle, last_scraped_at")
                      .eq("brand_id", brand_id)
                      .eq("platform", "instagram")
                      .in_("status", ["discovered", "promoted"])
                      .order("last_scraped_at", nullsfirst=True))
        if args.max_creators:
            creators_q = creators_q.limit(args.max_creators)
        creators = creators_q.execute().data or []
        # Skip creators scraped in the recent past — they have nothing new yet.
        # Default: 6h for daily cron, but the queue-processor calls this for
        # manual scans where user wants fresher data (we still skip <30min).
        skip_hours = args.skip_recent_hours
        if skip_hours and skip_hours > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=skip_hours)
            before = len(creators)
            creators = [c for c in creators if not c.get("last_scraped_at")
                        or datetime.fromisoformat(c["last_scraped_at"].replace("Z","+00:00")) < cutoff]
            print(f"{len(creators)} creators to refresh (skipped {before-len(creators)} scraped <{skip_hours}h ago)", file=sys.stderr)
        else:
            print(f"{len(creators)} creators to refresh", file=sys.stderr)

        # Existing external_ids so we only insert new
        existing_ext_ids = set()
        offset = 0
        while True:
            r = sb.table("content_items").select("external_id").eq("brand_id", brand_id).eq("platform", "instagram").range(offset, offset+999).execute()
            if not r.data: break
            for c in r.data: existing_ext_ids.add(c["external_id"])
            if len(r.data) < 1000: break
            offset += 1000
        print(f"{len(existing_ext_ids)} known content_items, scanning for new", file=sys.stderr)

        if args.dry_run:
            print("DRY RUN: stopping before Apify calls", file=sys.stderr)
            return

        # Parallel batch profile scrape — biggest single speedup. Was sequential
        # (22 batches × ~20s = 7-8 min). Now N concurrent batches, capped by
        # apify_concurrency, makes Apify ~4-6x faster end-to-end.
        new_posts = []  # list of (creator_id, post)
        handle_to_id = {c["handle"]: c["id"] for c in creators}
        handles = list(handle_to_id.keys())
        batch_size = 25
        batches = [handles[i:i+batch_size] for i in range(0, len(handles), batch_size)]
        apify_sem = asyncio.Semaphore(args.apify_concurrency)
        t_apify = time.time()
        results = await asyncio.gather(
            *[apify_run_async(b, args.posts_per_creator, apify_sem) for b in batches],
            return_exceptions=True,
        )
        print(f"  apify phase: {time.time()-t_apify:.1f}s for {len(batches)} batches "
              f"(concurrency {args.apify_concurrency})", file=sys.stderr)

        creator_updates = {}  # cid -> {handle, follower_count}
        for batch_idx, profiles in enumerate(results):
            if isinstance(profiles, Exception):
                print(f"  batch {batch_idx+1} failed: {profiles}", file=sys.stderr)
                continue
            for profile in (profiles or []):
                handle = profile.get("username") or profile.get("ownerUsername")
                if not handle or profile.get("error"):
                    continue
                cid = handle_to_id.get(handle)
                if not cid:
                    continue
                # Stash handle on the row too — PostgREST upsert validates all
                # NOT NULL columns even on the INSERT-on-conflict-UPDATE path.
                creator_updates[cid] = {
                    "handle": handle,
                    "follower_count": profile.get("followersCount"),
                }
                for post in (profile.get("latestPosts") or []):
                    short = post.get("shortCode") or post.get("id")
                    if not short or short in existing_ext_ids:
                        continue
                    new_posts.append((cid, post))

        # Batch update creators. NOTE: PostgREST upsert checks NOT NULL on
        # every row of the implicit INSERT path, even when the conflict
        # resolution is UPDATE-only — so we MUST include brand_id explicitly.
        now_iso = datetime.now(timezone.utc).isoformat()
        if creator_updates:
            t_cu = time.time()
            rows = [{
                "id": cid,
                "brand_id": brand_id,
                "platform": "instagram",  # NOT NULL constraint
                **v,                       # provides "handle" + "follower_count"
                "last_scraped_at": now_iso,
            } for cid, v in creator_updates.items()]
            for i in range(0, len(rows), 500):
                sb.table("creators").upsert(rows[i:i+500], on_conflict="id").execute()
            print(f"  creator updates: {time.time()-t_cu:.1f}s for {len(rows)} creators", file=sys.stderr)

        print(f"\n{len(new_posts)} new posts found across creators", file=sys.stderr)

        # Bulk insert content_items + content_images. Each row is built first,
        # then we hit Supabase with 500-row chunks instead of N single inserts.
        ci_rows = []
        for cid, post in new_posts:
            short = post.get("shortCode") or post.get("id")
            if not short:
                continue
            url = post.get("url") or f"https://www.instagram.com/p/{short}/"
            ci_rows.append({
                "brand_id": brand_id,
                "creator_id": cid,
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
                "_display_url": post.get("displayUrl"),  # carried via dict, dropped before insert
            })
        # Strip the carrier key before insert
        ci_insert = [{k: v for k, v in r.items() if k != "_display_url"} for r in ci_rows]
        ext_to_display = {r["external_id"]: r.get("_display_url") for r in ci_rows}
        ci_id_by_ext = {}
        if ci_insert:
            t_ci = time.time()
            for i in range(0, len(ci_insert), 500):
                res = sb.table("content_items").upsert(
                    ci_insert[i:i+500], on_conflict="platform,external_id"
                ).execute()
                for row in (res.data or []):
                    ci_id_by_ext[row["external_id"]] = row["id"]
            print(f"  content_items upsert: {time.time()-t_ci:.1f}s for {len(ci_insert)} rows", file=sys.stderr)

        img_rows = []
        for ext_id, display_url in ext_to_display.items():
            if not display_url:
                continue
            ci_id = ci_id_by_ext.get(ext_id)
            if not ci_id:
                continue
            img_rows.append({
                "content_item_id": ci_id,
                "brand_id": brand_id,
                "image_url": display_url,
                "sequence_idx": 0,
            })
        new_image_ids = []  # (image_id, display_url)
        if img_rows:
            t_img = time.time()
            for i in range(0, len(img_rows), 500):
                res = sb.table("content_images").insert(img_rows[i:i+500]).execute()
                for j, row in enumerate(res.data or []):
                    new_image_ids.append((row["id"], img_rows[i+j]["image_url"]))
            print(f"  content_images insert: {time.time()-t_img:.1f}s for {len(img_rows)} rows", file=sys.stderr)

        print(f"{len(new_image_ids)} new images inserted", file=sys.stderr)

        # Cache + detect new images
        client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
        ref_parts = load_refs()
        semaphore = asyncio.Semaphore(args.concurrency)

        async def process(image_id, display_url):
            b = fetch_image(display_url)
            if not b: return (image_id, None, None)
            h = hashlib.sha256(b).hexdigest()
            # Upload to storage
            path = f"stelz/{h[:2]}/{h}.jpg"
            try:
                sb.storage.from_(STORAGE_BUCKET).upload(
                    path=path, file=b,
                    file_options={"content-type": "image/jpeg", "upsert": "true"},
                )
            except Exception:
                pass
            sb.table("content_images").update({"stored_path": path, "image_hash": h}).eq("id", image_id).execute()
            # Detect
            result = await detect_one(client, ref_parts, b, semaphore)
            return (image_id, result, h)

        t0 = time.time()
        results = await asyncio.gather(*[process(iid, url) for iid, url in new_image_ids])
        print(f"cache+detect: {time.time()-t0:.1f}s for {len(new_image_ids)} images", file=sys.stderr)

        # Insert detections
        new_dets = []
        cache_seen = set()
        new_cache = []
        for image_id, result, h in results:
            if not result: continue
            new_dets.append({
                "brand_id": brand_id,
                "content_image_id": image_id,
                "model": MODEL,
                "prompt_version": PROMPT_VERSION,
                "detected": bool(result.get("detected", False)),
                "product_line": result.get("product_line"),
                "confidence": result.get("confidence"),
                "size_in_frame": result.get("size_in_frame"),
                "is_primary_subject": result.get("is_primary_subject"),
                "context": result.get("context"),
                "false_positive_risk": result.get("false_positive_risk"),
            })
            if h and h not in cache_seen:
                new_cache.append({"image_hash": h, "brand_id": brand_id, "model": MODEL,
                                  "prompt_version": PROMPT_VERSION, "detection_result": result})
                cache_seen.add(h)
        for i in range(0, len(new_dets), 200):
            sb.table("detections").insert(new_dets[i:i+200]).execute()
        for i in range(0, len(new_cache), 200):
            sb.table("image_detection_cache").upsert(new_cache[i:i+200], on_conflict="image_hash,brand_id,model,prompt_version").execute()

        hits = sum(1 for d in new_dets if d["detected"] and (d.get("confidence") or 0) >= 0.5)
        print(f"\nNew detections: {len(new_dets)} ({hits} hits)", file=sys.stderr)

        sb.table("discovery_runs").update({
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed",
            "results_count": len(new_image_ids),
        }).eq("id", run_id).execute()
        print(f"\n=== DAILY SCAN COMPLETE ===", file=sys.stderr)
        print(f"Creators refreshed: {len(creators)}", file=sys.stderr)
        print(f"New posts: {len(new_posts)}", file=sys.stderr)
        print(f"New images: {len(new_image_ids)}", file=sys.stderr)
        print(f"New detections: {len(new_dets)} ({hits} STELZ hits)", file=sys.stderr)

    except Exception as e:
        sb.table("discovery_runs").update({
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "error": str(e)[:1000],
        }).eq("id", run_id).execute()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-creators", type=int, default=0)
    parser.add_argument("--posts-per-creator", type=int, default=8,
                        help="How many recent posts per creator (default 8: rarely miss anything daily)")
    parser.add_argument("--concurrency", type=int, default=20,
                        help="Gemini Flash detection concurrency")
    parser.add_argument("--apify-concurrency", type=int, default=5,
                        help="How many Apify profile-scrape batches to run in parallel")
    parser.add_argument("--skip-recent-hours", type=int, default=6,
                        help="Skip creators last scraped within N hours (default 6, set 0 to disable)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
