#!/usr/bin/env python3
"""55_score_visual.py — Add visual-fingerprint layer to SRS.

For each candidate with SRS_layers_1-5 >= threshold (default 25 for STELZ
where current top SRS is ~35; raise to 50 once comment layer fills out):

  1. Build their content fingerprint (same shape as 54_visual_centroid.py)
  2. Embed via gemini-embedding-001
  3. Cosine-match against brand centroid
  4. Write resonance_scores.visual = cosine * 100
  5. Recompute total SRS with visual layer included

Quota-gated. Skips candidates with no usable text.

Usage:
    python3 tools/stelz_brand_watch/55_score_visual.py --brand stelz
    python3 tools/stelz_brand_watch/55_score_visual.py --brand stelz --srs-gate 25 --max 100
"""

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "dp33", str(PA_ROOT / "tools" / "stelz_brand_watch" / "33_detect_pending.py")
)
dp33 = importlib.util.module_from_spec(spec); spec.loader.exec_module(dp33)

EMBED_MODEL = "gemini-embedding-001"
BUCKET = "brand-watch-thumbnails"

# Weights for SRS recompute (must match 53_compute_resonance.py hot mode)
WEIGHTS = {
    "hot":  {"graph": 0.30, "hashtag": 0.20, "subculture": 0.15, "comment": 0.15, "geo": 0.10, "visual": 0.10},
    "warm": {"graph": 0.20, "hashtag": 0.30, "subculture": 0.20, "comment": 0.10, "geo": 0.10, "visual": 0.10},
    "cold": {"graph": 0.00, "hashtag": 0.55, "subculture": 0.20, "comment": 0.00, "geo": 0.25, "visual": 0.00},
}


def cosine(a, b):
    s = 0; sa = 0; sb_ = 0
    for x, y in zip(a, b):
        s += x*y; sa += x*x; sb_ += y*y
    return s / max((sa**0.5)*(sb_**0.5), 1e-9)


def load_centroid(sb, brand_slug):
    path = f"brand-centroids/{brand_slug}.json"
    try:
        r = sb.storage.from_(BUCKET).download(path)
        return json.loads(r.decode("utf-8") if isinstance(r, bytes) else r)
    except Exception as e:
        print(f"  centroid load failed: {e}", file=sys.stderr)
        return None


def build_fingerprint_for_handle(sb, brand_id, handle, platform):
    """Build content fingerprint via creator's posts. Returns text or empty."""
    c = (sb.table("creators")
         .select("id")
         .eq("brand_id", brand_id).eq("handle", handle).eq("platform", platform)
         .limit(1).execute()).data
    if not c: return ""
    cid = c[0]["id"]
    items = (sb.table("content_items")
             .select("caption, hashtags")
             .eq("brand_id", brand_id)
             .eq("creator_id", cid)
             .order("posted_at", desc=True)
             .limit(15).execute()).data or []
    caps = []
    tags = set()
    for it in items:
        c2 = (it.get("caption") or "").strip()
        if c2: caps.append(c2[:280])
        for h in (it.get("hashtags") or []):
            tags.add(h.lower())
    parts = []
    if caps: parts.append(" || ".join(caps))
    if tags: parts.append("Hashtags: " + " ".join("#" + t for t in sorted(tags)))
    return ("\n\n".join(parts))[:5000]


def process_brand(sb, brand_id, brand_slug, srs_gate, max_candidates, dry_run):
    print(f"\n[{brand_slug}]", file=sys.stderr)
    centroid_payload = load_centroid(sb, brand_slug)
    if not centroid_payload:
        print("  no centroid available — run 54_visual_centroid.py first", file=sys.stderr)
        return 0
    centroid = centroid_payload["centroid"]

    # Pull candidates above gate
    rows = (sb.table("resonance_scores")
            .select("creator_handle, platform, srs, graph, hashtag, subculture, comment, geo, bootstrap_mode")
            .eq("brand_id", brand_id)
            .gte("srs", srs_gate)
            .order("srs", desc=True)
            .limit(max_candidates)
            .execute()).data or []
    print(f"  candidates with SRS >= {srs_gate}: {len(rows)}", file=sys.stderr)
    if not rows:
        return 0

    client = genai.Client(api_key=dp33._get_gemini_key())
    updates = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        text = build_fingerprint_for_handle(sb, brand_id, r["creator_handle"], r["platform"])
        if not text or len(text) < 40:
            continue
        try:
            emb_r = client.models.embed_content(model=EMBED_MODEL, contents=text)
            v = list(emb_r.embeddings[0].values)
        except Exception as e:
            print(f"  [{i}] @{r['creator_handle']}: embed err {str(e)[:100]}", file=sys.stderr)
            continue
        sim = cosine(v, centroid)
        visual_score = max(0, min(100, sim * 100))
        # Recompute total SRS with visual layer
        mode = r.get("bootstrap_mode", "hot")
        w = WEIGHTS.get(mode, WEIGHTS["hot"])
        layers = {
            "graph": r.get("graph") or 0,
            "hashtag": r.get("hashtag") or 0,
            "subculture": r.get("subculture") or 0,
            "comment": r.get("comment") or 0,
            "geo": r.get("geo") or 0,
            "visual": visual_score,
        }
        new_srs = sum(layers[k] * w[k] for k in w)
        new_srs = max(0, min(100, new_srs))
        if not dry_run:
            sb.table("resonance_scores").update({
                "visual": round(visual_score, 2),
                "srs": round(new_srs, 2),
            }).eq("brand_id", brand_id).eq("platform", r["platform"]).eq("creator_handle", r["creator_handle"]).execute()
        updates += 1
        if i <= 20 or i % 25 == 0:
            print(f"  [{i:3}/{len(rows)}] @{r['creator_handle']:<28} sim={sim:.3f} → visual={visual_score:.1f} SRS:{r['srs']:.1f}→{new_srs:.1f}", file=sys.stderr)

    print(f"\n  scored {updates}/{len(rows)} in {time.time()-t0:.1f}s", file=sys.stderr)
    return updates


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--srs-gate", type=float, default=25.0,
                   help="Only score candidates with pre-visual SRS >= this. Default 25.")
    p.add_argument("--max", type=int, default=200, help="Max candidates per brand")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = sb.table("brands").select("id, slug").execute().data or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    for b in brands:
        process_brand(sb, b["id"], b["slug"], args.srs_gate, args.max, args.dry_run)


if __name__ == "__main__":
    main()
