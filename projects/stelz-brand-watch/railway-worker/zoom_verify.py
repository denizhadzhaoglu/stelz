#!/usr/bin/env python3
"""Zoom-and-verify pass for borderline-confidence detections.

The Flash detection pipeline downscales images to 512px before inference.
Small or partial product placements (e.g. a can held in the corner of a
festival shot) lose detail and end up in the 0.5-0.7 confidence band.

This pass re-runs Gemini Pro on those borderline images at 1024px max
dimension, with a prompt that explicitly asks the model to look for
small / partial product placement. False positives stay rejected,
genuine missed detections get upgraded.

Cost: ~€0.005 per Pro call. Borderline volume per brand is typically
low (single digits to low hundreds per week). Total cost rarely exceeds
€1/week per brand.

Usage:
    python3 tools/stelz_brand_watch/42_zoom_verify.py
    python3 tools/stelz_brand_watch/42_zoom_verify.py --brand stelz --limit 20
    python3 tools/stelz_brand_watch/42_zoom_verify.py --dry-run
"""

import argparse
import asyncio
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv
from google import genai
from google.genai import types as genai_types
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

MODEL = "gemini-2.5-pro"
PROMPT_VERSION = 100  # int marker: 100+ = zoom-pass re-verified at hi-res
STORAGE_BUCKET = "brand-watch-thumbnails"
ZOOM_MAX_DIM = 1024  # vs the regular 512px downscale

PROMPT = """You are a STRICT visual brand verifier doing a high-resolution re-check.

This image is being re-examined because the first-pass detection had
borderline confidence (0.5-0.7). Your job: confirm or reject the detection
by looking carefully at small or partial product placement that may have
been missed at lower resolution.

Look specifically for:
- Logos or text on a beverage container that match the reference packshots
- The distinctive can shape + color combination (top half white, bottom
  half colorful: purple/orange/pink for lemonade, blue for seltzer)
- Partial visibility: even half a can in a corner counts IF you can verify
  the visual signature

DO NOT confirm if:
- The container is generic (no logo) or only vaguely beverage-shaped
- The visual matches a lookalike brand
- The product is only inferred from context (a person at a bar, etc.)

Return ONLY valid JSON:
{
  "detected": true|false,
  "confidence": 0.0-1.0,
  "product_line": "hard_lemonade"|"hard_seltzer"|"hard_iced_tea"|"mixed_classics"|"non_alc"|"logo_only"|null,
  "size_in_frame": "tiny"|"small"|"medium"|"large"|"dominant",
  "is_primary_subject": true|false,
  "verification_notes": "short explanation of what you saw and your decision"
}
"""


def _get_gemini_key() -> str:
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"): return env_key
    # Fallback: scan sibling project .env files for the real key.
    for p in [PA_ROOT.parent / "dl-orchestrator" / ".env",
              Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env")]:
        if p.exists():
            for k, v in dotenv_values(p).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                    return v.strip()
    raise RuntimeError("no AIza Gemini key found")


def parse_json(text: str):
    cleaned = re.sub(r"^```(?:json)?", "", (text or "").strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m: return None
    try: return json.loads(m.group(0))
    except Exception: return None


def hi_res_resize(b: bytes, max_dim: int = ZOOM_MAX_DIM) -> bytes:
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def fetch_image(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        print(f"  fetch err {url[:80]}: {e}", file=sys.stderr)
    return None


def load_refs(brand_slug: str):
    """Reuse the brand_refs loader, but at higher dim for zoom pass."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _brand_refs import load_brand_refs
        return [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg")
                for b in load_brand_refs(brand_slug, max_dim=ZOOM_MAX_DIM, include_training=True)]
    except Exception as e:
        print(f"  [refs] err: {e}", file=sys.stderr)
        return []


async def verify_one(client, ref_parts, img_bytes, semaphore):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [PROMPT]
        for i, r in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(r)
        contents.extend(["Image to verify:", user])
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                return parse_json(resp.text or "")
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                print(f"  verify err: {e}", file=sys.stderr)
                return None
        return None


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_row = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).execute().data
    if not brand_row:
        sys.exit(f"No brand {args.brand_slug}")
    brand_id = brand_row[0]["id"]
    brand_slug = brand_row[0]["slug"]

    # Find borderline detections that haven't been zoom-verified yet
    q = (sb.table("detections")
         .select("id, content_image_id, detected, confidence, model, prompt_version, verified")
         .eq("brand_id", brand_id)
         .gte("confidence", args.min_conf)
         .lte("confidence", args.max_conf)
         .neq("prompt_version", PROMPT_VERSION)  # not yet zoom-verified
         .order("confidence", desc=False)  # focus on most uncertain first
         .limit(args.limit))
    candidates = q.execute().data or []
    if not candidates:
        print("No borderline detections to zoom-verify.", file=sys.stderr)
        return

    print(f"Zoom-verifying {len(candidates)} borderline detections for {brand_slug}", file=sys.stderr)

    # Lookup the image URLs / paths
    img_ids = [c["content_image_id"] for c in candidates]
    imgs_by_id = {}
    for i in range(0, len(img_ids), 200):
        r = sb.table("content_images").select("id, image_url, stored_path").in_("id", img_ids[i:i+200]).execute().data or []
        for row in r:
            imgs_by_id[row["id"]] = row

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_refs(brand_slug)
    if not ref_parts:
        sys.exit("No reference images found for brand")

    sem = asyncio.Semaphore(args.concurrency)

    async def process(det):
        img = imgs_by_id.get(det["content_image_id"])
        if not img: return (det, None)
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img.get("image_url"))
        if not url: return (det, None)
        raw = fetch_image(url)
        if not raw: return (det, None)
        resized = hi_res_resize(raw)
        result = await verify_one(client, ref_parts, resized, sem)
        return (det, result)

    results = await asyncio.gather(*[process(d) for d in candidates])

    confirmed = 0
    rejected = 0
    upgraded = 0
    for det, result in results:
        if not result:
            continue
        new_detected = bool(result.get("detected"))
        new_conf = result.get("confidence")
        decision = None
        if det["detected"] and not new_detected:
            rejected += 1; decision = "rejected"
        elif det["detected"] and new_detected:
            confirmed += 1; decision = "confirmed"
        elif not det["detected"] and new_detected:
            upgraded += 1; decision = "upgraded_to_hit"
        else:
            decision = "still_negative"

        if args.dry_run:
            print(f"  {decision}: id={det['id']} old_conf={det['confidence']} new_conf={new_conf} "
                  f"notes={(result.get('verification_notes') or '')[:80]}", file=sys.stderr)
            continue

        sb.table("detections").update({
            "detected": new_detected,
            "confidence": new_conf,
            "product_line": result.get("product_line"),
            "size_in_frame": result.get("size_in_frame"),
            "is_primary_subject": result.get("is_primary_subject"),
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "context": (result.get("verification_notes") or "")[:500],
        }).eq("id", det["id"]).execute()

    print(f"\n=== ZOOM VERIFY SUMMARY ===", file=sys.stderr)
    print(f"Confirmed (still detected): {confirmed}", file=sys.stderr)
    print(f"Rejected (was FP):           {rejected}", file=sys.stderr)
    print(f"Upgraded (missed TP):        {upgraded}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand-slug", dest="brand_slug", default="stelz")
    p.add_argument("--min-conf", type=float, default=0.45)
    p.add_argument("--max-conf", type=float, default=0.70)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
