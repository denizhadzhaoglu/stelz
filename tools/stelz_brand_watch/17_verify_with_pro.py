#!/usr/bin/env python3
"""Verify pass: re-detect every v4 hit with Gemini 2.5 Pro.

Gemini Flash had 2 documented false positives at confidence 1.0 in the
logo_only category. Pro is significantly better at edge cases.

For each v4 detection with detected=true and confidence >= 0.5:
  - Fetch image (from Supabase Storage when available, else CDN)
  - Run Gemini 2.5 Pro with the v4 prompt + 8 references
  - Insert new detection row with prompt_version=5

After the run, the view v_detections_full will surface the Pro result
(highest prompt_version) for those images, so the dashboard automatically
filters out Pro-rejected hits.

Usage:
    python3 tools/stelz_brand_watch/17_verify_with_pro.py
    python3 tools/stelz_brand_watch/17_verify_with_pro.py --limit 50
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
REFERENCE_FILES = [
    "web_stelz_logo.png", "web_group_13.png", "web_group_132.png",
    "web_group_133.png", "web_hardlemonade.png", "web_lifestyle.png",
    "web_lifestyle2.png", "a09e6174600a45b9b4da970d4e2cc45a.png",
]
MODEL = "gemini-2.5-pro"
PROMPT_VERSION = 5
STORAGE_BUCKET = "brand-watch-thumbnails"

PROMPT = """You are a precise visual brand verifier for STËLZ, a Dutch alcoholic beverage brand.

A previous less-precise model claimed to detect STËLZ in this image. Your job is to verify or reject that detection with high accuracy. Be strict.

STËLZ has FOUR product lines plus a 0.0 non-alcoholic line:

1. STËLZ HARD LEMONADE: slim white-top can with bold colored bottom (cassis purple, orange, strawberry pink). "STËLZ HARD LEMONADE" with S-in-circle in matching color.
2. STËLZ HARD SELTZER: white slim can with illustrated lower half (passionfruit, raspberry, mango). "STËLZ HARD SELTZER" with S-in-circle.
3. STËLZ HARD ICED TEA: white-top can with fruit-leaf illustration lower half (Lemon=green, Mango=yellow, Peach=orange). "STËLZ HARD ICED TEA" with S-in-circle.
4. STËLZ MIXED CLASSICS: cocktail-in-a-can (Spritz=orange, Gin & Tonic=teal, Moscow Mule=brown). "STËLZ MIXED CLASSICS" with S-in-circle.
5. STËLZ 0.0 non-alc: same shape, "NON ALC" badge, "0.0" label.

DIAGNOSTIC FEATURES (must be present for a true STELZ detection):
- "STËLZ" text spelled S-T-Ë-L-Z (umlaut on E), navy blue
- S-in-circle: thin ring with stylized "S" inside, optionally with small letters at left/right
- Curved sub-tagline beneath: "HARD SELTZER" / "HARD LEMONADE" / "HARD ICED TEA" / "MIXED CLASSICS"

CRITICAL VERIFICATION RULES:
- A random print on a t-shirt is NOT STELZ unless you can clearly read "STËLZ" or see the distinct S-in-circle.
- An award trophy is NOT STELZ unless the brand name is engraved/printed on it visibly.
- A generic white can or seltzer-shaped beverage is NOT STELZ unless you can read the brand name or see the S-in-circle.
- Banner text or graffiti words like "ASOCIAAL" are NOT STELZ.
- If you cannot 100% confirm the diagnostic features, set detected=false.

3 reference images then 1 user post image follow.

When detected=true, return bounding box(es) tightly enclosing the STELZ product(s) in the user post image. Critical rules:

  - Coordinate system: normalized 0-1000 with origin at TOP-LEFT of the image. y=0 is the TOP edge, y=1000 is the BOTTOM. x=0 is LEFT, x=1000 is RIGHT.
  - Order: [y1, x1, y2, x2] where y1 < y2 and x1 < x2.
  - Tightness: the box must hug the visible edges of the product (top edge of the can/bottle/box, its bottom edge, leftmost visible pixel, rightmost visible pixel). Not loose padding, not just a partial corner.
  - One box per distinct visible product instance. If two cans are visible in two different hands, return two boxes.
  - If the product is very small in the frame (estimated < 5% of total image area), do NOT return a bbox for it. Set bbox=[] and rely on the other JSON fields. Localization of tiny objects is unreliable and a wrong box is worse than no box.
  - Verify before returning: mentally trace the rectangle. Does its top edge sit at the product's top? Bottom at bottom? Left at left? Right at right? If not, adjust. If still unsure, return bbox=[].

Do not invent boxes when detected=false.

Return ONLY this JSON:
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "mixed_classics" | "zero_zero" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "size_in_frame": "small" | "medium" | "large" | "dominant",
  "is_primary_subject": true | false,
  "context": "one short sentence describing exactly what you see and where STELZ appears (or why you reject)",
  "false_positive_risk": "low" | "medium" | "high",
  "verified_by_pro": true,
  "verification_note": "short reason for confirm or reject",
  "bbox": [
    {"box_2d": [y1, x1, y2, x2], "label": "stelz hard seltzer can"}
  ]
}

Be strict. Prefer detected=false if any doubt. The previous model over-detected logos on clothing and objects.
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


def load_refs(brand_slug: str = "stelz"):
    """Brand-aware reference loader.

    Pulls product packshots from Supabase Storage under references/<slug>/.
    Falls back to the legacy local directory if the brand has no Storage refs
    yet (so STELZ keeps working in the transition window).
    """
    parts = []
    # Try Storage first (multi-tenant path)
    try:
        from _brand_refs import load_brand_refs
        for data in load_brand_refs(brand_slug, include_training=False):
            parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        if parts:
            return parts
    except Exception as e:
        print(f"  storage refs err: {e}", file=sys.stderr)
    # Fallback: legacy local files (STELZ-specific)
    for fname in REFERENCE_FILES:
        p = REF_DIR / fname
        if not p.exists(): continue
        data = resize_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    return parts


def load_fewshot():
    """Pull moderator-curated positive/negative examples to inject into prompt.

    These come from tools/stelz_brand_watch/29_train_from_moderator.py which
    pulls the latest moderator-confirmed and moderator-rejected detections,
    saves the images to reference-images/training/, and writes a manifest
    with the model's original verdict + moderator's correct call.

    Returns: list of (label_text, image_part) tuples to prepend to context.
    """
    train_dir = REF_DIR / "training"
    manifest_path = train_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        return []
    out = []
    for entry in manifest.get("positive", []):
        p = train_dir / entry["file"]
        if not p.exists(): continue
        img = genai_types.Part.from_bytes(data=resize_bytes(p.read_bytes()), mime_type="image/jpeg")
        label = (
            f"POSITIVE EXAMPLE: A human moderator confirmed STELZ IS visible in this image. "
            f"Model originally said: {entry['model_said'].get('context','')}"
        )
        out.append((label, img))
    for entry in manifest.get("negative", []):
        p = train_dir / entry["file"]
        if not p.exists(): continue
        img = genai_types.Part.from_bytes(data=resize_bytes(p.read_bytes()), mime_type="image/jpeg")
        label = (
            f"NEGATIVE EXAMPLE: A human moderator REJECTED this — STELZ is NOT actually visible. "
            f"Model wrongly claimed: {entry['model_said'].get('context','')}. "
            f"Learn from this hallucination."
        )
        out.append((label, img))
    return out


async def verify(client, ref_parts, fewshot_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT]
        for i, ref in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(ref)
        for label, part in fewshot_parts:
            contents.append(label)
            contents.append(part)
        contents.extend(["User post:", user])
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                return parse_json(resp.text or "")
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 3)
                    continue
                return {"error": str(e)[:200]}
        return None


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    if getattr(args, "reverify_ids", None):
        # Re-verify mode: caller supplied an explicit list of content_image_ids.
        ids = [l.strip() for l in Path(args.reverify_ids).read_text().splitlines() if l.strip()]
        v4_hits = [{"content_image_id": iid, "product_line": None, "confidence": None} for iid in ids]
        if args.limit:
            v4_hits = v4_hits[: args.limit]
        print(f"{len(v4_hits)} ids to re-verify with Pro (from {args.reverify_ids})", file=sys.stderr)
    else:
        # Default mode: find v4 Flash hits not yet covered by a v5 Pro verification.
        already_v5 = set()
        offset = 0
        while True:
            r = sb.table("detections").select("content_image_id").eq("brand_id", brand_id).eq("prompt_version", PROMPT_VERSION).range(offset, offset+999).execute()
            if not r.data: break
            for d in r.data: already_v5.add(d["content_image_id"])
            if len(r.data) < 1000: break
            offset += 1000

        v4_hits = []
        offset = 0
        while True:
            r = (sb.table("detections")
                 .select("content_image_id, product_line, confidence")
                 .eq("brand_id", brand_id)
                 .eq("prompt_version", 4)
                 .eq("detected", True)
                 .gte("confidence", 0.5)
                 .range(offset, offset+999)
                 .execute())
            if not r.data: break
            v4_hits.extend(r.data)
            if len(r.data) < 1000: break
            offset += 1000

        v4_hits = [h for h in v4_hits if h["content_image_id"] not in already_v5]
        if args.limit:
            v4_hits = v4_hits[: args.limit]
        print(f"{len(v4_hits)} v4 hits to verify with Pro", file=sys.stderr)

    # Get image URLs/paths
    image_ids = [h["content_image_id"] for h in v4_hits]
    images_by_id = {}
    # Fetch in batches
    for i in range(0, len(image_ids), 200):
        batch = image_ids[i:i+200]
        r = sb.table("content_images").select("id, image_url, stored_path").in_("id", batch).execute()
        for img in (r.data or []):
            images_by_id[img["id"]] = img

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=120_000))
    ref_parts = load_refs(args.brand_slug)
    fewshot_parts = load_fewshot()
    print(f"Loaded {len(ref_parts)} references + {len(fewshot_parts)} moderator-trained few-shot examples", file=sys.stderr)
    semaphore = asyncio.Semaphore(args.concurrency)

    failed = 0
    new_dets = []

    async def process(hit):
        nonlocal failed
        image_id = hit["content_image_id"]
        img = images_by_id.get(image_id)
        if not img:
            failed += 1
            return None
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img["image_url"])
        b = fetch_image(url)
        if not b:
            failed += 1
            return None
        result = await verify(client, ref_parts, fewshot_parts, b, semaphore)
        return (image_id, result, hit)

    t0 = time.time()
    results = await asyncio.gather(*[process(h) for h in v4_hits])
    elapsed = time.time() - t0
    print(f"verify phase: {elapsed:.1f}s ({len(v4_hits)/elapsed*60:.0f}/min)", file=sys.stderr)

    confirmed = 0
    rejected = 0
    errors = 0
    for r in results:
        if not r:
            errors += 1
            continue
        image_id, result, v4_hit = r
        if not result or "error" in result:
            errors += 1
            continue
        row = {
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
            "verified": True,
            "verified_by": "gemini-2.5-pro",
            "notes": result.get("verification_note"),
        }
        # Bounding boxes (column is optional — script tolerates missing column)
        if result.get("bbox"):
            row["bbox"] = result.get("bbox")
        new_dets.append(row)
        if result.get("detected") and (result.get("confidence") or 0) >= 0.5:
            confirmed += 1
        else:
            rejected += 1

    print(f"Inserting {len(new_dets)} verification rows...", file=sys.stderr)
    for i in range(0, len(new_dets), 200):
        chunk = new_dets[i:i+200]
        try:
            sb.table("detections").insert(chunk).execute()
        except Exception as e:
            # Bbox column may not exist yet — retry without it
            if "bbox" in str(e).lower() or "column" in str(e).lower():
                print(f"  bbox column missing, retrying without bbox...", file=sys.stderr)
                stripped = [{k: v for k, v in r.items() if k != "bbox"} for r in chunk]
                sb.table("detections").insert(stripped).execute()
            else:
                raise

    print(f"\n=== PRO VERIFY SUMMARY ===", file=sys.stderr)
    print(f"v4 hits checked: {len(v4_hits)}", file=sys.stderr)
    print(f"Failed: {failed} fetch, {errors} response", file=sys.stderr)
    print(f"Confirmed by Pro: {confirmed}", file=sys.stderr)
    print(f"REJECTED by Pro (likely v4 FPs): {rejected}", file=sys.stderr)
    print(f"Rejection rate: {rejected / max(confirmed+rejected, 1) * 100:.1f}%", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--reverify-ids", type=str, default=None,
                        help="Path to a newline-separated list of content_image_ids to re-verify")
    parser.add_argument("--brand-slug", default="stelz",
                        help="Brand slug for reference image lookup (default: stelz)")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
