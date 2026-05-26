#!/usr/bin/env python3
"""Re-scan ALL existing images with the v3 prompt (stricter + more metadata).

Compares the result with the existing detection. Goal: catch hits the first
scan missed because the prompt was less specific, and see if v3 reduces FPs.

For each content_images row:
- Download image from stored_path (Supabase Storage) or image_url
- Run Gemini Flash with v3 prompt (asyncio concurrency 20)
- Insert new detection row with prompt_version=3
- Update v3 image_detection_cache so future scans can reuse

After: print delta summary (new hits, lost hits, changed product_lines).

Usage:
    python3 tools/stelz_brand_watch/11_rescan_v3.py
    python3 tools/stelz_brand_watch/11_rescan_v3.py --limit 100
"""

import argparse
import asyncio
import hashlib
import io
import os
import re
import sys
import time
from collections import defaultdict
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
CRITICAL: BE THOROUGH. Look at the entire image including hands, tables, backgrounds, shelves, t-shirts, packaging, flyers. STELZ might be small but still visible. If you see ANY STELZ branding (logo, text, product), set detected=true and describe where.
CRITICAL: only set detected=true if STELZ is genuinely visible. If unsure, set detected=false.
"""


def _get_gemini_key():
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"):
        return env_key
    for p in [PA_ROOT.parent / "dl-orchestrator" / ".env",
              Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env")]:
        if p.exists():
            for k, v in dotenv_values(p).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                    return v.strip()
    raise RuntimeError("No AIza key")


def resize_bytes(b: bytes, max_dim: int = 512) -> bytes:
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def fetch_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return resize_bytes(r.content)
    except Exception:
        return None


def parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m: return None
    import json
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def load_refs():
    parts = []
    for fname in REFERENCE_FILES:
        p = REF_DIR / fname
        data = resize_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


async def detect_one(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user_part = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [
            PROMPT,
            "Reference 1:", ref_parts[0],
            "Reference 2:", ref_parts[1],
            "Reference 3:", ref_parts[2],
            "User post:", user_part,
        ]
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                return parse_json(resp.text or "")
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                return {"error": str(e)[:200]}
        return None


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]
    print(f"brand {brand_id}", file=sys.stderr)

    # Get content_images rows (paginate, REST limit ~1000)
    images = []
    offset = 0
    while True:
        res = (sb.table("content_images")
               .select("id, image_url, stored_path")
               .eq("brand_id", brand_id)
               .range(offset, offset + 999)
               .execute())
        batch = res.data or []
        if not batch:
            break
        images.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    if args.limit:
        images = images[: args.limit]
    print(f"{len(images)} images to rescan", file=sys.stderr)

    # Get existing v1 detections by content_image_id for comparison
    existing_by_image = {}
    offset = 0
    while True:
        res = (sb.table("detections")
               .select("content_image_id, detected, product_line, confidence")
               .eq("brand_id", brand_id)
               .eq("prompt_version", 1)
               .range(offset, offset + 999)
               .execute())
        batch = res.data or []
        if not batch:
            break
        for d in batch:
            existing_by_image[d["content_image_id"]] = d
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"{len(existing_by_image)} existing v1 detections to compare against", file=sys.stderr)

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_refs()
    semaphore = asyncio.Semaphore(args.concurrency)

    t0 = time.time()
    async def process(img):
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img["image_url"])
        img_bytes = fetch_image(url)
        if not img_bytes:
            return (img["id"], None, "fetch_failed")
        result = await detect_one(client, ref_parts, img_bytes, semaphore)
        return (img["id"], result, None)

    results = await asyncio.gather(*[process(im) for im in images])

    print(f"detect: {time.time() - t0:.1f}s for {len(images)} images", file=sys.stderr)

    # Insert new detections + compare
    new_rows = []
    new_hits = 0
    lost_hits = 0
    confirmed_hits = 0
    failed = 0
    for image_id, result, err in results:
        if err or not result or "error" in result:
            failed += 1
            continue
        new_rows.append({
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
        old = existing_by_image.get(image_id)
        new_detected = result.get("detected", False) and result.get("confidence", 0) >= 0.5
        old_detected = old and old.get("detected") and (old.get("confidence") or 0) >= 0.5
        if new_detected and not old_detected:
            new_hits += 1
        elif old_detected and not new_detected:
            lost_hits += 1
        elif new_detected and old_detected:
            confirmed_hits += 1

    # Bulk insert
    print(f"\nInserting {len(new_rows)} v3 detection rows...", file=sys.stderr)
    for i in range(0, len(new_rows), 200):
        chunk = new_rows[i:i+200]
        sb.table("detections").insert(chunk).execute()

    print(f"\n=== RESCAN v3 SUMMARY ===", file=sys.stderr)
    print(f"Images rescanned: {len(images)}", file=sys.stderr)
    print(f"Failed: {failed}", file=sys.stderr)
    print(f"  Confirmed hits (both v1 + v3 said yes): {confirmed_hits}", file=sys.stderr)
    print(f"  NEW hits (v3 yes, v1 no -- missed by v1!): {new_hits}", file=sys.stderr)
    print(f"  Lost hits (v1 yes, v3 no -- likely v1 FPs): {lost_hits}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
