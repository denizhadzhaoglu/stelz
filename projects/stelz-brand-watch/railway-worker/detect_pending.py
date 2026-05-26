#!/usr/bin/env python3
"""Run Gemini Flash detection on any content_image that doesn't yet have one.

This closes the gap where 15_tiktok_harvest.py and other harvesters cache
images but never trigger Flash detection. The daily_scan does it inline for
IG profile-scrape results, but TikTok hashtag scrapes and historical backfill
images stay un-detected until this script runs.

Strategy:
1. Pull content_image ids with NO detection rows.
2. Fetch the image bytes (prefer stored_path → Supabase Storage, else image_url).
3. Run Gemini Flash with the same v4 prompt + reference set as daily_scan.
4. Insert detection row, cache hash result, write image_hash + stored_path back.

Usage:
    python3 tools/stelz_brand_watch/33_detect_pending.py              # all pending
    python3 tools/stelz_brand_watch/33_detect_pending.py --limit 500  # cap batch
    python3 tools/stelz_brand_watch/33_detect_pending.py --concurrency 25
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
from dotenv import dotenv_values, load_dotenv
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

PROMPT = """You are a strict visual brand detector for STËLZ, a Dutch alcoholic beverage brand.

STËLZ has FOUR product lines plus a 0.0 non-alc line:
1. STËLZ HARD LEMONADE: slim white-top can with bold colored bottom (purple, orange, pink)
2. STËLZ HARD SELTZER: white slim can with illustrated lower half (passionfruit, raspberry, mango)
3. STËLZ HARD ICED TEA: white-top can with fruit-leaf illustration lower half (green, yellow, orange)
4. STËLZ MIXED CLASSICS: cocktail-in-a-can (orange, teal, brown)
5. STËLZ 0.0 non-alc: same shape, "NON ALC" + "0.0" label

DIAGNOSTIC FEATURES:
- "STËLZ" text spelled S-T-Ë-L-Z (umlaut on E), navy blue
- S-in-circle: thin ring with stylized "S" inside
- Curved sub-tagline beneath
Be strict. A random t-shirt print is NOT STELZ unless you can clearly read STËLZ or see the S-in-circle.

Return ONLY this JSON:
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "mixed_classics" | "zero_zero" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "size_in_frame": "small" | "medium" | "large" | "dominant",
  "is_primary_subject": true | false,
  "context": "one short sentence describing what you see",
  "false_positive_risk": "low" | "medium" | "high"
}
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
    raise RuntimeError("no AIza Gemini key found")


def resize_bytes(b, max_dim=512):
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def fetch_image(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
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


def load_refs(brand_slug: str = "stelz"):
    # Prefer brand-specific Storage refs (multi-tenant).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _brand_refs import load_brand_refs
        ref_bytes = load_brand_refs(brand_slug, max_dim=512, include_training=True)
        if ref_bytes:
            return [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in ref_bytes]
    except Exception as e:
        print(f"  [refs] storage load err: {e}; falling back to local", file=sys.stderr)
    # Legacy local fallback (STELZ only).
    parts = []
    for fname in REFERENCE_FILES:
        p = REF_DIR / fname
        if not p.exists(): continue
        data = resize_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


# Module-level error tally so the main loop can summarize at the end and
# operators see at a glance whether failures are quota-bound vs other.
ERR_TALLY = {"quota": 0, "transient_5xx": 0, "key_invalid": 0, "other": 0, "parse_fail": 0}


async def detect_one(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT]
        for i, r in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(r)
        contents.extend(["User post:", user])
        last_err_kind = None
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                parsed = parse_json(resp.text or "")
                if parsed is None:
                    ERR_TALLY["parse_fail"] += 1
                return parsed
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    last_err_kind = "quota"
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                if "503" in err or "500" in err or "UNAVAILABLE" in err:
                    last_err_kind = "transient_5xx"
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                if "API_KEY_INVALID" in err or "400 INVALID_ARGUMENT" in err:
                    last_err_kind = "key_invalid"
                    break
                last_err_kind = "other"
                break
        if last_err_kind:
            ERR_TALLY[last_err_kind] = ERR_TALLY.get(last_err_kind, 0) + 1
        return None


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_row = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).execute().data
    if not brand_row:
        sys.exit(f"No brand found with slug={args.brand_slug}")
    brand_id = brand_row[0]["id"]
    brand_slug = brand_row[0]["slug"]

    # 1. Collect content_image ids that have NO detection.
    done = set()
    offset = 0
    while True:
        r = sb.table("detections").select("content_image_id").eq("brand_id", brand_id).range(offset, offset+999).execute()
        if not r.data: break
        for d in r.data: done.add(d["content_image_id"])
        if len(r.data) < 1000: break
        offset += 1000

    pending = []
    offset = 0
    while True:
        # Skip images the moderator has explicitly rejected. Re-detecting
        # them would resurrect a hit the user already said wasn't STELZ.
        r = (sb.table("content_images")
               .select("id, image_url, stored_path")
               .eq("brand_id", brand_id)
               .is_("excluded_at", "null")
               .range(offset, offset+999)
               .execute())
        if not r.data: break
        for img in r.data:
            if img["id"] not in done:
                pending.append(img)
        if len(r.data) < 1000: break
        offset += 1000

    if args.limit:
        pending = pending[: args.limit]
    print(f"{len(pending)} images pending detection", file=sys.stderr)
    if not pending:
        return

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_refs(brand_slug)
    semaphore = asyncio.Semaphore(args.concurrency)

    async def process(img):
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img.get("image_url"))
        if not url:
            return (img["id"], None, None)
        b = fetch_image(url)
        if not b:
            return (img["id"], None, None)
        h = hashlib.sha256(b).hexdigest()
        # Backfill stored_path + hash if missing (cheap)
        if not img.get("stored_path"):
            path = f"stelz/{h[:2]}/{h}.jpg"
            try:
                sb.storage.from_(STORAGE_BUCKET).upload(
                    path=path, file=b,
                    file_options={"content-type": "image/jpeg", "upsert": "true"},
                )
            except Exception:
                pass
            try:
                sb.table("content_images").update({"stored_path": path, "image_hash": h}).eq("id", img["id"]).execute()
            except Exception as e:
                # The unique partial index on (content_item_id, image_hash)
                # rejects this when a keeper row for the same content_item
                # already has this hash. That means THIS row is a duplicate
                # of an existing keeper. Re-point any detections to the
                # keeper, then drop the duplicate content_images row.
                msg = str(e).lower()
                if "23505" in msg or "unique" in msg or "duplicate" in msg:
                    try:
                        ci_id_row = sb.table("content_images").select("content_item_id").eq("id", img["id"]).limit(1).execute().data
                        if ci_id_row:
                            ci_id = ci_id_row[0]["content_item_id"]
                            keeper = (sb.table("content_images")
                                        .select("id")
                                        .eq("content_item_id", ci_id)
                                        .eq("image_hash", h)
                                        .neq("id", img["id"])
                                        .limit(1).execute().data)
                            if keeper:
                                keeper_id = keeper[0]["id"]
                                # Re-point any detections (best-effort; drop on its own unique conflicts).
                                try:
                                    sb.table("detections").update({"content_image_id": keeper_id}).eq("content_image_id", img["id"]).execute()
                                except Exception:
                                    sb.table("detections").delete().eq("content_image_id", img["id"]).execute()
                                sb.table("content_images").delete().eq("id", img["id"]).execute()
                                # Tell caller to skip detection on this dropped row; the keeper already covers it.
                                return (img["id"], None, h)
                    except Exception as inner:
                        print(f"  reconcile-dup failed for {img['id']}: {inner}", file=sys.stderr)
                else:
                    print(f"  update content_images failed {img['id']}: {str(e)[:120]}", file=sys.stderr)
        result = await detect_one(client, ref_parts, b, semaphore)
        return (img["id"], result, h)

    t0 = time.time()
    results = await asyncio.gather(*[process(img) for img in pending])
    elapsed = time.time() - t0
    print(f"detect phase: {elapsed:.1f}s ({len(pending)/max(elapsed,1)*60:.0f}/min)", file=sys.stderr)

    new_dets = []
    hits = 0
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
        if result.get("detected") and (result.get("confidence") or 0) >= 0.5:
            hits += 1

    print(f"Inserting {len(new_dets)} detections...", file=sys.stderr)
    for i in range(0, len(new_dets), 200):
        sb.table("detections").insert(new_dets[i:i+200]).execute()

    print(f"\n=== DETECT-PENDING SUMMARY ===", file=sys.stderr)
    print(f"Images processed: {len(pending)}", file=sys.stderr)
    print(f"Detection rows added: {len(new_dets)}", file=sys.stderr)
    print(f"STELZ hits (confidence >= 0.5): {hits}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--brand-slug", dest="brand_slug", default="stelz")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
