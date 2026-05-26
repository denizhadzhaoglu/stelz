#!/usr/bin/env python3
"""Cache content_images to Supabase Storage so dashboard has permanent URLs.

Instagram CDN URLs expire (signed with tokens that die in <24h). For a dashboard
that needs to render thumbnails reliably, we must store our own copy.

For each content_images row without stored_path:
1. Download image_url
2. Resize to 512px max
3. Upload to bucket 'brand-watch-thumbnails' under path stelz/{shortcode}.jpg
4. Compute SHA256 hash, save both stored_path and image_hash on the row

Resume-safe: skips rows that already have stored_path.

Usage:
    python3 tools/stelz_brand_watch/10_cache_images.py
    python3 tools/stelz_brand_watch/10_cache_images.py --limit 50
"""

import argparse
import hashlib
import io
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

BUCKET = "brand-watch-thumbnails"
BRAND_SLUG = "stelz"


def get_client():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))


def fetch_and_resize(url: str, max_dim: int = 512) -> tuple[bytes, str] | None:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
        return data, hashlib.sha256(data).hexdigest()
    except Exception as e:
        print(f"  fetch failed for {url[:80]}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=2000)
    args = parser.parse_args()

    client = get_client()

    # Get brand id
    brand_res = client.table("brands").select("id").eq("slug", BRAND_SLUG).limit(1).execute()
    brand_id = brand_res.data[0]["id"]

    # Get images without stored_path, prioritize ones with detections
    res = (client.table("content_images")
           .select("id, image_url, content_item_id, stored_path")
           .eq("brand_id", brand_id)
           .is_("stored_path", "null")
           .limit(args.limit)
           .execute())
    images = res.data or []
    print(f"{len(images)} images to cache", file=sys.stderr)

    success = 0
    failed = 0
    t0 = time.time()

    for i, img in enumerate(images, 1):
        url = img["image_url"]
        if not url:
            continue
        fetched = fetch_and_resize(url)
        if not fetched:
            failed += 1
            continue
        data, sha = fetched

        # Path: stelz/{first_2_chars_of_hash}/{full_hash}.jpg (avoid one giant directory)
        path = f"stelz/{sha[:2]}/{sha}.jpg"

        try:
            # Upload (upsert = overwrite if exists; that's fine since same hash = same content)
            client.storage.from_(BUCKET).upload(
                path=path,
                file=data,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception as e:
            msg = str(e)
            if "Duplicate" in msg or "already exists" in msg:
                pass  # OK, another row had same hash, file already there
            else:
                print(f"  upload failed for {img['id']}: {msg[:100]}", file=sys.stderr)
                failed += 1
                continue

        # Update row with stored_path + image_hash
        try:
            client.table("content_images").update({
                "stored_path": path,
                "image_hash": sha,
            }).eq("id", img["id"]).execute()
            success += 1
        except Exception as e:
            print(f"  update failed for {img['id']}: {e}", file=sys.stderr)
            failed += 1

        if i % 50 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed else 0
            print(f"  {i}/{len(images)} ({success} ok, {failed} fail, {rate:.1f}/s)", file=sys.stderr)

    elapsed = time.time() - t0
    print(f"\nDone: {success} cached, {failed} failed in {elapsed:.1f}s", file=sys.stderr)
    print(f"Bucket: https://menaatbeoeutywulcdvv.supabase.co/storage/v1/object/public/{BUCKET}/...", file=sys.stderr)


if __name__ == "__main__":
    main()
