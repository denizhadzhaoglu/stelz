"""Video frame brand detection — visibility-first.

This is "step 1" of the focused video pipeline. Goal of this iteration:
   See exactly how many videos we receive, how many we successfully
   download, how many frames we extract, and where each one is dropped.

Every video attempt writes a doc to /brands/{id}/videoLog/{auto} so the
Debug tab can show the funnel. No yt-dlp yet, no advanced frame analysis
yet — just visibility.

Cascade for each frame: detect_image (cache → OCR → embedding → Gemini).
"""
from __future__ import annotations
import io
import logging
import os
import tempfile
import time
from typing import Any

import requests
from google.cloud.firestore import SERVER_TIMESTAMP

from lib import fs, usage
from handlers import detect_image

log = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB
FRAME_SAMPLE_POINTS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def _video_log(brand_id: str, post_id: str, video_url: str, stage: str, status: str, extra: dict | None = None) -> None:
    """Write a row to /brands/{id}/videoLog with the funnel state.
    stage is one of: received | download | frames | analyse | done."""
    try:
        fs.brand_doc(brand_id).collection("videoLog").add({
            "postId": post_id,
            "videoUrl": video_url,
            "stage": stage,
            "status": status,
            "createdAt": SERVER_TIMESTAMP,
            **(extra or {}),
        })
    except Exception:
        pass


def _is_web_page_url(url: str) -> bool:
    """TikTok web URLs (tiktok.com/@user/video/id) need yt-dlp to resolve to
    a CDN MP4. Direct CDN URLs (instagram CDN, raw .mp4) can stream directly."""
    u = (url or "").lower()
    return "tiktok.com" in u and "/video/" in u


def _download_with_ytdlp(url: str) -> tuple[bytes | None, str, int]:
    """Use yt-dlp to fetch a TikTok video. Picks smallest acceptable MP4."""
    try:
        import yt_dlp
    except Exception as e:
        log.error(f"yt_dlp import failed: {e}")
        return None, f"err:yt_dlp_import:{type(e).__name__}", 0

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "video.%(ext)s")
        ydl_opts = {
            "outtmpl": out_path,
            "format": "best[ext=mp4][filesize<25M]/best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "max_filesize": MAX_VIDEO_BYTES,
            "socket_timeout": 30,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            log.error(f"yt-dlp download failed: {e}")
            return None, f"err:ytdlp:{type(e).__name__}", 0

        for fname in os.listdir(tmpdir):
            if fname.startswith("video."):
                p = os.path.join(tmpdir, fname)
                try:
                    with open(p, "rb") as f:
                        data = f.read()
                    if len(data) > MAX_VIDEO_BYTES:
                        return None, "too_large", len(data)
                    return data, "ok", len(data)
                except Exception as e:
                    return None, f"err:read:{type(e).__name__}", 0
        return None, "no_output_file", 0


def _download_video(url: str) -> tuple[bytes | None, str, int]:
    """Returns (bytes_or_None, reason, bytes_downloaded). reason is a short
    debug tag describing why a download failed when bytes is None."""
    if _is_web_page_url(url):
        return _download_with_ytdlp(url)
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            buf = io.BytesIO()
            total = 0
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_VIDEO_BYTES:
                    return None, "too_large", total
                buf.write(chunk)
            return buf.getvalue(), "ok", total
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        return None, f"http_{code}", 0
    except requests.Timeout:
        return None, "timeout", 0
    except Exception as e:
        log.error(f"video download failed: {e}")
        return None, f"err:{type(e).__name__}", 0


def _extract_frames(video_bytes: bytes) -> tuple[list[tuple[int, bytes]], dict]:
    """Returns (frames, info). info contains diagnostic details (total_frames,
    fps, duration_seconds, decode_errors)."""
    info: dict[str, Any] = {"total_frames": 0, "fps": 0.0, "duration_seconds": 0.0, "decode_errors": 0}
    try:
        import cv2
    except Exception as e:
        log.error(f"cv2 import failed: {e}")
        info["cv2_error"] = str(e)
        return [], info

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        path = tmp.name

    out: list[tuple[int, bytes]] = []
    try:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            info["open_failed"] = True
            return [], info
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        info["total_frames"] = total_frames
        info["fps"] = round(fps, 2)
        if total_frames <= 0:
            return [], info
        if fps > 0:
            info["duration_seconds"] = round(total_frames / fps, 1)

        for i, pct in enumerate(FRAME_SAMPLE_POINTS):
            target = min(total_frames - 1, int(total_frames * pct))
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, frame = cap.read()
            if not ok or frame is None:
                info["decode_errors"] = info["decode_errors"] + 1
                continue
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok:
                out.append((i, buf.tobytes()))
        cap.release()
    except Exception as e:
        log.error(f"frame extract failed: {e}")
        info["extract_error"] = str(e)[:200]
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    return out, info


def run(brand_id: str, post_id: str, video_url: str) -> dict[str, Any]:
    t_start = time.time()
    _video_log(brand_id, post_id, video_url, "received", "ok")

    if usage.budget_exhausted(brand_id):
        _video_log(brand_id, post_id, video_url, "received", "skipped_budget")
        return {"status": "skip", "reason": "budget_exhausted"}

    post_snap = fs.posts_col(brand_id).document(post_id).get()
    if not post_snap.exists:
        _video_log(brand_id, post_id, video_url, "received", "no_post")
        return {"status": "skip", "reason": "no_post"}

    # ── 1. Download ──────────────────────────────────────────────────
    t_dl = time.time()
    video_bytes, dl_reason, total_bytes = _download_video(video_url)
    dl_ms = int((time.time() - t_dl) * 1000)
    if not video_bytes:
        _video_log(brand_id, post_id, video_url, "download", "failed", {
            "reason": dl_reason,
            "bytesAttempted": total_bytes,
            "ms": dl_ms,
        })
        return {"status": "skip", "reason": "download_failed", "downloadReason": dl_reason}
    _video_log(brand_id, post_id, video_url, "download", "ok", {
        "bytes": total_bytes,
        "ms": dl_ms,
    })

    # ── 2. Frame extraction ─────────────────────────────────────────
    t_fr = time.time()
    frames, frame_info = _extract_frames(video_bytes)
    fr_ms = int((time.time() - t_fr) * 1000)
    if not frames:
        _video_log(brand_id, post_id, video_url, "frames", "failed", {
            "framesExtracted": 0,
            "info": frame_info,
            "ms": fr_ms,
        })
        return {"status": "skip", "reason": "no_frames", "frameInfo": frame_info}
    _video_log(brand_id, post_id, video_url, "frames", "ok", {
        "framesExtracted": len(frames),
        "info": frame_info,
        "ms": fr_ms,
    })

    # ── 3. Per-frame analysis (via detect_image cascade) ────────────
    bucket = fs.bucket()
    hit = False
    hit_frame: dict | None = None
    frames_analysed = 0
    frame_outcomes: list[dict] = []
    for frame_idx, jpeg in frames:
        path = f"thumbnails/{brand_id}/video_frames/{post_id}_f{frame_idx}.jpg"
        blob = bucket.blob(path)
        if not blob.exists():
            blob.upload_from_string(jpeg, content_type="image/jpeg")
            blob.make_public()
        frame_url = blob.public_url

        try:
            r = detect_image.run(brand_id, post_id, frame_url, frame_idx=frame_idx)
        except Exception as e:
            log.error(f"frame {frame_idx} detect_image error: {e}")
            frame_outcomes.append({"idx": frame_idx, "err": str(e)[:120]})
            continue
        frames_analysed += 1
        frame_outcomes.append({
            "idx": frame_idx,
            "source": r.get("source"),
            "detected": r.get("detected"),
        })
        if r.get("detected") is True:
            hit = True
            hit_frame = {"frame_idx": frame_idx, "source": r.get("source")}
            break  # short-circuit

    total_ms = int((time.time() - t_start) * 1000)
    _video_log(brand_id, post_id, video_url, "done", "hit" if hit else "no_hit", {
        "framesAnalysed": frames_analysed,
        "hitFrame": hit_frame,
        "frames": frame_outcomes,
        "totalMs": total_ms,
    })

    # Mark post as video-processed so future scans don't re-publish to
    # detect-video unless the post's metrics change materially.
    fs.posts_col(brand_id).document(post_id).set({
        "videoProcessed": True,
        "videoProcessedAt": SERVER_TIMESTAMP,
        "videoHit": hit,
    }, merge=True)

    fs.scan_runs_col(brand_id).add({
        "type": "detect_video",
        "postId": post_id,
        "framesAnalysed": frames_analysed,
        "hit": hit,
        "hitFrame": hit_frame,
        "totalMs": total_ms,
        "finishedAt": SERVER_TIMESTAMP,
    })
    return {"status": "ok", "framesAnalysed": frames_analysed, "hit": hit, "hitFrame": hit_frame}
