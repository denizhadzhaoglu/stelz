#!/usr/bin/env python3
"""Strict re-verify pass for low-trust ("needs review") detections.

Targets the high-FP-risk slice: detected hits that
- have no STELZ mention in caption or hashtags
- are not marked as primary subject
- product_line is logo_only OR size_in_frame is small

For each such image we hit Gemini Pro with an extra-strict prompt that
forces it to answer "is there clearly a STELZ-branded product, of meaningful
size, that you can point to with high confidence?". If Pro disagrees, we
mark the detection as is_false_positive=true automatically.

Usage:
    python3 tools/stelz_brand_watch/27_strict_verify_review_hits.py
    python3 tools/stelz_brand_watch/27_strict_verify_review_hits.py --dry-run
    python3 tools/stelz_brand_watch/27_strict_verify_review_hits.py --limit 50
"""

import argparse
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

PRO_MODEL = "gemini-2.5-pro"


def _get_gemini_key():
    for k in ("GEMINI_API_KEY", "GOOGLE_AI_API_KEY"):
        v = os.getenv(k, "")
        if v and v.startswith("AIza"):
            return v
    # Fallback: pull AIza key from sibling dl-orchestrator/.env
    for p in [PA_ROOT.parent / "dl-orchestrator" / ".env",
              Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env")]:
        if p.exists():
            for k, v in dotenv_values(p).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.startswith("AIza"):
                    return v.strip()
    raise RuntimeError("no AIza Gemini key found")

GEMINI_KEY = None

STELZ_CAPTION_RE = re.compile(r"\bstelz\b", re.IGNORECASE)

STRICT_PROMPT = """You are a brand auditor specifically looking for the Dutch hard seltzer brand STELZ.

STELZ packaging always shows the wordmark "STELZ" in bold sans-serif (sometimes with two dots on the E, like "STËLZ") on a colored can. The product lines are:
- Hard Seltzer (light pastel cans)
- Hard Lemonade (bright fruit-color cans)
- Hard Iced Tea (warm-color cans)
- Mixed Classics (variety pack)

Look at the image and answer STRICTLY. Only answer "yes" if ALL of these hold:
1. You can clearly READ the letters S-T-E-L-Z on a product (can, bottle, packaging) in the image.
2. The product is recognizable as the STELZ product itself, not just text on a t-shirt, sticker, banner, trophy, sign, or other object.
3. The product occupies a meaningful portion of the frame (not a tiny background blur, not a partial sliver behind another object).

If any of these are uncertain, answer "no". Hallucinations and over-eager matches are unacceptable.

Return ONLY a JSON object:
{
  "detected": true|false,
  "confidence": 0.0..1.0,
  "reason": "one short sentence explaining what you actually see",
  "stelz_text_visible": true|false,
  "product_visible": true|false,
  "size": "small|medium|large|dominant|none"
}"""


def fetch_review_candidates(sb, brand_id, limit):
    """Pull current detections that would land in the 'needs review' bucket."""
    # Get latest detection per image (mirrors v_detections_full's distinct on)
    # plus the caption + handle to apply the review rule.
    res = sb.rpc("execute_sql", {}).execute() if False else None  # placeholder for clarity

    # Simpler: select detections directly, join with content_items via REST view
    res = (
        sb.table("v_detections_full")
        .select("detection_id, post_caption, post_hashtags, "
                "product_line, size_in_frame, is_primary_subject, "
                "creator_handle, image_url, stored_path, is_false_positive, verified")
        .eq("brand_id", brand_id)
        .eq("detected", True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []

    review_rows = []
    for d in rows:
        if d.get("is_false_positive"):
            continue
        if d.get("verified"):
            continue
        caption = (d.get("post_caption") or "").lower()
        hashtags = [(h or "").lower() for h in (d.get("post_hashtags") or [])]
        stelz_in_text = (
            bool(STELZ_CAPTION_RE.search(caption))
            or any("stelz" in h for h in hashtags)
        )
        if stelz_in_text:
            continue  # trusted via caption
        if d.get("is_primary_subject") and d.get("size_in_frame") in {"medium", "large", "dominant"}:
            continue  # trusted via primary subject
        if d.get("product_line") in {"hard_lemonade", "hard_seltzer", "hard_iced_tea", "mixed_classics"} \
                and d.get("size_in_frame") in {"medium", "large", "dominant"}:
            continue  # trusted via clear product
        review_rows.append(d)
    return review_rows


def fetch_image_bytes(url, timeout=20):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def gemini_pro_verify(image_bytes):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{PRO_MODEL}:generateContent?key={GEMINI_KEY}"
    import base64
    payload = {
        "contents": [{
            "parts": [
                {"text": STRICT_PROMPT},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_bytes).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0.0, "response_mime_type": "application/json"},
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    j = r.json()
    text = j["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200, help="Max images to verify")
    p.add_argument("--dry-run", action="store_true", help="Compute outcome without writing to DB")
    args = p.parse_args()

    global GEMINI_KEY
    try:
        GEMINI_KEY = _get_gemini_key()
    except RuntimeError as e:
        sys.exit(str(e))

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Over-fetch generously since most rows are trusted (95%); filter then cap.
    candidates = fetch_review_candidates(sb, brand_id, 5000)
    candidates = candidates[: args.limit]
    print(f"Found {len(candidates)} 'needs review' candidates", file=sys.stderr)

    flipped_fp = 0
    confirmed = 0
    errors = 0
    for i, d in enumerate(candidates, 1):
        img_url = d["image_url"]
        if d.get("stored_path"):
            img_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/brand-watch-thumbnails/{d['stored_path']}"
        print(f"[{i}/{len(candidates)}] @{d['creator_handle']} {d['product_line']} {d['size_in_frame']}...", file=sys.stderr)
        try:
            img_bytes = fetch_image_bytes(img_url)
        except Exception as e:
            print(f"  fetch err: {e}", file=sys.stderr)
            errors += 1
            continue
        try:
            verdict = gemini_pro_verify(img_bytes)
        except Exception as e:
            print(f"  pro err: {e}", file=sys.stderr)
            errors += 1
            time.sleep(2)
            continue

        is_fp = not verdict.get("detected")
        reason = verdict.get("reason", "")
        print(f"  → pro says detected={verdict.get('detected')} conf={verdict.get('confidence')}: {reason[:90]}", file=sys.stderr)

        if not args.dry_run:
            sb.table("detections").update({
                "is_false_positive": is_fp,
                "verified": True,
                "verified_by": "gemini_pro_strict",
                "verified_at": "now()",
                "notes": f"strict_verify v1: {reason}"[:500],
            }).eq("id", d["detection_id"]).execute()

        if is_fp:
            flipped_fp += 1
        else:
            confirmed += 1
        time.sleep(0.3)

    print(f"\n=== STRICT VERIFY SUMMARY ===", file=sys.stderr)
    print(f"Candidates processed: {len(candidates)}", file=sys.stderr)
    print(f"  Flipped to FP:      {flipped_fp}", file=sys.stderr)
    print(f"  Confirmed real:     {confirmed}", file=sys.stderr)
    print(f"  Errors:             {errors}", file=sys.stderr)


if __name__ == "__main__":
    main()
