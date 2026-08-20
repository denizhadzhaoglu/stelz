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

from lib import cache, fs, gemini, identity, refs, scan_state, usage
from handlers import detect_image

log = logging.getLogger(__name__)

MAX_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB

# Sample inside this window rather than the old fixed [0.0, 0.2 ... 1.0]. On a Reel or TikTok, frame 0
# is almost always a title/hook card and the final frame an outro or CTA — the
# old fixed [0.0 ... 1.0] spread burned two of its six samples on them. The
# legacy pipeline already knew this (57_video_frame_detect.py:120-122 sampled
# 10%-90%); the Firebase rewrite dropped it.
_SAMPLE_LO = 0.08
_SAMPLE_HI = 0.92

# Bump to force reprocessing of every already-analysed video after a pipeline
# improvement. Stored on the post as videoDetectVersion.
VIDEO_DETECT_VERSION = 2


def adaptive_frame_budget(duration_s: float) -> int:
    """How many frames to sample for a clip of this length.

    A fixed 6 over-samples a 5-second clip and badly under-samples a 3-minute
    vlog. Duration is already captured on the post as extras.duration but was
    never used.

    Budgets raised by ~50% over the original 4/6/8/10. What makes that cheap is
    the batch screen (screen_flags_frame): every extracted frame goes through ONE
    Gemini call that flags the ~21% worth analysing, and only those become
    individual detect calls. So an extra frame costs a slice of one batched call,
    not a full detection — while a can that appears in only one second of a
    60-second clip needs the denser sampling to be caught at all.

    Note what this does and does not buy. Recall on clips where the can IS
    sampled is already measured at 1.000, so extra frames mostly find the SAME
    post again (deduped by dedupeByPost in the UI). The gain is on clips the
    sparser grid missed entirely — real, but not a linear increase in hits.
    """
    if duration_s <= 0:
        return 8  # unknown duration — the common case for TikTok
    if duration_s <= 10:
        return 6
    if duration_s <= 30:
        return 9
    if duration_s <= 60:
        return 12
    return 15


def frame_sample_points(duration_s: float, budget: int | None = None) -> list[float]:
    """Fractional positions to sample, evenly spread inside the safe window."""
    n = budget if budget is not None else adaptive_frame_budget(duration_s)
    n = max(1, n)
    if n == 1:
        return [(_SAMPLE_LO + _SAMPLE_HI) / 2]
    step = (_SAMPLE_HI - _SAMPLE_LO) / (n - 1)
    return [round(_SAMPLE_LO + step * i, 4) for i in range(n)]


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


def screen_flags_frame(verdict: dict, accept_variants: list[str] | None = None) -> bool:
    """Should this batch-screened frame get a full per-frame analysis?

    The two errors are not symmetric: over-flagging costs one extra Gemini
    call, while under-flagging drops a frame nothing ever looks at again. So
    this leans towards flagging — but only on BRAND-relevant evidence.

    Flagging on "the model transcribed any text at all" was the obvious
    generous rule and it is a trap. Measured over the 72-image golden set it
    flags 50% of frames, because the model reads competitor labels perfectly
    well: TRULY, HEINEKEN, Red Bull, THERMOS all carry text and none of them
    can ever survive the real gate. Restricting to brand-relevant text flags
    ~21% while keeping every known positive.

    The partial-wordmark case is handled explicitly rather than by accident.
    DETECT_PROMPT_V8 emits reads like "ST??Z"; on the golden set the model does
    set detected=true for those, but that is an observation about current model
    behaviour, not a guarantee. Matching the wildcard form directly means the
    tier survives even if that behaviour changes.
    """
    if verdict.get("detected"):
        return True
    vt = (verdict.get("visible_text") or "").strip()
    if not vt:
        return False
    variants = accept_variants or ["stelz"]
    if identity.has_brand_word(vt, variants)[0]:
        return True
    return identity.partial_wordmark_match(vt, variants)[0]


def _extract_frames(
    video_bytes: bytes, frame_budget: int | None = None
) -> tuple[list[tuple[int, bytes]], dict]:
    """Returns (frames, info). info contains diagnostic details (total_frames,
    fps, duration_seconds, sample_points, decode_errors).

    frame_budget overrides the duration-derived count — used to shrink sampling
    when the brand is near its budget cap (see lib/usage.frame_budget_cap)."""
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
        duration_s = 0.0
        if fps > 0:
            duration_s = total_frames / fps
            info["duration_seconds"] = round(duration_s, 1)

        points = frame_sample_points(duration_s, budget=frame_budget)
        info["sample_points"] = points
        for i, pct in enumerate(points):
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


def _cover_fallback(
    brand_id: str,
    post_id: str,
    post: dict,
    video_url: str,
    reason: str,
) -> dict[str, Any]:
    """Last resort when a video can't be downloaded or decoded: run the normal
    image detector over the post's stored cover image.

    Returns the usual handler dict. Marks the post processed so the video path
    isn't retried forever, but records `videoFallback` so the outcome is
    distinguishable from a genuine full-video analysis.
    """
    cover = post.get("coverUrl")
    if not cover:
        _video_log(brand_id, post_id, video_url, "fallback", "no_cover", {"reason": reason})
        return {"status": "skip", "reason": "download_failed", "downloadReason": reason}

    try:
        r = detect_image.run(brand_id, post_id, cover, bump_progress=False)
    except Exception as e:
        log.error(f"cover fallback failed for {post_id}: {e}")
        _video_log(brand_id, post_id, video_url, "fallback", "error", {"errMsg": str(e)[:160]})
        return {"status": "error", "reason": "cover_fallback_failed"}

    hit = bool(r.get("detected"))
    _video_log(brand_id, post_id, video_url, "fallback", "hit" if hit else "no_hit", {
        "reason": reason,
        "coverUrl": cover[:200],
    })
    fs.posts_col(brand_id).document(post_id).set({
        "videoProcessed": True,
        "videoProcessedAt": SERVER_TIMESTAMP,
        "videoDetectVersion": VIDEO_DETECT_VERSION,
        "videoHit": hit,
        "videoFallback": reason,
    }, merge=True)
    return {"status": "ok", "source": "cover_fallback", "hit": hit, "reason": reason}


def run(brand_id: str, post_id: str, video_url: str) -> dict[str, Any]:
    """One video message = one progress unit.

    detect_video never bumped at all, while the detect_image calls it makes per
    frame each bumped once — so numerator and denominator were different units
    and a video-heavy scan reported nonsense (a 6-frame video moved the bar six
    places while the queue counted it as one). Nested calls now pass
    bump_progress=False and this counts the message, once, in a finally.
    """
    outcome: dict[str, Any] = {"status": "error", "reason": "crashed"}
    try:
        outcome = _run_inner(brand_id, post_id, video_url)
        return outcome
    finally:
        scan_state.bump_detect_progress(
            brand_id,
            hit=bool(outcome.get("hit") or outcome.get("detected")),
            skipped=outcome.get("status") == "skip",
        )


def _run_inner(brand_id: str, post_id: str, video_url: str) -> dict[str, Any]:
    t_start = time.time()
    _video_log(brand_id, post_id, video_url, "received", "ok")

    if usage.budget_exhausted(brand_id):
        _video_log(brand_id, post_id, video_url, "received", "skipped_budget")
        return {"status": "skip", "reason": "budget_exhausted"}

    post_snap = fs.posts_col(brand_id).document(post_id).get()
    if not post_snap.exists:
        _video_log(brand_id, post_id, video_url, "received", "no_post")
        return {"status": "skip", "reason": "no_post"}
    post = post_snap.to_dict() or {}

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
        # Fall back to the cover image rather than giving up on the post.
        #
        # Download failure is the NORM, not the exception: TikTok blocks GCP
        # egress IPs (scan_hashtags.py:189-192) and Instagram videoUrls are
        # short-lived signed CDN URLs that routinely expire while queued behind
        # max_instances=25. Previously this returned here and the post produced
        # zero detections forever, despite a perfectly good cover JPEG already
        # being scraped and stored.
        return _cover_fallback(brand_id, post_id, post, video_url, dl_reason)
    _video_log(brand_id, post_id, video_url, "download", "ok", {
        "bytes": total_bytes,
        "ms": dl_ms,
    })

    # ── 2. Frame extraction ─────────────────────────────────────────
    t_fr = time.time()
    # Under budget pressure, sample fewer frames rather than dropping the video
    # entirely — a shallower look still finds dominant cans.
    frames, frame_info = _extract_frames(
        video_bytes, frame_budget=usage.frame_budget_cap(brand_id)
    )
    fr_ms = int((time.time() - t_fr) * 1000)
    if not frames:
        _video_log(brand_id, post_id, video_url, "frames", "failed", {
            "framesExtracted": 0,
            "info": frame_info,
            "ms": fr_ms,
        })
        # Decode failure is common for streamed/fragmented MP4s, where OpenCV
        # reports total_frames <= 0. Same reasoning as the download path: the
        # cover image is already paid for and is better than nothing.
        return _cover_fallback(brand_id, post_id, post, video_url, "no_frames")
    _video_log(brand_id, post_id, video_url, "frames", "ok", {
        "framesExtracted": len(frames),
        "info": frame_info,
        "ms": fr_ms,
    })

    # ── 3. Batched screen ────────────────────────────────────────────
    # One Gemini call judges every frame, and only the frames it flags get a
    # full per-frame analysis. Measured on the golden set (tools/eval/eval_batch.py):
    #
    #   batched recall    1.000  — never drops a genuine can
    #   batched precision worse  — a real can in ONE frame leaks into others:
    #                              a true negative came back as "STËLZ HARD
    #                              SELTZER PEACH 63 CALORIES" at 0.9, and as
    #                              "STËLZ HARD LEMONADE ORANGE" on a re-run.
    #                              Different fabricated text each time.
    #
    # So batching is used ONLY to skip work, never to decide. Every surfaced
    # detection still comes from an unbatched detect_image.run(), which is the
    # path whose precision is actually measured. The asymmetry is what makes
    # this safe: over-flagging costs one extra call, under-flagging would lose
    # a can forever, and the screen does not under-flag.
    #
    # Cost: most videos contain no brand at all, so the common path is one
    # batched call instead of N — measured 2.4x cheaper for a 6-frame video
    # ($0.0037 vs $0.0090). Note that is lower than the 3.6x this was planned
    # at: output tokens dominate a batched response and do not shrink.
    # Skip the screen entirely when every frame is already in the detection
    # cache. A rescan used to be free (N cache hits, no model calls); screening
    # first would have made it cost one Gemini call per video forever after.
    # detect_image hashes the bytes it fetches from the frame URL, which are
    # byte-identical to the JPEGs held here, so these hashes match its keys.
    all_cached = all(
        cache.get_cached_detection(brand_id, cache.sha256_of(jpeg), "cascade",
                                   prompt_version=11) is not None
        for _idx, jpeg in frames
    )

    screen: list[bool] | None = None
    if len(frames) > 1 and not all_cached:
        try:
            brand_snap = fs.brand_doc(brand_id).get()
            brand = brand_snap.to_dict() or {} if brand_snap.exists else {}
            u: dict = {}
            verdicts = gemini.detect_frames_batch(
                frames,
                brand.get("name", brand_id),
                brand.get("productLines") or {},
                reference_image_bytes=refs.load_references(brand_id),
                usage_out=u,
            )
            _accept = detect_image._accept_variants(brand)
            screen = [screen_flags_frame(v, _accept) for v in verdicts]
            usage.record(brand_id, gemini_video_calls=1)
            _video_log(brand_id, post_id, video_url, "screen", "ok", {
                "flagged": sum(screen),
                "frames": len(frames),
                "tokens": u,
            })
        except Exception as e:
            # Any failure — malformed array, wrong length, API error — falls
            # through to analysing every frame, i.e. exactly the previous
            # behaviour. The screen can only ever save work, never lose it.
            log.warning(f"frame screen failed, analysing all frames: {e}")
            screen = None
            _video_log(brand_id, post_id, video_url, "screen", "failed",
                       {"err": str(e)[:160]})

    # ── 4. Per-frame analysis (via detect_image cascade) ────────────
    bucket = fs.bucket()
    hit = False
    hit_frame: dict | None = None
    frames_analysed = 0
    frames_screened_out = 0
    frame_support = 0  # how many frames independently detected the brand
    frame_outcomes: list[dict] = []
    for pos, (frame_idx, jpeg) in enumerate(frames):
        if screen is not None and not screen[pos]:
            # Cleared by the screen. No detection doc is written, matching the
            # existing behaviour for any frame with no hit: the dashboard
            # queries detected==true, and the per-frame diagnostic lives in
            # this video log rather than in the detections collection.
            frames_screened_out += 1
            frame_outcomes.append({"idx": frame_idx, "source": "screen", "detected": False})
            continue
        path = f"thumbnails/{brand_id}/video_frames/{post_id}_f{frame_idx}.jpg"
        blob = bucket.blob(path)
        if not blob.exists():
            blob.upload_from_string(jpeg, content_type="image/jpeg")
            blob.make_public()
        frame_url = blob.public_url

        try:
            r = detect_image.run(brand_id, post_id, frame_url, frame_idx=frame_idx, bump_progress=False)
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
        # Analyse every frame instead of stopping at the first hit.
        #
        # The short-circuit here saved little: the common case is a miss, which
        # already ran all frames. What it cost was evidence — how many frames
        # independently support the detection. A can visible across 4 of 6
        # frames is a far stronger signal than one that flickers in a single
        # frame, and that distinction improves precision AND recall at once.
        # frameSupport is persisted below for exactly that use.
        if r.get("detected") is True:
            hit = True
            if hit_frame is None:
                hit_frame = {"frame_idx": frame_idx, "source": r.get("source")}
            frame_support += 1

    total_ms = int((time.time() - t_start) * 1000)
    _video_log(brand_id, post_id, video_url, "done", "hit" if hit else "no_hit", {
        "framesAnalysed": frames_analysed,
        "framesScreenedOut": frames_screened_out,
        "frameSupport": frame_support,
        "hitFrame": hit_frame,
        "frames": frame_outcomes,
        "totalMs": total_ms,
    })

    # Mark post as video-processed so future scans don't re-publish to
    # detect-video unless the post's metrics change materially.
    #
    # videoDetectVersion, not just a boolean: a plain `videoProcessed: True`
    # can never be re-run after the pipeline improves. Bumping the version
    # constant re-opens every video for reprocessing. (Note this flag is still
    # written-but-not-read by the publishers — wiring that dedupe is the next
    # step, and it needs a batched get_all() to avoid 1 read per post.)
    fs.posts_col(brand_id).document(post_id).set({
        "videoProcessed": True,
        "videoProcessedAt": SERVER_TIMESTAMP,
        "videoDetectVersion": VIDEO_DETECT_VERSION,
        "videoHit": hit,
        "videoFrameSupport": frame_support,
    }, merge=True)

    fs.scan_runs_col(brand_id).add({
        "type": "detect_video",
        "postId": post_id,
        "framesAnalysed": frames_analysed,
        "framesScreenedOut": frames_screened_out,
        "frameSupport": frame_support,
        "hit": hit,
        "hitFrame": hit_frame,
        "totalMs": total_ms,
        "finishedAt": SERVER_TIMESTAMP,
    })
    return {
        "status": "ok",
        "framesAnalysed": frames_analysed,
        "framesScreenedOut": frames_screened_out,
        "frameSupport": frame_support,
        "hit": hit,
        "hitFrame": hit_frame,
    }
