#!/usr/bin/env python3
"""54_visual_centroid.py — Build content-fingerprint centroid for a brand.

NOTE on naming: the original plan called this 'visual centroid' using Gemini
multimodal embeddings. The public Gemini API only exposes text embeddings;
multimodal requires Vertex AI service-account auth (heavier setup). So this
implementation uses TEXT embeddings of each tier_1 creator's content
fingerprint — captions + hashtags + the Gemini-generated detection contexts
of their confirmed STELZ hits. The detection contexts ARE Gemini-generated
visual descriptions, so we get a visual proxy through text.

Centroid = mean of tier_1 fingerprint embeddings. Stored once per brand.
Refreshed monthly. Reused by 55_score_visual.py.

Storage: writes JSON to Supabase storage at brand-centroids/{brand_slug}.json
(simple, no new table needed).

Usage:
    python3 tools/stelz_brand_watch/54_visual_centroid.py
    python3 tools/stelz_brand_watch/54_visual_centroid.py --brand stelz --top-tier 20
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# Reuse Gemini key helper from 33_detect_pending
import importlib.util
spec = importlib.util.spec_from_file_location(
    "dp33", str(PA_ROOT / "tools" / "stelz_brand_watch" / "33_detect_pending.py")
)
dp33 = importlib.util.module_from_spec(spec); spec.loader.exec_module(dp33)

EMBED_MODEL = "gemini-embedding-001"
BUCKET = "brand-watch-thumbnails"  # reuse existing bucket, prefix centroids


def build_fingerprint(sb, brand_id, creator_id, max_items=25, max_contexts=40):
    """Build a single text blob representing a creator's content fingerprint.

    Sources combined:
      - Up to 25 recent caption texts
      - Hashtags from those posts (deduped)
      - Up to 40 detection.context strings from their confirmed STELZ hits
    """
    parts = []

    # Captions + hashtags
    items = (sb.table("content_items")
             .select("caption, hashtags")
             .eq("brand_id", brand_id)
             .eq("creator_id", creator_id)
             .order("posted_at", desc=True)
             .limit(max_items).execute()).data or []
    caps = []
    tags = set()
    for it in items:
        c = (it.get("caption") or "").strip()
        if c: caps.append(c[:280])
        for h in (it.get("hashtags") or []):
            tags.add(h.lower())
    if caps: parts.append(" || ".join(caps))
    if tags: parts.append("Hashtags: " + " ".join("#" + t for t in sorted(tags)))

    # Detection contexts (these are Gemini-generated visual descriptions)
    contexts = []
    img_ids = []
    item_ids = [it["id"] for it in (sb.table("content_items").select("id").eq("brand_id", brand_id).eq("creator_id", creator_id).execute().data or [])]
    if item_ids:
        for i in range(0, len(item_ids), 200):
            r = sb.table("content_images").select("id").in_("content_item_id", item_ids[i:i+200]).execute().data or []
            img_ids.extend(im["id"] for im in r)
    if img_ids:
        for i in range(0, len(img_ids), 200):
            dets = (sb.table("detections")
                    .select("context, confidence, is_false_positive")
                    .eq("brand_id", brand_id)
                    .in_("content_image_id", img_ids[i:i+200])
                    .eq("detected", True)
                    .execute()).data or []
            for d in dets:
                if d.get("is_false_positive"): continue
                if (d.get("confidence") or 0) < 0.5: continue
                ctx = (d.get("context") or "").strip()
                if ctx: contexts.append(ctx[:300])
            if len(contexts) >= max_contexts: break
        if contexts:
            parts.append("STELZ visual contexts: " + " || ".join(contexts[:max_contexts]))

    text = "\n\n".join(parts)
    return text[:6000]  # safety cap


def embed_text(client, text):
    """Returns list[float] embedding (768-dim) or None."""
    if not text or len(text) < 20:
        return None
    try:
        r = client.models.embed_content(model=EMBED_MODEL, contents=text)
        return list(r.embeddings[0].values)
    except Exception as e:
        print(f"  embed failed: {str(e)[:140]}", file=sys.stderr)
        return None


def vector_mean(vectors):
    if not vectors: return None
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    return [x / len(vectors) for x in out]


def vector_norm(v):
    s = sum(x*x for x in v) ** 0.5
    return s or 1.0


def process_brand(sb, brand_id, brand_slug, top_tier, dry_run):
    t0 = time.time()
    print(f"\n[{brand_slug}]", file=sys.stderr)

    # Pick top tier_1 creators by clear_visibility_hits
    stats = (sb.table("v_creator_stats")
             .select("creator_id, handle, clear_visibility_hits")
             .eq("brand_id", brand_id)
             .eq("tier", "tier_1")
             .order("clear_visibility_hits", desc=True)
             .limit(top_tier).execute()).data or []
    if len(stats) < 3:
        print(f"  too few tier_1 creators ({len(stats)}); need ≥3 for a meaningful centroid", file=sys.stderr)
        return None
    print(f"  using top {len(stats)} tier_1 creators by clear hits", file=sys.stderr)

    client = genai.Client(api_key=dp33._get_gemini_key())

    vectors, embedded_handles = [], []
    for c in stats:
        text = build_fingerprint(sb, brand_id, c["creator_id"])
        if not text:
            print(f"  @{c['handle']}: empty fingerprint, skip", file=sys.stderr)
            continue
        v = embed_text(client, text)
        if not v:
            continue
        vectors.append(v)
        embedded_handles.append(c["handle"])
        print(f"  @{c['handle']:<25} ({c['clear_visibility_hits']} hits) → embedded ({len(text)} chars)", file=sys.stderr)

    if not vectors:
        print("  no successful embeddings; centroid not built", file=sys.stderr)
        return None

    centroid = vector_mean(vectors)
    norm = vector_norm(centroid)

    payload = {
        "brand_id": brand_id,
        "brand_slug": brand_slug,
        "model": EMBED_MODEL,
        "dim": len(centroid),
        "n_creators": len(vectors),
        "handles": embedded_handles,
        "centroid": centroid,
        "centroid_norm": norm,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    blob = json.dumps(payload).encode("utf-8")

    if not dry_run:
        path = f"brand-centroids/{brand_slug}.json"
        try:
            sb.storage.from_(BUCKET).upload(path, blob, {"content-type":"application/json","upsert":"true"})
        except Exception:
            # Already exists — re-upload via update
            try:
                sb.storage.from_(BUCKET).update(path, blob, {"content-type":"application/json"})
            except Exception as e:
                print(f"  storage upload failed: {e}", file=sys.stderr)
                return None
        print(f"\n  centroid stored at {BUCKET}/{path}", file=sys.stderr)

    print(f"  built from {len(vectors)} creators, dim={len(centroid)}, took {time.time()-t0:.1f}s", file=sys.stderr)
    return payload


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--top-tier", type=int, default=20, help="Top N tier_1 creators by clear_visibility_hits")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = sb.table("brands").select("id, slug").execute().data or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    if not brands:
        print("No brands selected", file=sys.stderr); return
    for b in brands:
        process_brand(sb, b["id"], b["slug"], args.top_tier, args.dry_run)


if __name__ == "__main__":
    main()
