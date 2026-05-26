#!/usr/bin/env python3
"""Turn moderator decisions into few-shot training data for Pro verify.

The moderator UI in dashboard/moderator.html lets the user swipe through
detections and decide "STELZ visible" (confirm) or "not visible" (reject).
Each decision sets detections.verified_by = 'moderator_review' plus the
is_false_positive flag.

This script:
1. Pulls the N most recent moderator-confirmed positives (real STELZ).
2. Pulls the N most recent moderator-rejected hits (false positives).
3. Downloads the images and stores them under reference-images/training/
   as fewshot_pos_<n>.jpg / fewshot_neg_<n>.jpg.
4. Writes a manifest in reference-images/training/manifest.json with the
   image-id -> label mapping, plus the model's original verdict and
   the moderator decision (so Pro can see WHY the model was wrong).

The Pro verify prompt loader (in 17_verify_with_pro.py) is updated separately
to prepend these few-shot examples to its context, so the next batch of
verifications benefits from yesterday's moderator work.

Usage:
    python3 tools/stelz_brand_watch/29_train_from_moderator.py
    python3 tools/stelz_brand_watch/29_train_from_moderator.py --pos 12 --neg 12
"""

import argparse
import io
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

REF_DIR  = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"
TRAIN_DIR = REF_DIR / "training"
STORAGE_BUCKET = "brand-watch-thumbnails"


def upload_to_storage(sb, brand_slug, filename, data):
    """Upload a training image to Storage at references/<brand>/training/<filename>.
    upsert=true so re-runs overwrite the previous batch cleanly."""
    path = f"references/{brand_slug}/training/{filename}"
    try:
        sb.storage.from_(STORAGE_BUCKET).upload(
            path=path, file=data,
            file_options={"content-type": "image/jpeg" if filename.endswith(".jpg") else "application/json",
                          "upsert": "true"},
        )
        return path
    except Exception as e:
        # supabase-py raises on duplicate; the file_options upsert should prevent it,
        # but we belt-and-suspenders by retrying with explicit remove+upload.
        if "already exists" in str(e).lower() or "Duplicate" in str(e):
            try:
                sb.storage.from_(STORAGE_BUCKET).remove([path])
                sb.storage.from_(STORAGE_BUCKET).upload(
                    path=path, file=data,
                    file_options={"content-type": "image/jpeg" if filename.endswith(".jpg") else "application/json"},
                )
                return path
            except Exception as e2:
                print(f"  storage retry err {filename}: {e2}", file=sys.stderr)
        else:
            print(f"  storage err {filename}: {e}", file=sys.stderr)
        return None


def wipe_remote_training_set(sb, brand_slug):
    """Remove the old training images from Storage so the new batch fully replaces them.
    Keeps the main packshots in references/<brand>/ untouched."""
    folder = f"references/{brand_slug}/training"
    try:
        existing = sb.storage.from_(STORAGE_BUCKET).list(folder, {"limit": 200}) or []
        to_remove = [f"{folder}/{f['name']}" for f in existing
                     if f.get("name") and not f["name"].startswith(".")]
        if to_remove:
            sb.storage.from_(STORAGE_BUCKET).remove(to_remove)
            print(f"  wiped {len(to_remove)} old training files from Storage", file=sys.stderr)
    except Exception as e:
        print(f"  wipe err (proceeding): {e}", file=sys.stderr)


def resize_jpeg(b, max_dim=768, quality=85):
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return out.getvalue()


def fetch_image(d):
    url = (f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{STORAGE_BUCKET}/{d['stored_path']}"
           if d.get("stored_path") else d.get("image_url"))
    if not url:
        return None
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return resize_jpeg(r.content)


def fetch_moderator_decisions(sb, brand_id, decision_kind, limit):
    """decision_kind: 'positive' (real STELZ) or 'negative' (false positive).

    Pulls moderator-reviewed detections (verified_by='moderator_review'),
    which is the unified tag used by BOTH the Moderator page AND the inline
    reject/confirm buttons on the main dashboard.

    Within negatives, prioritize HIGH_SIGNAL rejections: cases where the user
    rejected a hit that the model+Pro chain had classified as trusted. These
    are the most valuable negatives because they teach the model where its
    own confident predictions fail.
    """
    # Use the explicit moderation_label column when populated, fall back
    # to is_false_positive for legacy rows. Critically: plausible-labeled
    # detections are excluded — they would teach the model to be loose
    # on positives or harsh on negatives. Only confirmed/rejected drives
    # training.
    target_label = "rejected" if decision_kind == "negative" else "confirmed"
    is_fp = (decision_kind == "negative")
    q = (
        sb.table("v_detections_full")
        .select("detection_id, model, product_line, confidence, size_in_frame, "
                "is_primary_subject, context, post_caption, post_url, "
                "image_url, stored_path, is_false_positive, creator_handle, "
                "verified, verified_by, notes, moderation_label")
        .eq("brand_id", brand_id)
        .eq("detected", True)
        .eq("verified_by", "moderator_review")
        .or_(f"moderation_label.eq.{target_label},and(moderation_label.is.null,is_false_positive.eq.{str(is_fp).lower()})")
        .limit(limit * 4)
    )
    res = q.execute()
    rows = res.data or []
    # Hard filter: drop anything explicitly labeled 'plausible'
    rows = [r for r in rows if r.get("moderation_label") != "plausible"]

    if is_fp:
        # Sort: HIGH_SIGNAL rejections first, then rest by recency.
        # The dashboard tags rejections of trusted hits with "HIGH_SIGNAL" in notes.
        def sort_key(r):
            notes = r.get("notes") or ""
            is_high = "HIGH_SIGNAL" in notes
            return (0 if is_high else 1, r.get("detection_id") or "")
        rows.sort(key=sort_key)
    return rows[:limit]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pos", type=int, default=8, help="Number of positive examples")
    p.add_argument("--neg", type=int, default=8, help="Number of negative examples")
    p.add_argument("--brand-slug", dest="brand_slug", default="stelz",
                   help="Brand to refresh training set for")
    p.add_argument("--no-upload", action="store_true",
                   help="Skip Storage upload (local-only run for debugging)")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_row = sb.table("brands").select("id, slug").eq("slug", args.brand_slug).execute().data
    if not brand_row:
        sys.exit(f"No brand with slug={args.brand_slug}")
    brand_id = brand_row[0]["id"]
    brand_slug = brand_row[0]["slug"]

    TRAIN_DIR.mkdir(parents=True, exist_ok=True)

    pos = fetch_moderator_decisions(sb, brand_id, "positive", args.pos)
    neg = fetch_moderator_decisions(sb, brand_id, "negative", args.neg)
    print(f"[{brand_slug}] Found {len(pos)} positive + {len(neg)} negative moderator decisions "
          f"(plausible excluded)", file=sys.stderr)

    manifest = {"positive": [], "negative": []}

    # Wipe old local training files (we rebuild from latest moderator session)
    for f in TRAIN_DIR.glob("fewshot_*.jpg"):
        f.unlink()
    # Also wipe Storage so the new batch fully replaces the previous one
    if not args.no_upload:
        wipe_remote_training_set(sb, brand_slug)

    for i, d in enumerate(pos):
        try:
            b = fetch_image(d)
        except Exception as e:
            print(f"  pos {i}: fetch err {e}", file=sys.stderr)
            continue
        if not b:
            continue
        fname = f"fewshot_pos_{i:02d}.jpg"
        (TRAIN_DIR / fname).write_bytes(b)
        if not args.no_upload:
            upload_to_storage(sb, brand_slug, fname, b)
        manifest["positive"].append({
            "file": fname,
            "creator": d["creator_handle"],
            "model_said": {
                "product_line": d.get("product_line"),
                "confidence": d.get("confidence"),
                "size_in_frame": d.get("size_in_frame"),
                "context": d.get("context"),
            },
            "moderator_verdict": "STELZ is visible in this image — correct positive",
        })

    for i, d in enumerate(neg):
        try:
            b = fetch_image(d)
        except Exception as e:
            print(f"  neg {i}: fetch err {e}", file=sys.stderr)
            continue
        if not b:
            continue
        fname = f"fewshot_neg_{i:02d}.jpg"
        (TRAIN_DIR / fname).write_bytes(b)
        if not args.no_upload:
            upload_to_storage(sb, brand_slug, fname, b)
        is_high_signal = "HIGH_SIGNAL" in (d.get("notes") or "")
        manifest["negative"].append({
            "file": fname,
            "creator": d["creator_handle"],
            "high_signal": is_high_signal,
            "model_said": {
                "product_line": d.get("product_line"),
                "confidence": d.get("confidence"),
                "size_in_frame": d.get("size_in_frame"),
                "context": d.get("context"),
            },
            "moderator_verdict": (
                "CRITICAL FALSE POSITIVE: The model AND the Pro verify chain BOTH "
                "marked this as a trusted STELZ detection — but a human moderator "
                "rejected it. STELZ is NOT visible. The diagnostic features the "
                "model claimed to see are not actually there. Be especially "
                "skeptical of this pattern."
                if is_high_signal
                else "STELZ is NOT visible — model hallucinated. Do not detect."
            ),
        })

    manifest_json = json.dumps(manifest, indent=2)
    (TRAIN_DIR / "manifest.json").write_text(manifest_json)
    if not args.no_upload:
        upload_to_storage(sb, brand_slug, "manifest.json", manifest_json.encode("utf-8"))
    print(f"\n=== TRAINING SET REFRESHED for {brand_slug} ===", file=sys.stderr)
    print(f"  Positives saved: {len(manifest['positive'])}", file=sys.stderr)
    print(f"  Negatives saved: {len(manifest['negative'])}", file=sys.stderr)
    print(f"  Local path:   {TRAIN_DIR}", file=sys.stderr)
    if not args.no_upload:
        print(f"  Storage path: references/{brand_slug}/training/", file=sys.stderr)
    print(f"  Next Pro verify run will pick these up as few-shot examples", file=sys.stderr)


if __name__ == "__main__":
    main()
