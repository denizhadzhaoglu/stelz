#!/usr/bin/env python3
"""Visual scan FAST: parallel Gemini calls + image hash dedup + resize.

Speed optimizations vs 06_visual_scan.py:
- asyncio parallel Gemini calls (semaphore-limited, default 20 concurrent)
- SHA256 image hash dedup cache: same image bytes -> reuse detection
- Image resize to max 512px before upload (smaller payload, faster)
- Same prompt and reference images as 06 (with size_in_frame / is_primary_subject)

Reads candidates from --input CSV (default: lifestyle_persons.csv).
Output: validated_stelz_creators_fast.csv

Usage:
    python3 tools/stelz_brand_watch/08_visual_scan_fast.py --top 50
    python3 tools/stelz_brand_watch/08_visual_scan_fast.py --input lifestyle_persons.csv --top 50 --concurrency 20
"""

import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv, dotenv_values
from PIL import Image
from google import genai
from google.genai import types as genai_types

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
SCRAPED_DIR = OUTPUT_DIR / "scraped_per_creator"
DETECT_DIR = OUTPUT_DIR / "detect_per_creator"
HASH_CACHE_FILE = OUTPUT_DIR / "image_hash_cache.json"
SCRAPED_DIR.mkdir(parents=True, exist_ok=True)
DETECT_DIR.mkdir(parents=True, exist_ok=True)

REF_DIR = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"
REFERENCE_FILES = [
    "a09e6174600a45b9b4da970d4e2cc45a.png",
    "hardlemonade.webp",
    "stelz-smaak-tobias.jpg",
]

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_PROFILE = "apify/instagram-profile-scraper"
MODEL = "gemini-2.5-flash"
MAX_IMAGE_DIM = 512

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

CRITICAL: do NOT detect STELZ in cartoons, illustrations, drawn elements, unless the brand name is explicitly written. Real product cans only.
CRITICAL: only set detected=true if the STELZ product is CLEARLY VISIBLE, takes up a MEANINGFUL portion of the frame (not just a tiny detail in background), and would be recognizable to a human viewer at a glance. A "faintly visible can on a screen in the background" or "barely visible can on the top shelf" or "tiny can in the corner" does NOT count as detected. Set detected=false in those cases.
CRITICAL: if not sure, set detected=false. Prefer miss over false positive.
"""


def _get_gemini_key() -> str:
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"):
        return env_key
    candidates = [
        PA_ROOT.parent / "dl-orchestrator" / ".env",
        Path("/Users/meintestinstra/Documents/Jackandai/dl-orchestrator/.env"),
    ]
    for dl_env in candidates:
        if dl_env.exists():
            for k, v in dotenv_values(dl_env).items():
                if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                    return v.strip()
    raise RuntimeError("No valid AIza GOOGLE_AI_API_KEY found")


def apify_run_sync(actor_id: str, run_input: dict, timeout: int = 300) -> list:
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "memory": 1024}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 30)
    resp.raise_for_status()
    return resp.json()


def load_hash_cache() -> dict:
    if HASH_CACHE_FILE.exists():
        return json.loads(HASH_CACHE_FILE.read_text())
    return {}


def save_hash_cache(cache: dict):
    HASH_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))


def resize_image_bytes(img_bytes: bytes, max_dim: int = MAX_IMAGE_DIM) -> bytes:
    try:
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) <= max_dim:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return img_bytes


def fetch_image_bytes(url: str, timeout: int = 20) -> bytes | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def parse_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def load_ref_parts():
    parts = []
    for fname in REFERENCE_FILES:
        p = REF_DIR / fname
        # Also resize references for consistency and smaller payload
        resized = resize_image_bytes(p.read_bytes())
        parts.append(genai_types.Part.from_bytes(data=resized, mime_type="image/jpeg"))
    return parts


async def detect_async(client, ref_parts, img_bytes: bytes, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        user_part = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [
            PROMPT,
            "Reference 1 (logo):", ref_parts[0],
            "Reference 2 (Hard Lemonade lineup):", ref_parts[1],
            "Reference 3 (lifestyle UGC):", ref_parts[2],
            "User post:", user_part,
        ]
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=MODEL, contents=contents)
                parsed = parse_json(resp.text or "")
                if parsed is None:
                    return {"error": "unparseable", "raw": (resp.text or "")[:300]}
                return parsed
            except Exception as e:
                err = str(e)
                if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                return {"error": "exception", "detail": str(e)[:300]}
        return {"error": "max_retries"}


def scrape_creator_batch(handles: list[str], posts_per_creator: int) -> dict:
    try:
        items = apify_run_sync(ACTOR_PROFILE, {
            "usernames": handles,
            "resultsLimit": posts_per_creator,
        }, timeout=400)
    except Exception as e:
        print(f"  batch failed: {e}", file=sys.stderr)
        return {}
    by_handle: dict = defaultdict(list)
    for item in items:
        handle = item.get("username") or item.get("ownerUsername")
        if not handle:
            continue
        posts = item.get("latestPosts") or []
        if posts:
            by_handle[handle] = posts
        elif item.get("type") in ("Image", "Video", "Sidecar"):
            owner = item.get("ownerUsername")
            if owner:
                by_handle[owner].append(item)
    return by_handle


async def main_async(args):
    csv_in = OUTPUT_DIR / args.input
    if not csv_in.exists():
        sys.exit(f"Missing {csv_in}")

    all_candidates = list(csv.DictReader(open(csv_in)))
    score_field = "composite" if "composite" in all_candidates[0] else "composite_score"
    candidates = sorted(all_candidates, key=lambda x: float(x[score_field]), reverse=True)[: args.top]
    print(f"Selected {len(candidates)} candidates from {args.input}", file=sys.stderr)

    # SCRAPE PHASE
    handles_to_scrape = [c["handle"] for c in candidates if not (SCRAPED_DIR / f"{c['handle']}.json").exists()]
    if handles_to_scrape:
        print(f"\n--- SCRAPE: {len(handles_to_scrape)} new handles ---", file=sys.stderr)
        t0 = time.time()
        for i in range(0, len(handles_to_scrape), args.batch_size):
            batch = handles_to_scrape[i:i + args.batch_size]
            print(f"  batch {i//args.batch_size+1}: {len(batch)} handles", file=sys.stderr)
            by_handle = scrape_creator_batch(batch, args.posts_per_creator)
            for handle in batch:
                posts = by_handle.get(handle, [])
                (SCRAPED_DIR / f"{handle}.json").write_text(json.dumps(posts, ensure_ascii=False))
        print(f"  scrape phase: {time.time()-t0:.1f}s", file=sys.stderr)

    # DETECT PHASE (parallel)
    print(f"\n--- DETECT (parallel, concurrency={args.concurrency}) ---", file=sys.stderr)
    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_ref_parts()
    hash_cache = load_hash_cache()
    print(f"Loaded {len(hash_cache)} cached image hashes", file=sys.stderr)

    semaphore = asyncio.Semaphore(args.concurrency)

    # Collect all image-tasks per candidate
    all_tasks = []  # list of (handle, shortcode, img_bytes_resized, img_hash, post)
    skipped_cached = 0

    for c in candidates:
        handle = c["handle"]
        scrape_file = SCRAPED_DIR / f"{handle}.json"
        if not scrape_file.exists():
            continue
        posts = json.loads(scrape_file.read_text())
        detect_file = DETECT_DIR / f"{handle}.json"
        existing = json.loads(detect_file.read_text()) if detect_file.exists() else {}

        for post in posts:
            short = post.get("shortCode") or post.get("id")
            if not short:
                continue
            if short in existing:
                continue  # already detected for this candidate
            img_url = post.get("displayUrl")
            if not img_url:
                continue
            img_bytes = fetch_image_bytes(img_url)
            if not img_bytes:
                continue
            resized = resize_image_bytes(img_bytes)
            h = hashlib.sha256(resized).hexdigest()
            if h in hash_cache:
                existing[short] = hash_cache[h]
                skipped_cached += 1
                continue
            all_tasks.append((handle, short, resized, h, post))
        detect_file.write_text(json.dumps(existing, ensure_ascii=False))

    print(f"  {skipped_cached} images already in hash cache (skip Gemini)", file=sys.stderr)
    print(f"  {len(all_tasks)} new Gemini detection calls to run", file=sys.stderr)

    t0 = time.time()
    async def run_one(task):
        handle, short, img_bytes, h, post = task
        result = await detect_async(client, ref_parts, img_bytes, semaphore)
        return (handle, short, h, result)

    results = await asyncio.gather(*[run_one(t) for t in all_tasks])

    # Persist by handle
    per_handle_detections: dict = defaultdict(dict)
    for handle, short, h, result in results:
        per_handle_detections[handle][short] = result
        if "error" not in result:
            hash_cache[h] = result

    for handle, dets in per_handle_detections.items():
        detect_file = DETECT_DIR / f"{handle}.json"
        existing = json.loads(detect_file.read_text()) if detect_file.exists() else {}
        existing.update(dets)
        detect_file.write_text(json.dumps(existing, ensure_ascii=False))

    save_hash_cache(hash_cache)
    print(f"  detect phase: {time.time()-t0:.1f}s for {len(all_tasks)} calls", file=sys.stderr)

    # Build summary CSV: dump ALL detections (no hardcoded filter)
    # UI/dashboard filters on product_line, size_in_frame, etc
    candidate_results = []
    all_detections_flat = []
    for c in candidates:
        handle = c["handle"]
        detect_file = DETECT_DIR / f"{handle}.json"
        if not detect_file.exists():
            continue
        dets = json.loads(detect_file.read_text())
        scanned = len(dets)
        all_hits = [(sc, d) for sc, d in dets.items() if d.get("detected") and d.get("confidence", 0) >= 0.5]
        # Default "clear visibility" subset for the candidate summary
        clear_hits = [(sc, d) for sc, d in all_hits
                      if d.get("product_line") in {"hard_lemonade", "hard_seltzer", "hard_iced_tea"}
                      and not (d.get("size_in_frame") == "small" and not d.get("is_primary_subject") and d.get("confidence", 0) < 0.9)]
        candidate_results.append({
            "handle": handle,
            "full_name": c.get("full_name", ""),
            "posts_scanned": scanned,
            "total_detections": len(all_hits),
            "clear_visibility_hits": len(clear_hits),
            "hit_rate": round(len(all_hits) / max(scanned, 1), 3),
        })
        # Flat detection log: every detection with full metadata
        sf = SCRAPED_DIR / f"{handle}.json"
        posts = {p.get("shortCode") or p.get("id"): p for p in json.loads(sf.read_text())} if sf.exists() else {}
        for sc, d in all_hits:
            post = posts.get(sc, {})
            all_detections_flat.append({
                "handle": handle,
                "shortcode": sc,
                "url": post.get("url") or f"https://www.instagram.com/p/{sc}/",
                "posted_at": post.get("timestamp"),
                "caption": (post.get("caption") or "")[:200],
                "hashtags_on_post": ",".join((post.get("hashtags") or [])[:10]),
                "product_line": d.get("product_line"),
                "confidence": d.get("confidence"),
                "size_in_frame": d.get("size_in_frame"),
                "is_primary_subject": d.get("is_primary_subject"),
                "context": d.get("context"),
                "false_positive_risk": d.get("false_positive_risk"),
            })

    candidate_results.sort(key=lambda r: (r["total_detections"], r["hit_rate"]), reverse=True)
    out_csv = OUTPUT_DIR / "validated_stelz_creators_fast.csv"
    if candidate_results:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(candidate_results[0].keys()))
            w.writeheader()
            w.writerows(candidate_results)

    # Full detection log (every hit with full metadata for dashboard filtering)
    detections_csv = OUTPUT_DIR / "all_detections.csv"
    if all_detections_flat:
        with open(detections_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_detections_flat[0].keys()))
            w.writeheader()
            w.writerows(all_detections_flat)

    with_hits = sum(1 for r in candidate_results if r["total_detections"] > 0)
    print(f"\n=== FAST SCAN SUMMARY ===", file=sys.stderr)
    print(f"Candidates: {len(candidate_results)}", file=sys.stderr)
    print(f"With any STELZ detection: {with_hits}", file=sys.stderr)
    print(f"Total detections (all types): {len(all_detections_flat)}", file=sys.stderr)
    print(f"\nTop candidates:", file=sys.stderr)
    for r in candidate_results[:25]:
        if r["total_detections"] == 0:
            break
        print(f"  @{r['handle']:<28} {r['total_detections']} total  ({r['clear_visibility_hits']} clear)  {r['full_name'][:30]}", file=sys.stderr)
    print(f"\nWrote: {out_csv}", file=sys.stderr)
    print(f"Wrote: {detections_csv}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="lifestyle_persons.csv")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--posts-per-creator", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
