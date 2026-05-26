#!/usr/bin/env python3
"""57_video_frame_detect.py — Per-frame TikTok detection.

Why: cover-frame detection misses STELZ that appears mid-video. Most TikToks
are 10-30 seconds. By sampling 5 frames evenly across the video and running
Gemini vision on each, we recover hits we'd otherwise miss.

Pipeline per video:
  1. yt-dlp downloads MP4 (no API key, public videos only)
  2. ffmpeg extracts 5 evenly-spaced frames as JPEG
  3. Gemini vision runs on each frame
  4. Aggregate: max(confidence) wins. That frame becomes the new
     stored_path (replacing the cover thumbnail).
  5. Upsert detection row with best frame's verdict.
  6. Cleanup: delete local video + spare frames.

Usage:
    # Process specific TikTok content_item:
    python3 tools/stelz_brand_watch/57_video_frame_detect.py --item-id <uuid>

    # Auto-scan: any TikTok with cover-detection=false OR tier_1 unscanned:
    python3 tools/stelz_brand_watch/57_video_frame_detect.py --auto --limit 20

    # Run for one URL directly (no DB needed):
    python3 tools/stelz_brand_watch/57_video_frame_detect.py --url <tiktok_url>
"""

import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "dp33", str(PA_ROOT / "tools" / "stelz_brand_watch" / "33_detect_pending.py")
)
dp33 = importlib.util.module_from_spec(spec); spec.loader.exec_module(dp33)

from google import genai

BUCKET = "brand-watch-thumbnails"
N_FRAMES = 5  # evenly spaced across video


def download_video(url: str, out_path: Path) -> bool:
    """yt-dlp the video to out_path. Best mp4 below 5 MB."""
    cmd = [
        "yt-dlp",
        "-q", "--no-warnings",
        "-f", "best[ext=mp4][filesize<10M]/best[filesize<10M]/best",
        "--no-playlist",
        "-o", str(out_path),
        url,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        if r.returncode != 0:
            print(f"    yt-dlp err: {r.stderr.decode()[:200]}", file=sys.stderr)
            return False
        if not out_path.exists() or out_path.stat().st_size < 1000:
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    yt-dlp timeout", file=sys.stderr)
        return False
    except Exception as e:
        print(f"    yt-dlp exc: {e}", file=sys.stderr)
        return False


def get_video_duration(video_path: Path) -> float:
    """Get duration in seconds via ffmpeg stderr parse (ffprobe may not be available)."""
    import re
    try:
        # Try ffprobe first (cleaner output)
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video_path)],
            capture_output=True, timeout=20,
        )
        if r.returncode == 0:
            v = r.stdout.decode().strip()
            if v: return float(v)
    except (FileNotFoundError, Exception):
        pass
    # Fallback: parse ffmpeg stderr (it logs "Duration: 00:00:14.92,...")
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True, timeout=20,
        )
        # ffmpeg writes to stderr even on success when only reading
        stderr = r.stderr.decode("utf-8", errors="replace")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        if m:
            h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mn * 60 + s
    except Exception:
        pass
    return 0


def extract_frames(video_path: Path, n_frames: int, out_dir: Path) -> list[Path]:
    """Extract n_frames evenly spaced. Returns list of paths to JPEG frames."""
    duration = get_video_duration(video_path)
    if duration <= 0:
        return []
    # 5 frames: at 10%, 30%, 50%, 70%, 90% of duration. Avoid intro/outro.
    timestamps = [duration * (0.1 + 0.8 * i / max(1, n_frames - 1))
                  for i in range(n_frames)]
    frames = []
    for i, ts in enumerate(timestamps):
        frame_path = out_dir / f"frame_{i:02d}.jpg"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(round(ts, 2)),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "3",  # high quality JPEG (1-31, lower=better)
            str(frame_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=20)
            if frame_path.exists() and frame_path.stat().st_size > 1000:
                frames.append(frame_path)
        except Exception as e:
            print(f"    ffmpeg frame {i} err: {e}", file=sys.stderr)
    return frames


async def detect_frames(client, refs, frames: list[Path]) -> tuple[dict | None, bytes | None]:
    """Run Gemini on each frame, return (best detection, best frame bytes).
    'Best' = highest confidence with detected=true; if none detected, return the highest-conf negative."""
    sem = asyncio.Semaphore(2)

    async def one(fp):
        with open(fp, "rb") as f:
            b = f.read()
        det = await dp33.detect_one(client, refs, b, sem)
        return fp, b, det

    results = await asyncio.gather(*[one(f) for f in frames])
    # Pick best
    best_det, best_bytes = None, None
    best_score = -1
    for fp, b, det in results:
        if det is None:
            continue
        score = (1000 if det.get("detected") else 0) + (det.get("confidence") or 0) * 100
        if score > best_score:
            best_score = score
            best_det = det
            best_bytes = b
    return best_det, best_bytes


def cache_best_frame(sb, brand_id: str, image_row_id: str, jpeg_bytes: bytes) -> str | None:
    """Upload the winning frame to Supabase storage, update content_images.stored_path.
    Returns the new stored_path."""
    h = hashlib.sha256(jpeg_bytes).hexdigest()
    path = f"stelz/{h[:2]}/{h}.jpg"
    try:
        sb.storage.from_(BUCKET).upload(path, jpeg_bytes, {"content-type": "image/jpeg", "upsert": "true"})
    except Exception:
        pass  # may already exist
    sb.table("content_images").update({"stored_path": path, "image_hash": h}).eq("id", image_row_id).execute()
    return path


async def process_video(sb, client, refs, item_id: str, url: str, image_row_id: str,
                         brand_id: str, force_redetect: bool = False) -> dict | None:
    """Full pipeline for one video. Returns detection result or None."""
    print(f"  ▸ {url[-30:]}", file=sys.stderr)
    if not force_redetect:
        # Skip if already detected
        existing = sb.table("detections").select("id").eq("brand_id", brand_id).eq("content_image_id", image_row_id).limit(1).execute().data
        if existing:
            print(f"    already detected, skipping (use --force to redetect)", file=sys.stderr)
            return None

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        video = tmp / "video.mp4"
        if not download_video(url, video):
            print(f"    download failed", file=sys.stderr)
            return None
        size_kb = video.stat().st_size / 1024
        duration = get_video_duration(video)
        print(f"    downloaded {size_kb:.0f}KB ({duration:.1f}s)", file=sys.stderr)

        frames = extract_frames(video, N_FRAMES, tmp)
        if not frames:
            print(f"    no frames extracted", file=sys.stderr)
            return None
        print(f"    extracted {len(frames)} frames", file=sys.stderr)

        det, best_bytes = await detect_frames(client, refs, frames)
        if not det:
            print(f"    all frames returned no detection (quota?)", file=sys.stderr)
            return None

        # Replace stored_path with best frame
        new_path = cache_best_frame(sb, brand_id, image_row_id, best_bytes)

        # Insert detection
        sb.table("detections").insert({
            "brand_id": brand_id, "content_image_id": image_row_id,
            "model": dp33.MODEL + "+video_frames",
            "prompt_version": dp33.PROMPT_VERSION,
            "detected": bool(det.get("detected")),
            "product_line": det.get("product_line"),
            "confidence": det.get("confidence"),
            "size_in_frame": det.get("size_in_frame"),
            "is_primary_subject": det.get("is_primary_subject"),
            "context": (det.get("context") or "") + f" [frame analysis · {len(frames)} frames]",
            "false_positive_risk": det.get("false_positive_risk"),
        }).execute()

        c = det.get("confidence") or 0
        marker = "★ HIT" if det.get("detected") and c >= 0.5 else "·"
        print(f"    {marker} det={det.get('detected')} conf={c} prod={det.get('product_line')}", file=sys.stderr)
        if det.get("detected") and c >= 0.5:
            print(f"      ctx: {(det.get('context') or '')[:200]}", file=sys.stderr)
        return det


def pick_candidates(sb, brand_id: str, limit: int) -> list[dict]:
    """Auto mode: pick TikTok content_items where cover detection was negative
    (or tier_1 unscanned). Returns rows with item_id, url, image_id."""
    # 1. TikTok content_items with at least one negative detection (no STELZ in cover)
    rows = sb.from_("v_detections_full").select(
        "detection_id, content_type, post_url, image_url, stored_path, creator_handle, creator_tier, confidence, detected, model"
    ).eq("brand_id", brand_id).eq("content_type", "tiktok").eq("detected", False).limit(limit * 3).execute().data or []

    # We need image_id but view doesn't expose it — fetch via post_url uniquely identifies the item.
    # Easier: lookup content_image_id from detections table.
    out = []
    for r in rows:
        if "video_frames" in (r.get("model") or ""):
            continue  # already video-frame-analyzed
        # lookup content_image_id via detection_id
        d = sb.table("detections").select("content_image_id").eq("id", r["detection_id"]).maybe_single().execute().data
        if not d: continue
        out.append({
            "item_id": None,  # not used downstream
            "url": r["post_url"],
            "image_id": d["content_image_id"],
            "handle": r["creator_handle"],
            "tier": r["creator_tier"],
        })
        if len(out) >= limit: break
    return out


async def main_async(args):
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", args.brand_slug).execute().data[0]["id"]
    client = genai.Client(api_key=dp33._get_gemini_key())
    refs = dp33.load_refs(args.brand_slug)

    if args.url:
        # Single URL mode — no DB row exists yet
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video = tmp / "video.mp4"
            if not download_video(args.url, video):
                print("download failed", file=sys.stderr); return
            print(f"video {video.stat().st_size/1024:.0f}KB", file=sys.stderr)
            frames = extract_frames(video, N_FRAMES, tmp)
            print(f"frames {len(frames)}", file=sys.stderr)
            det, best_bytes = await detect_frames(client, refs, frames)
            if det:
                c = det.get("confidence") or 0
                marker = "★ HIT" if det.get("detected") and c >= 0.5 else "no hit"
                print(f"\n{marker} det={det.get('detected')} conf={c} prod={det.get('product_line')}", file=sys.stderr)
                print(f"ctx: {(det.get('context') or '')[:300]}", file=sys.stderr)
            else:
                print("no detection (quota?)", file=sys.stderr)
        return

    if args.item_id:
        # Specific item
        row = sb.table("content_items").select("id, url").eq("id", args.item_id).maybe_single().execute().data
        if not row: print(f"item {args.item_id} not found", file=sys.stderr); return
        img = sb.table("content_images").select("id").eq("content_item_id", row["id"]).limit(1).execute().data
        if not img: print(f"no image for item", file=sys.stderr); return
        await process_video(sb, client, refs, row["id"], row["url"], img[0]["id"], brand_id, force_redetect=args.force)
        return

    # Auto mode
    candidates = pick_candidates(sb, brand_id, args.limit)
    print(f"\n{len(candidates)} candidates (tiktok, cover-negative, not yet frame-analyzed)", file=sys.stderr)
    t0 = time.time()
    hits = 0
    for i, c in enumerate(candidates, 1):
        print(f"\n[{i}/{len(candidates)}] @{c['handle']} ({c.get('tier','—')})", file=sys.stderr)
        det = await process_video(sb, client, refs, None, c["url"], c["image_id"], brand_id, force_redetect=args.force)
        if det and det.get("detected") and (det.get("confidence") or 0) >= 0.5:
            hits += 1
    print(f"\n=== VIDEO FRAME DETECT COMPLETE in {time.time()-t0:.1f}s ===", file=sys.stderr)
    print(f"processed: {len(candidates)} · new STELZ hits ≥0.5: {hits}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand-slug", default="stelz")
    p.add_argument("--item-id", help="UUID of a content_items row to process")
    p.add_argument("--url", help="Process a single TikTok URL directly (no DB)")
    p.add_argument("--auto", action="store_true", help="Auto-pick TikTok cover-negative items")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--force", action="store_true", help="Redetect even if already analyzed")
    args = p.parse_args()
    if not (args.item_id or args.url or args.auto):
        p.print_help(); return
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
