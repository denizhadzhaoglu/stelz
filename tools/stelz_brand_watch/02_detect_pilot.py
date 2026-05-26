#!/usr/bin/env python3
"""Pilot: run Gemini 2.5 Flash vision detection on scraped pilot images.

Reads .tmp/stelz_brand_watch/pilot_posts.json and the corresponding images,
asks Gemini to classify each image as containing STELZ Hard Lemonade,
STELZ Hard Seltzer, or none, with a confidence score and short context.

Writes results to pilot_detections.json and prints a summary.

Usage:
    python3 tools/stelz_brand_watch/02_detect_pilot.py
    python3 tools/stelz_brand_watch/02_detect_pilot.py --max 100
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv, dotenv_values
from google import genai
from google.genai import types as genai_types

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


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
    pa_env = PA_ROOT / ".env"
    if pa_env.exists():
        for k, v in dotenv_values(pa_env).items():
            if k == "GOOGLE_AI_API_KEY" and v and v.strip().startswith("AIza"):
                return v.strip()
    raise RuntimeError("No valid AIza-prefixed GOOGLE_AI_API_KEY found")

DATA_DIR = PA_ROOT / ".tmp" / "stelz_brand_watch"
REF_DIR = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"

MODEL = "gemini-2.5-flash"

REFERENCE_FILES = [
    "a09e6174600a45b9b4da970d4e2cc45a.png",
    "hardlemonade.webp",
    "stelz-smaak-tobias.jpg",
]

PROMPT = """You are a visual brand detector for STELZ, a Dutch alcoholic beverage brand.

STELZ has three product lines:
1. STELZ HARD LEMONADE: slim cans with white top half and colored bottom half (blue/cassis, orange, pink/strawberry), with the STELZ logo in dark blue text and an "S" inside a colored circle.
2. STELZ HARD SELTZER: white slim cans with patterned/illustrated artwork (fruit, abstract patterns), STELZ logo in dark blue with an orange/red "S" circle, "HARD SELTZER" written below.
3. STELZ HARD ICED TEA: slim cans, flavors include peach, lime, mango, often with fruit illustration and "HARD ICED TEA" written below the STELZ logo.

The standalone logo is the word "STELZ" (with umlaut on the E) in dark navy blue, arranged in a circle around an "S" inside a red/orange circle, with "HARD SELTZER" or "HARD LEMONADE" curved underneath.

I will show you 3 reference images first, then 1 user post image to evaluate.

For the user post image, return ONLY this JSON (no markdown, no prose):
{
  "detected": true | false,
  "product_line": "hard_lemonade" | "hard_seltzer" | "hard_iced_tea" | "logo_only" | "none",
  "confidence": 0.0 to 1.0,
  "context": "one short sentence: what is in the image and where the brand appears",
  "false_positive_risk": "low" | "medium" | "high"
}

Set false_positive_risk to "high" if the image contains other white seltzer cans (White Claw, generic seltzers) that could be confused with STELZ, or if you're guessing based on shape alone.

confidence reflects how certain you are that STELZ is actually in the image. detected=true requires confidence >= 0.5.
"""


def get_client() -> genai.Client:
    return genai.Client(
        api_key=_get_gemini_key(),
        http_options=genai_types.HttpOptions(timeout=60_000),
    )


def load_image_part(path: Path):
    mime = "image/jpeg"
    suffix = path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".avif":
        mime = "image/avif"
    data = path.read_bytes()
    return genai_types.Part.from_bytes(data=data, mime_type=mime)


def parse_json_response(text: str) -> dict | None:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def detect(client: genai.Client, ref_parts: list, image_path: Path) -> dict:
    user_part = load_image_part(image_path)
    contents = [
        PROMPT,
        "Reference image 1 (standalone logo):",
        ref_parts[0],
        "Reference image 2 (Hard Lemonade lineup):",
        ref_parts[1],
        "Reference image 3 (lifestyle UGC with both lines):",
        ref_parts[2],
        "User post image to evaluate:",
        user_part,
    ]

    last_err = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=MODEL, contents=contents)
            parsed = parse_json_response(resp.text or "")
            if parsed is None:
                return {"error": "unparseable_response", "raw": (resp.text or "")[:500]}
            return parsed
        except Exception as e:
            last_err = e
            err = str(e)
            if any(c in err for c in ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED")):
                wait = 2 ** attempt * 3
                print(f"  retry in {wait}s ({type(e).__name__})", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    return {"error": "max_retries_exceeded", "detail": str(last_err)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=100)
    args = parser.parse_args()

    posts_file = DATA_DIR / "pilot_posts.json"
    if not posts_file.exists():
        sys.exit(f"No pilot posts found at {posts_file}. Run 01_scrape_pilot.py first.")

    posts = json.loads(posts_file.read_text())
    posts_with_image = [p for p in posts if p.get("local_image")]
    print(f"{len(posts_with_image)} posts with local image (of {len(posts)} total)", file=sys.stderr)

    posts_with_image = posts_with_image[: args.max]

    client = get_client()
    ref_parts = [load_image_part(REF_DIR / f) for f in REFERENCE_FILES]
    print(f"Loaded {len(ref_parts)} reference images", file=sys.stderr)

    results = []
    for i, post in enumerate(posts_with_image, 1):
        img_path = PA_ROOT / post["local_image"]
        if not img_path.exists():
            continue
        print(f"[{i}/{len(posts_with_image)}] {post['shortCode']} @{post.get('ownerUsername','?')}", file=sys.stderr)
        try:
            detection = detect(client, ref_parts, img_path)
        except Exception as e:
            detection = {"error": "exception", "detail": str(e)}
        results.append({
            "shortCode": post["shortCode"],
            "url": post.get("url"),
            "ownerUsername": post.get("ownerUsername"),
            "caption": (post.get("caption") or "")[:200],
            "matched_hashtag": post.get("matched_hashtag"),
            "local_image": post["local_image"],
            "detection": detection,
        })
        time.sleep(0.3)

    out_file = DATA_DIR / "pilot_detections.json"
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2))

    total = len(results)
    hits = sum(1 for r in results if r["detection"].get("detected") is True)
    high_conf = sum(1 for r in results if (r["detection"].get("confidence") or 0) >= 0.8)
    by_line: dict = {}
    for r in results:
        line = r["detection"].get("product_line", "none")
        by_line[line] = by_line.get(line, 0) + 1
    errors = sum(1 for r in results if "error" in r["detection"])

    print("\n=== PILOT SUMMARY ===", file=sys.stderr)
    print(f"Total evaluated: {total}", file=sys.stderr)
    print(f"Detected: {hits} ({100*hits/total:.0f}%)" if total else "Detected: 0", file=sys.stderr)
    print(f"High confidence (>=0.8): {high_conf}", file=sys.stderr)
    print(f"Errors: {errors}", file=sys.stderr)
    print(f"By product line: {by_line}", file=sys.stderr)
    print(f"\nResults: {out_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
