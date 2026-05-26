#!/usr/bin/env python3
"""v4 detection: richer reference set + logo-focused prompt.

Adds:
- 4 product lines (Hard Lemonade, Hard Seltzer, Hard Iced Tea, Mixed Classics)
- 0.0 non-alcoholic variant (Sparkling Water, Iced Tea Lemon/Peach 0.0)
- 7 reference images sourced from drinkstelz.com (official)
- Explicit logo recognition guidance: STËLZ text with umlaut, S-in-circle in
  various colors (orange/red/green/yellow depending on line)
- Stronger instruction to look at clothing, banners, posters, menus, taps

Runs against any content_image without a v4 detection row.

Usage:
    python3 tools/stelz_brand_watch/16_detect_v4_logo_focus.py
    python3 tools/stelz_brand_watch/16_detect_v4_logo_focus.py --limit 200
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

# Rich reference set: official product line photos + UGC examples
REFERENCE_FILES_V4 = [
    "web_stelz_logo.png",       # Variety pack including 0.0 non-alc
    "web_group_13.png",         # Hard Iced Tea trio (Lemon, Mango, Peach)
    "web_group_132.png",        # Hard Seltzer trio (Passionfruit, Raspberry, Mango)
    "web_group_133.png",        # Mixed Classics trio (Spritz, Gin & Tonic, Moscow Mule)
    "web_hardlemonade.png",     # Hard Lemonade trio (Cassis, Orange, Strawberry)
    "web_lifestyle.png",        # UGC: man holding STELZ Signature can at party
    "web_lifestyle2.png",       # UGC: group photo with multiple STELZ cans at outdoor event
    "a09e6174600a45b9b4da970d4e2cc45a.png",  # Standalone logo close-up
]

MODEL = "gemini-2.5-flash"
PROMPT_VERSION = 4
STORAGE_BUCKET = "brand-watch-thumbnails"

PROMPT = """You are a visual brand detector for STËLZ, a Dutch alcoholic beverage brand (the first Dutch hard seltzer, founded 2020, Heineken minority stake 2024).

STËLZ has FOUR product lines plus a 0.0 non-alcoholic line:

1. STËLZ HARD LEMONADE: slim cans with white top half and bold colored bottom (cassis purple, orange, strawberry pink). Logo "STËLZ HARD LEMONADE" with S-in-circle in matching accent color. "HARD Lemonade <flavor>" in big script underneath. 63 calories, 4.5% alc.

2. STËLZ HARD SELTZER: slim cans, mostly white with brand logo top, illustrated artwork lower half (passionfruit purple, raspberry red, mango yellow). "STËLZ HARD SELTZER" with S-in-circle in matching accent color. "Alcohol infused sparkling water" subtitle. 63 calories, 4.5%.

3. STËLZ HARD ICED TEA: slim cans, white top with "STËLZ HARD ICED TEA" logo and S-in-circle (green for Lemon, yellow/orange for Mango, deep orange for Peach). Lower half has fruit/leaf illustrations. Smooth script "Lemon" / "Mango" / "Peach" on lower half. 69 calories, 4.5%.

4. STËLZ MIXED CLASSICS: cocktail-in-a-can. White top with "STËLZ MIXED CLASSICS" logo and S-in-circle (orange for Spritz, teal for Gin & Tonic, brown for Moscow Mule). Lower half has abstract colorful patterns. "CLASSIC" header then "SPRITZ" / "GIN & TONIC" / "MOSCOW MULE" in large block letters.

5. STËLZ 0.0 (non-alcoholic): same can shape, "NON ALC" badge top, "0.0" label. Includes Sparkling Water, Classic Iced Tea Lemon, Iced Tea Peach 0.0.

LOGO ELEMENTS (critical for detection):
- Brand name: "STËLZ" — NOTE the UMLAUT (two dots) over the E. This is THE diagnostic feature. Always spelled S-T-Ë-L-Z, dark navy blue text.
- S-in-circle: a thin ring (orange/red/green/yellow/teal/brown depending on product line) with a stylized "S" inside, often with two small letters or marks at left and right of the S (H-L for Hard Lemonade, H-S for Hard Seltzer, H-T for Hard Iced Tea, M-C for Mixed Classics).
- Curved sub-tagline: "HARD SELTZER" / "HARD LEMONADE" / "HARD ICED TEA" / "MIXED CLASSICS" curved beneath the brand name.

WHERE LOGO MAY APPEAR (look thoroughly):
- On a can (front, side, top rim)
- On a glass bottle or pack box
- Cooler, bucket, fridge, bar tap, dispenser
- T-shirt, hoodie, cap of staff or fans
- Promotional flyer, A4 poster, menu listing, price list
- Banner, sign, screen, projection at festival/event
- Bus, tram, billboard advertising
- Tattoo, sticker, button pin
- Print ad in magazine or newspaper
- Pack of cans on shelf in supermarket or slijterij

3 reference images then 1 user post image follow.

Return ONLY this JSON:
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "mixed_classics" | "zero_zero" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "size_in_frame": "small" | "medium" | "large" | "dominant",
  "is_primary_subject": true | false,
  "context": "one short sentence describing the image and exactly where/how STELZ appears",
  "false_positive_risk": "low" | "medium" | "high"
}

product_line guidance:
- A specific product line if you can see the actual product (can, bottle, pack).
- "logo_only" if you see only the brand name/logo without an actual product (e.g. on t-shirt, banner, menu listing, screen).
- "none" if you cannot detect STELZ at all.

size_in_frame: small=<5% of image area, medium=5-20%, large=20-50%, dominant=>50%.
is_primary_subject: true if STELZ is the actual subject of the photo (held by someone, focused on). false if background detail or incidental.

CRITICAL:
- BE THOROUGH. Scan hands, tables, shelves, walls, clothing, signage, screens, packaging.
- The umlaut on the E (Ë) is the strongest single tell. If you see "STELZ" without umlaut but with the S-in-circle, still detected.
- Look for the S-in-circle even if blurry, that distinctive ring shape with letter inside is rare.
- Do NOT count generic seltzers, White Claw, Bud Light Seltzer, etc as STELZ.
- Do NOT detect STELZ in cartoons or fully illustrated/drawn elements unless the brand name is explicitly written there.
- If unsure, set detected=false. Prefer miss over false positive.
- For very small / blurry / corner-of-frame appearances, lower the confidence accordingly but still detected=true if you can identify it.
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
    for fname in REFERENCE_FILES_V4:
        p = REF_DIR / fname
        if not p.exists():
            print(f"  WARNING: ref missing {fname}", file=sys.stderr)
            continue
        data = resize_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


async def detect(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT]
        for i, ref in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(ref)
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

    # Get all content images
    all_images = []
    offset = 0
    while True:
        res = sb.table("content_images").select("id, image_url, stored_path, image_hash").eq("brand_id", brand_id).range(offset, offset+999).execute()
        batch = res.data or []
        if not batch: break
        all_images.extend(batch)
        if len(batch) < 1000: break
        offset += 1000
    print(f"{len(all_images)} total images in DB", file=sys.stderr)

    # Skip those with existing v4 detection
    have_v4 = set()
    offset = 0
    while True:
        res = sb.table("detections").select("content_image_id").eq("brand_id", brand_id).eq("prompt_version", PROMPT_VERSION).range(offset, offset+999).execute()
        batch = res.data or []
        if not batch: break
        for d in batch:
            have_v4.add(d["content_image_id"])
        if len(batch) < 1000: break
        offset += 1000
    print(f"{len(have_v4)} images already have v4", file=sys.stderr)

    todo = [im for im in all_images if im["id"] not in have_v4]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} to detect with v4", file=sys.stderr)

    # Hash cache for v4
    cache_rows = sb.table("image_detection_cache").select("image_hash, detection_result").eq("brand_id", brand_id).eq("model", MODEL).eq("prompt_version", PROMPT_VERSION).execute()
    cache = {r["image_hash"]: r["detection_result"] for r in (cache_rows.data or [])}
    print(f"{len(cache)} v4 cache entries", file=sys.stderr)

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_refs()
    print(f"Loaded {len(ref_parts)} reference images", file=sys.stderr)
    semaphore = asyncio.Semaphore(args.concurrency)

    failed_fetch = 0
    new_dets = []
    cache_new = []
    seen_hashes = set()

    async def process(img):
        nonlocal failed_fetch
        if img.get("image_hash") and img["image_hash"] in cache:
            return (img["id"], cache[img["image_hash"]], img["image_hash"])
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img["image_url"])
        b = fetch_image(url)
        if not b:
            failed_fetch += 1
            return (img["id"], None, None)
        h = hashlib.sha256(b).hexdigest()
        if h in cache:
            return (img["id"], cache[h], h)
        result = await detect(client, ref_parts, b, semaphore)
        return (img["id"], result, h)

    t0 = time.time()
    results = await asyncio.gather(*[process(im) for im in todo])
    print(f"detect: {time.time()-t0:.1f}s", file=sys.stderr)

    for image_id, result, h in results:
        if not result:
            continue
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
        if h and h not in cache and h not in seen_hashes:
            cache_new.append({"image_hash": h, "brand_id": brand_id, "model": MODEL,
                              "prompt_version": PROMPT_VERSION, "detection_result": result})
            seen_hashes.add(h)

    print(f"Inserting {len(new_dets)} detections, {len(cache_new)} cache entries...", file=sys.stderr)
    for i in range(0, len(new_dets), 200):
        sb.table("detections").insert(new_dets[i:i+200]).execute()
    for i in range(0, len(cache_new), 200):
        sb.table("image_detection_cache").upsert(cache_new[i:i+200], on_conflict="image_hash,brand_id,model,prompt_version").execute()

    hits = sum(1 for d in new_dets if d["detected"] and (d.get("confidence") or 0) >= 0.5)
    by_line = {}
    for d in new_dets:
        if d["detected"] and (d.get("confidence") or 0) >= 0.5:
            line = d.get("product_line", "?")
            by_line[line] = by_line.get(line, 0) + 1

    print(f"\n=== V4 DETECT SUMMARY ===", file=sys.stderr)
    print(f"Detected rows: {len(new_dets)}", file=sys.stderr)
    print(f"Failed fetch: {failed_fetch}", file=sys.stderr)
    print(f"STELZ hits: {hits}", file=sys.stderr)
    print(f"By product line: {by_line}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=15)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
