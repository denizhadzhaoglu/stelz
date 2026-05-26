#!/usr/bin/env python3
"""Shadow-run a candidate detection prompt against past images and compare
with the production detection's verdict.

Workflow:
  1. Insert a row into public.prompt_experiments with the candidate
     prompt body, target model, optional brand restriction.
  2. Run this script with --experiment-id X.
  3. Script pulls a sample of content_images (default 100) with at
     least one production detection, runs the candidate prompt, and
     records the side-by-side outcome in prompt_experiment_results.
  4. Read v_prompt_experiment_summary for the agreement % and the
     "new positives" / "new negatives" counts that show where the
     candidate prompt would change production behavior.

This lets us evaluate prompt changes before promoting them, and gives
us auditable data on detection quality.

Usage:
    python3 tools/stelz_brand_watch/46_run_prompt_experiment.py --experiment-id <uuid>
    python3 tools/stelz_brand_watch/46_run_prompt_experiment.py --experiment-id <uuid> --sample 200 --dry-run
"""

import argparse
import asyncio
import io
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values, load_dotenv
from google import genai
from google.genai import types as genai_types
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

STORAGE_BUCKET = "brand-watch-thumbnails"
DEFAULT_DIM = 512


def _get_gemini_key() -> str:
    env_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if env_key.startswith("AIza"): return env_key
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


def resize(b: bytes, max_dim: int = DEFAULT_DIM) -> bytes:
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def fetch_bytes(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=15)
        return r.content if r.status_code == 200 else None
    except Exception:
        return None


def load_brand_refs(brand_slug: str):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _brand_refs import load_brand_refs
    return [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg")
            for b in load_brand_refs(brand_slug, max_dim=DEFAULT_DIM, include_training=True)]


async def detect(client, prompt: str, ref_parts, img_bytes, semaphore, model: str):
    async with semaphore:
        user = genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        contents = [prompt]
        for i, r in enumerate(ref_parts, 1):
            contents.append(f"Reference {i}:")
            contents.append(r)
        contents.extend(["Post to evaluate:", user])
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(model=model, contents=contents)
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

    exp = sb.table("prompt_experiments").select("*").eq("id", args.experiment_id).maybe_single().execute().data
    if not exp:
        sys.exit(f"No experiment {args.experiment_id}")

    brand_row = sb.table("brands").select("slug").eq("id", exp["brand_id"]).execute().data[0]
    brand_slug = brand_row["slug"]
    print(f"Running experiment '{exp['name']}' for brand {brand_slug}", file=sys.stderr)

    # Mark running
    sb.table("prompt_experiments").update({"status": "running"}).eq("id", exp["id"]).execute()

    # Sample: get N images that have a production detection on this brand.
    dets = (sb.table("detections")
            .select("id, content_image_id, detected, confidence")
            .eq("brand_id", exp["brand_id"])
            .lt("prompt_version", 100)  # exclude zoom-verified
            .order("id", desc=True)
            .limit(args.sample).execute().data) or []
    if not dets:
        print("No production detections to compare against.", file=sys.stderr)
        return

    # Pull image urls
    img_ids = [d["content_image_id"] for d in dets]
    images_by_id = {}
    for i in range(0, len(img_ids), 200):
        r = sb.table("content_images").select("id, image_url, stored_path").in_("id", img_ids[i:i+200]).execute().data or []
        for row in r:
            images_by_id[row["id"]] = row

    client = genai.Client(api_key=_get_gemini_key(), http_options=genai_types.HttpOptions(timeout=60_000))
    ref_parts = load_brand_refs(brand_slug)
    if not ref_parts:
        sys.exit("No brand reference images")
    sem = asyncio.Semaphore(args.concurrency)

    async def one(det):
        img = images_by_id.get(det["content_image_id"])
        if not img: return None
        url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{img['stored_path']}"
               if img.get("stored_path") else img.get("image_url"))
        if not url: return None
        raw_img = fetch_bytes(url)
        if not raw_img: return None
        result = await detect(client, exp["prompt"], ref_parts, resize(raw_img), sem, exp["model"])
        return (det, result)

    print(f"Detecting {len(dets)} samples with candidate prompt", file=sys.stderr)
    out = await asyncio.gather(*[one(d) for d in dets])

    inserts = []
    agreements = 0
    new_pos = 0
    new_neg = 0
    for pair in out:
        if not pair: continue
        det, result = pair
        if not result: continue
        cand_det = bool(result.get("detected"))
        cand_conf = result.get("confidence")
        agreed = cand_det == bool(det["detected"])
        if agreed: agreements += 1
        if cand_det and not det["detected"]: new_pos += 1
        if not cand_det and det["detected"]: new_neg += 1
        inserts.append({
            "experiment_id": exp["id"],
            "content_image_id": det["content_image_id"],
            "detected": cand_det,
            "confidence": cand_conf,
            "product_line": result.get("product_line"),
            "size_in_frame": result.get("size_in_frame"),
            "is_primary_subject": result.get("is_primary_subject"),
            "raw": result,
            "prod_detection_id": det["id"],
            "prod_detected": bool(det["detected"]),
            "prod_confidence": det.get("confidence"),
            "agreed": agreed,
        })

    if args.dry_run:
        print(f"DRY: {len(inserts)} samples, {agreements} agreed, "
              f"{new_pos} new positives, {new_neg} new negatives", file=sys.stderr)
        return

    for i in range(0, len(inserts), 200):
        sb.table("prompt_experiment_results").upsert(
            inserts[i:i+200], on_conflict="experiment_id,content_image_id",
        ).execute()

    sb.table("prompt_experiments").update({"status": "done"}).eq("id", exp["id"]).execute()

    pct = round(100.0 * agreements / max(len(inserts), 1), 1)
    print(f"\n=== EXPERIMENT '{exp['name']}' DONE ===", file=sys.stderr)
    print(f"  Samples: {len(inserts)}", file=sys.stderr)
    print(f"  Agreement: {agreements} ({pct}%)", file=sys.stderr)
    print(f"  New positives (candidate found, prod missed): {new_pos}", file=sys.stderr)
    print(f"  New negatives (candidate rejected, prod accepted): {new_neg}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--experiment-id", required=True)
    p.add_argument("--sample", type=int, default=100)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
