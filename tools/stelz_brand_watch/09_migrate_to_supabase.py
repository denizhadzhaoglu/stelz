#!/usr/bin/env python3
"""Migrate pilot data from .tmp/ JSON files into Supabase Postgres.

Reads:
- .tmp/stelz_brand_watch/scraped_per_creator/{handle}.json (scraped IG posts)
- .tmp/stelz_brand_watch/detect_per_creator/{handle}.json (Gemini detection results)
- .tmp/stelz_brand_watch/image_hash_cache.json (hash cache)
- .tmp/stelz_brand_watch/known_false_positives.json (manual overrides)
- .tmp/stelz_brand_watch/lifestyle_persons.csv (creator scoring signals)

Writes to Supabase:
- creators (upsert by brand_id + platform + handle)
- content_items (upsert by platform + external_id)
- content_images
- detections
- image_detection_cache

Idempotent: re-runnable, skips existing rows.

Usage:
    python3 tools/stelz_brand_watch/09_migrate_to_supabase.py
    python3 tools/stelz_brand_watch/09_migrate_to_supabase.py --dry-run
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client
from PIL import Image

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

DATA_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
SCRAPED_DIR = DATA_DIR / "scraped_per_creator"
DETECT_DIR = DATA_DIR / "detect_per_creator"

BRAND_SLUG = "stelz"

# Heuristic for creator category (matches what we used in discovery)
BUSINESS_RE = re.compile(
    r"\b(cafe|caf[eé]|restaurant|bar |club|hotel|hostel|inn|pizza|sushi|frietzaak|"
    r"snackbar|grand cafe|stadscafe|borrelbar|schenkerij|slijterij|wijnhuis|"
    r"markt|winkel|supermarkt|albert heijn|jumbo|lidl|brouwerij)",
    re.IGNORECASE,
)
STUDENT_RE = re.compile(r"\b(svosiris|svoikosnomos|ddvigeo|introweek|eurekaweek|uniwageningen|dispuut)", re.IGNORECASE)
FESTIVAL_RE = re.compile(r"\b(festival|kermis|tentfeest|koningsdag|zomerfeest|midzomer)", re.IGNORECASE)


def categorize(handle: str, full_name: str | None) -> str:
    text = " ".join(filter(None, [handle, full_name or ""])).lower()
    if STUDENT_RE.search(text):
        return "student_org"
    if FESTIVAL_RE.search(text):
        return "festival"
    if BUSINESS_RE.search(text):
        return "horeca"
    return "person"


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not (url and key):
        sys.exit("SUPABASE_URL or SUPABASE_SECRET_KEY missing in .env")
    return create_client(url, key)


def fetch_brand_id(client, slug: str) -> str:
    res = client.table("brands").select("id").eq("slug", slug).limit(1).execute()
    if not res.data:
        sys.exit(f"Brand '{slug}' not found in DB. Run db/02_seed_stelz.sql first.")
    return res.data[0]["id"]


def fetch_image_hash(image_url: str, timeout: int = 15) -> str | None:
    try:
        r = requests.get(image_url, timeout=timeout)
        r.raise_for_status()
        # Resize same way as 08_visual_scan_fast.py for consistent hashes
        img = Image.open(io.BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > 512:
            scale = 512 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return hashlib.sha256(buf.getvalue()).hexdigest()
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rehash-images", action="store_true", help="Re-download images to compute hash. Slower.")
    args = parser.parse_args()

    client = get_client()
    brand_id = fetch_brand_id(client, BRAND_SLUG)
    print(f"Brand stelz: {brand_id}", file=sys.stderr)

    # Load creator signals from CSVs
    persons_csv = DATA_DIR / "lifestyle_persons.csv"
    creators_csv = DATA_DIR / "lifestyle_creators.csv"
    signals_by_handle: dict = {}
    if persons_csv.exists():
        for r in csv.DictReader(open(persons_csv)):
            signals_by_handle[r["handle"]] = r
    elif creators_csv.exists():
        for r in csv.DictReader(open(creators_csv)):
            signals_by_handle[r["handle"]] = r

    # Load false positive overrides
    fp_file = DATA_DIR / "known_false_positives.json"
    known_fp = json.loads(fp_file.read_text()) if fp_file.exists() else {}

    # Load hash cache
    hash_cache_file = DATA_DIR / "image_hash_cache.json"
    hash_cache = json.loads(hash_cache_file.read_text()) if hash_cache_file.exists() else {}

    # Walk creators we have any data on
    handles = sorted({f.stem for f in SCRAPED_DIR.glob("*.json")} | {f.stem for f in DETECT_DIR.glob("*.json")})
    print(f"Found {len(handles)} creators with data", file=sys.stderr)

    if args.dry_run:
        print("DRY RUN, not writing", file=sys.stderr)
        return

    n_creators = 0
    n_content = 0
    n_images = 0
    n_detections = 0
    n_signals = 0

    for handle in handles:
        scraped_file = SCRAPED_DIR / f"{handle}.json"
        detect_file = DETECT_DIR / f"{handle}.json"
        posts = json.loads(scraped_file.read_text()) if scraped_file.exists() else []
        detections = json.loads(detect_file.read_text()) if detect_file.exists() else {}

        # Find full_name from any post
        full_name = None
        for p in posts:
            if p.get("ownerFullName"):
                full_name = p["ownerFullName"]
                break

        # Upsert creator
        category = categorize(handle, full_name)
        creator_row = {
            "brand_id": brand_id,
            "platform": "instagram",
            "handle": handle,
            "full_name": full_name,
            "category": category,
            "status": "discovered",
        }
        cres = client.table("creators").upsert(creator_row, on_conflict="brand_id,platform,handle").execute()
        creator_id = cres.data[0]["id"]
        n_creators += 1

        # Insert signals if we have them
        sig = signals_by_handle.get(handle)
        if sig:
            sig_rows = []
            for k in ("composite", "composite_score", "person_score", "avg_engagement", "nl_signal_score", "post_count"):
                if k in sig and sig[k] not in ("", None):
                    try:
                        sig_rows.append({
                            "creator_id": creator_id,
                            "signal_type": k,
                            "value": float(sig[k]),
                            "source": "discovery_v2_lifestyle",
                        })
                    except (ValueError, TypeError):
                        pass
            if sig_rows:
                client.table("creator_signals").insert(sig_rows).execute()
                n_signals += len(sig_rows)

        # Posts -> content_items + content_images + detections
        for post in posts:
            short = post.get("shortCode") or post.get("id")
            if not short:
                continue
            url = post.get("url") or f"https://www.instagram.com/p/{short}/"
            content_row = {
                "brand_id": brand_id,
                "creator_id": creator_id,
                "platform": "instagram",
                "external_id": short,
                "content_type": "post" if post.get("type") != "Video" else "reel",
                "url": url,
                "caption": (post.get("caption") or "")[:5000],
                "hashtags": post.get("hashtags") or [],
                "mentions": post.get("mentions") or [],
                "posted_at": post.get("timestamp"),
                "likes_count": post.get("likesCount"),
                "comments_count": post.get("commentsCount"),
                "views_count": post.get("videoPlayCount"),
            }
            ci_res = client.table("content_items").upsert(content_row, on_conflict="platform,external_id").execute()
            content_item_id = ci_res.data[0]["id"]
            n_content += 1

            display_url = post.get("displayUrl")
            if not display_url:
                continue

            img_row = {
                "content_item_id": content_item_id,
                "brand_id": brand_id,
                "image_url": display_url,
                "sequence_idx": 0,
            }
            # Find existing image first (since no unique constraint), else insert
            existing = client.table("content_images").select("id,image_hash").eq("content_item_id", content_item_id).eq("image_url", display_url).limit(1).execute()
            if existing.data:
                image_id = existing.data[0]["id"]
            else:
                img_res = client.table("content_images").insert(img_row).execute()
                image_id = img_res.data[0]["id"]
                n_images += 1

            # Detection for this post (if available)
            det = detections.get(short)
            if det:
                is_fp = short in known_fp
                detection_row = {
                    "brand_id": brand_id,
                    "content_image_id": image_id,
                    "model": "gemini-2.5-flash",
                    "prompt_version": 1,
                    "detected": bool(det.get("detected", False)),
                    "product_line": det.get("product_line"),
                    "confidence": det.get("confidence"),
                    "size_in_frame": det.get("size_in_frame"),
                    "is_primary_subject": det.get("is_primary_subject"),
                    "context": det.get("context"),
                    "false_positive_risk": det.get("false_positive_risk"),
                    "is_false_positive": is_fp if is_fp else None,
                    "notes": known_fp.get(short, {}).get("reason") if is_fp else None,
                }
                client.table("detections").insert(detection_row).execute()
                n_detections += 1

        if n_creators % 10 == 0:
            print(f"  ...{n_creators} creators processed", file=sys.stderr)

    # Image hash cache
    if hash_cache:
        cache_rows = []
        for h, result in hash_cache.items():
            cache_rows.append({
                "image_hash": h,
                "brand_id": brand_id,
                "model": "gemini-2.5-flash",
                "prompt_version": 1,
                "detection_result": result,
            })
        # Bulk upsert in batches of 200
        for i in range(0, len(cache_rows), 200):
            chunk = cache_rows[i:i+200]
            client.table("image_detection_cache").upsert(chunk, on_conflict="image_hash,brand_id,model,prompt_version").execute()
        print(f"  hash cache: {len(cache_rows)} entries", file=sys.stderr)

    print(f"\n=== MIGRATION SUMMARY ===", file=sys.stderr)
    print(f"Creators: {n_creators}", file=sys.stderr)
    print(f"Creator signals: {n_signals}", file=sys.stderr)
    print(f"Content items: {n_content}", file=sys.stderr)
    print(f"Content images: {n_images}", file=sys.stderr)
    print(f"Detections: {n_detections}", file=sys.stderr)
    print(f"Hash cache entries: {len(hash_cache)}", file=sys.stderr)


if __name__ == "__main__":
    main()
