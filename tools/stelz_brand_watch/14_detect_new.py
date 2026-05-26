#!/usr/bin/env python3
"""Detect on any content_images without a v3 detection, using v3 prompt.

After Sprint A (#stelz harvest) and Sprint B (popular NL creators) added thousands
of new images, this script runs Gemini v3 detection on every image that doesn't
yet have a prompt_version=3 detection row.

Uses image_detection_cache (keyed by sha256 hash) to reuse detection results
for duplicate images across creators (e.g. reposts).

Usage:
    python3 tools/stelz_brand_watch/14_detect_new.py
    python3 tools/stelz_brand_watch/14_detect_new.py --limit 1000
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
REFERENCE_FILES = ["a09e6174600a45b9b4da970d4e2cc45a.png", "hardlemonade.webp", "stelz-smaak-tobias.jpg"]
MODEL = "gemini-2.5-flash"
PROMPT_VERSION = 3
STORAGE_BUCKET = "brand-watch-thumbnails"

PROMPT = """You are a visual brand detector for STELZ, a Dutch alcoholic beverage brand.

STELZ has three product lines:
1. STELZ HARD LEMONADE: slim cans with white top half and colored bottom half (blue/cassis, orange, pink/strawberry).
2. STELZ HARD SELTZER: white slim cans with illustrated artwork (fruit, abstract patterns), STELZ logo with orange/red "S" circle.
3. STELZ HARD ICED TEA: slim cans, flavors peach, lime, mango, with fruit illustration and "HARD ICED TEA" below.

The standalone logo is "STELZ" (umlaut on E) in dark navy, around an "S" in a red/orange circle.

3 reference images first, then 1 user post image.

Return ONLY this JSON:
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "size_in_frame": "small" | "medium" | "large" | "dominant",
  "is_primary_subject": true | false,
  "context": "one short sentence describing the image and where STELZ appears",
  "false_positive_risk": "low" | "medium" | "high"
}

size_in_frame: small=<5%, medium=5-20%, large=20-50%, dominant=>50%.
is_primary_subject: true if STELZ is the actual subject. false if background detail, illustration, or incidental.

CRITICAL: do NOT detect STELZ in cartoons, illustrations, drawn elements, unless the brand name is explicitly written.
CRITICAL: BE THOROUGH. Look at the entire image including hands, tables, backgrounds, shelves, t-shirts, packaging, flyers. If you see ANY STELZ branding (logo, text, product), set detected=true and describe where.
CRITICAL: only set detected=true if STELZ is genuinely visible. If unsure, set detected=false.
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


def resize_bytes(b, max_dim=512):
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
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
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def load_refs():
    parts = []
    for fname in REFERENCE_FILES:
        data = resize_bytes((REF_DIR / fname).read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


async def detect(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT, "Reference 1:", ref_parts[0], "Reference 2:", ref_parts[1],
                    "Reference 3:", ref_parts[2], "User post:", user]
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

    # Find content_images without a v3 detection
    # Use a raw SQL via RPC, OR fetch all images and existing v3 detections separately
    all_images = []
    offset = 0
    while True:
        res = sb.table("content_images").select("id, image_url, stored_path, image_hash").eq("brand_id", brand_id).range(offset, offset+999).execute()
        batch = res.data or []
        if not batch: break
        all_images.extend(batch)
        if len(batch) < 1000: break
        offset += 1000
    print(f"{len(all_images)} total images", file=sys.stderr)

    # Existing v3 detection content_image_ids
    have_v3 = set()
    offset = 0
    while True:
        res = sb.table("detections").select("content_image_id").eq("brand_id", brand_id).eq("prompt_version", 3).range(offset, offset+999).execute()
        batch = res.data or []
        if not batch: break
        for d in batch:
            have_v3.add(d["content_image_id"])
        if len(batch) < 1000: break
        offset += 1000
    print(f"{len(have_v3)} images already have v3 detection", file=sys.stderr)

    todo = [im for im in all_images if im["id"] not in have_v3]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} images to detect", file=sys.stderr)

    # Load hash cache for v3
    cache_rows = sb.table("image_detection_cache").select("image_hash, detection_result").eq("brand_id", brand_id).eq("model", MODEL).eq("prompt_version", PROMPT_VERSION).execute()
    cache = {r["image_hash"]: r["detection_result"] for r in (cache_rows.data or [])}
    print(f"{len(cache)} cache entries", file=sys.stderr)

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_refs()
    semaphore = asyncio.Semaphore(args.concurrency)

    new_detections = []
    cache_new = []
    failed = 0

    async def process(img):
        nonlocal failed
        # 1. Get bytes + hash
        if img.get("image_hash") and img["image_hash"] in cache:
            return (img["id"], cache[img["image_hash"]], img["image_hash"])
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img["image_url"])
        b = fetch_image(url)
        if not b:
            failed += 1
            return (img["id"], None, None)
        h = hashlib.sha256(b).hexdigest()
        if h in cache:
            return (img["id"], cache[h], h)
        result = await detect(client, ref_parts, b, semaphore)
        return (img["id"], result, h)

    t0 = time.time()
    results = await asyncio.gather(*[process(im) for im in todo])
    print(f"detect phase: {time.time()-t0:.1f}s", file=sys.stderr)

    seen_cache_hashes = set()
    for image_id, result, h in results:
        if not result:
            continue
        new_detections.append({
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
        if h and h not in cache and h not in seen_cache_hashes:
            cache_new.append({
                "image_hash": h,
                "brand_id": brand_id,
                "model": MODEL,
                "prompt_version": PROMPT_VERSION,
                "detection_result": result,
            })
            seen_cache_hashes.add(h)

    # Bulk insert
    print(f"Inserting {len(new_detections)} detections, {len(cache_new)} cache entries...", file=sys.stderr)
    for i in range(0, len(new_detections), 200):
        sb.table("detections").insert(new_detections[i:i+200]).execute()
    for i in range(0, len(cache_new), 200):
        sb.table("image_detection_cache").upsert(cache_new[i:i+200], on_conflict="image_hash,brand_id,model,prompt_version").execute()

    hits = sum(1 for d in new_detections if d["detected"] and (d.get("confidence") or 0) >= 0.5)
    print(f"\n=== DETECT SUMMARY ===", file=sys.stderr)
    print(f"Detected: {len(new_detections)}", file=sys.stderr)
    print(f"Failed (fetch): {failed}", file=sys.stderr)
    print(f"With STELZ hit: {hits}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
