#!/usr/bin/env python3
"""Visual scan: scrape recent posts of top candidates and run STELZ detection.

Takes the top N candidates from lifestyle_creators.csv, fetches their recent
posts via Apify, then runs Gemini Flash visual detection on each image to
identify which candidates actually feature STELZ in their content.

Output: validated_stelz_creators.csv, ranked by detection hit count.

Resume-safe: existing per-candidate scrape and detection files are skipped.

Usage:
    python3 tools/stelz_brand_watch/06_visual_scan.py --top 100
    python3 tools/stelz_brand_watch/06_visual_scan.py --top 500 --posts-per-creator 20
"""

import argparse
import csv
import json
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

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

OUTPUT_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
SCRAPED_DIR = OUTPUT_DIR / "scraped_per_creator"
DETECT_DIR = OUTPUT_DIR / "detect_per_creator"
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

PROMPT = """You are a visual brand detector for STELZ, a Dutch alcoholic beverage brand.

STELZ has three product lines:
1. STELZ HARD LEMONADE: slim cans with white top half and colored bottom half (blue/cassis, orange, pink/strawberry), STELZ logo in dark blue with colored "S" circle.
2. STELZ HARD SELTZER: white slim cans with illustrated artwork (fruit, abstract patterns), STELZ logo in dark blue with orange/red "S" circle, "HARD SELTZER" below.
3. STELZ HARD ICED TEA: slim cans, flavors peach, lime, mango, with fruit illustration and "HARD ICED TEA" below.

The standalone logo is "STELZ" (umlaut on E) in dark navy, arranged around an "S" in a red/orange circle.

I will show 3 reference images first, then 1 user post image.

Return ONLY this JSON (no markdown, no prose):
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "size_in_frame": "small" | "medium" | "large" | "dominant",
  "is_primary_subject": true | false,
  "context": "one short sentence describing the image and where STELZ appears",
  "false_positive_risk": "low" | "medium" | "high"
}

size_in_frame: how much of the image does STELZ occupy? small = less than 5% of image, medium = 5-20%, large = 20-50%, dominant = more than 50%.
is_primary_subject: true if STELZ is the actual subject the photo is about (held by someone, on a tap, in focus). false if it's a background detail, illustration on a flyer, or incidental.

CRITICAL: do NOT detect STELZ in cartoons, illustrations, drawn elements, or graphics unless the brand name is explicitly written. Real product cans only.
CRITICAL: if you are not sure, set detected=false. We prefer missing a hit over false positives.

Set false_positive_risk=high if other white seltzers (White Claw, generic) could be confused with STELZ, or if guessing on shape alone. detected=true requires confidence >= 0.5.
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


def fetch_image_bytes(url: str, timeout: int = 20) -> tuple[bytes, str] | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if content_type not in ("image/jpeg", "image/png", "image/webp"):
            content_type = "image/jpeg"
        return r.content, content_type
    except Exception:
        return None


def parse_json(text: str) -> dict | None:
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
        data = p.read_bytes()
        mime = "image/jpeg"
        if p.suffix.lower() == ".png":
            mime = "image/png"
        elif p.suffix.lower() == ".webp":
            mime = "image/webp"
        parts.append(genai_types.Part.from_bytes(data=data, mime_type=mime))
    return parts


def detect_image(client, ref_parts, img_bytes: bytes, mime: str) -> dict:
    user_part = genai_types.Part.from_bytes(data=img_bytes, mime_type=mime)
    contents = [
        PROMPT,
        "Reference 1 (logo):", ref_parts[0],
        "Reference 2 (Hard Lemonade lineup):", ref_parts[1],
        "Reference 3 (lifestyle UGC):", ref_parts[2],
        "User post:", user_part,
    ]
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=MODEL, contents=contents)
            parsed = parse_json(resp.text or "")
            if parsed is None:
                return {"error": "unparseable", "raw": (resp.text or "")[:300]}
            return parsed
        except Exception as e:
            err = str(e)
            if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                time.sleep(2 ** attempt * 3)
                continue
            return {"error": "exception", "detail": str(e)[:300]}
    return {"error": "max_retries"}


def scrape_creator_batch(handles: list[str], posts_per_creator: int) -> dict:
    """Returns {handle: [posts]} dict."""
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
        # Profile scraper returns the profile dict containing latestPosts
        posts = item.get("latestPosts") or []
        if posts:
            by_handle[handle] = posts
        elif item.get("type") in ("Image", "Video", "Sidecar"):
            # Sometimes returns individual posts
            owner = item.get("ownerUsername")
            if owner:
                by_handle[owner].append(item)
    return by_handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=100, help="Top N candidates from lifestyle_creators.csv")
    parser.add_argument("--posts-per-creator", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--skip-scrape", action="store_true", help="Use existing scrape files, only detect")
    parser.add_argument("--min-score", type=float, default=15.0)
    args = parser.parse_args()

    csv_in = OUTPUT_DIR / "lifestyle_creators.csv"
    if not csv_in.exists():
        sys.exit(f"Missing {csv_in}. Run 04_discover_lifestyle.py first.")

    all_candidates = list(csv.DictReader(open(csv_in)))
    candidates = [
        c for c in all_candidates
        if float(c["composite_score"]) >= args.min_score
    ][: args.top]
    print(f"Selected {len(candidates)} candidates (top {args.top}, min_score {args.min_score})", file=sys.stderr)

    handles_to_scrape = []
    for c in candidates:
        handle = c["handle"]
        cache = SCRAPED_DIR / f"{handle}.json"
        if cache.exists() and not args.skip_scrape:
            continue
        handles_to_scrape.append(handle)

    if handles_to_scrape and not args.skip_scrape:
        print(f"\n--- SCRAPE PHASE: {len(handles_to_scrape)} new handles ---", file=sys.stderr)
        for i in range(0, len(handles_to_scrape), args.batch_size):
            batch = handles_to_scrape[i:i + args.batch_size]
            print(f"  batch {i//args.batch_size + 1}: {len(batch)} handles ({batch[0]}..{batch[-1]})", file=sys.stderr)
            by_handle = scrape_creator_batch(batch, args.posts_per_creator)
            for handle in batch:
                posts = by_handle.get(handle, [])
                (SCRAPED_DIR / f"{handle}.json").write_text(json.dumps(posts, ensure_ascii=False))
                if posts:
                    print(f"    @{handle}: {len(posts)} posts", file=sys.stderr)

    # DETECT PHASE
    print(f"\n--- DETECT PHASE ---", file=sys.stderr)
    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_ref_parts()
    print(f"Reference images loaded", file=sys.stderr)

    candidate_results = []
    total_images = 0
    total_hits = 0

    for ci, c in enumerate(candidates, 1):
        handle = c["handle"]
        scrape_file = SCRAPED_DIR / f"{handle}.json"
        if not scrape_file.exists():
            continue
        posts = json.loads(scrape_file.read_text())

        detect_file = DETECT_DIR / f"{handle}.json"
        if detect_file.exists():
            existing = json.loads(detect_file.read_text())
        else:
            existing = {}

        scanned = 0
        hits = 0
        hit_posts = []
        for post in posts:
            short = post.get("shortCode") or post.get("id")
            if not short:
                continue
            if short in existing:
                det = existing[short]
            else:
                img_url = post.get("displayUrl")
                if not img_url:
                    continue
                fetched = fetch_image_bytes(img_url)
                if not fetched:
                    det = {"error": "image_fetch_failed"}
                else:
                    img_bytes, mime = fetched
                    det = detect_image(client, ref_parts, img_bytes, mime)
                existing[short] = det
                time.sleep(0.2)
            scanned += 1
            if det.get("detected") and det.get("confidence", 0) >= 0.5:
                hits += 1
                hit_posts.append({
                    "shortCode": short,
                    "url": post.get("url"),
                    "product_line": det.get("product_line"),
                    "confidence": det.get("confidence"),
                    "context": det.get("context"),
                })

        detect_file.write_text(json.dumps(existing, ensure_ascii=False))

        total_images += scanned
        total_hits += hits
        hit_rate = hits / max(scanned, 1)
        if hits > 0 or ci % 10 == 0:
            print(f"  [{ci}/{len(candidates)}] @{handle}: {hits}/{scanned} hits ({hit_rate:.0%})", file=sys.stderr)

        candidate_results.append({
            "handle": handle,
            "full_name": c.get("full_name", ""),
            "composite_score": c.get("composite_score"),
            "groups_seen": c.get("groups_seen"),
            "posts_scanned": scanned,
            "stelz_hits": hits,
            "hit_rate": round(hit_rate, 3),
            "hit_post_urls": ";".join(p["url"] for p in hit_posts[:3] if p.get("url")),
            "sample_hit_context": (hit_posts[0]["context"] if hit_posts else ""),
            "lifestyle_groups": c.get("groups_seen"),
        })

    candidate_results.sort(key=lambda r: (r["stelz_hits"], r["hit_rate"]), reverse=True)

    out_csv = OUTPUT_DIR / "validated_stelz_creators.csv"
    if candidate_results:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(candidate_results[0].keys()))
            w.writeheader()
            w.writerows(candidate_results)

    creators_with_hits = sum(1 for r in candidate_results if r["stelz_hits"] > 0)
    print(f"\n=== VISUAL SCAN SUMMARY ===", file=sys.stderr)
    print(f"Candidates scanned: {len(candidate_results)}", file=sys.stderr)
    print(f"Total images: {total_images}", file=sys.stderr)
    print(f"Total STELZ hits: {total_hits}", file=sys.stderr)
    print(f"Creators with >=1 hit: {creators_with_hits}", file=sys.stderr)
    print(f"\nTop 20 by hit count:", file=sys.stderr)
    for r in candidate_results[:20]:
        if r["stelz_hits"] == 0:
            break
        print(f"  @{r['handle']:<28} hits={r['stelz_hits']:<3} rate={r['hit_rate']:.0%}  {r['full_name'][:35]}", file=sys.stderr)
    print(f"\nWrote: {out_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
