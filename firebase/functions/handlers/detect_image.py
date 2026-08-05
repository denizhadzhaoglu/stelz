"""Brand detection for a single image, multi-stage cascade.

Pub/Sub triggered. One message = one image.

Cascade (cheapest first):
  1. imageHashCache hit  → reuse prior result (free)
  2. RapidOCR text grab  → if wordmark present, auto-HIT (free, ~150 ms)
  3. Gemini Flash full   → with brand-identity prompt + reference images
                           (prompt v5: surface_type, visible_text, people, setting, activity)

Embedding pre-filter removed — Gemini API has no image-embedding endpoint
(gemini-embedding-001 is text-only), so the filter never worked correctly.
We keep cost down via the imageHashCache + OCR shortcut + 512px image resize.

Persistence: every survivor of stages 2-3 writes a detection doc. Hashtag
yield is updated incrementally for SRS.
"""
from __future__ import annotations
import io
import logging
from typing import Any

import requests
from PIL import Image
from google.cloud.firestore import SERVER_TIMESTAMP, Increment

from lib import cache, fs, gemini, inbox, refs, usage

log = logging.getLogger(__name__)

# Resize candidate images before sending to Gemini — cuts vision token cost ~50%.
MAX_IMAGE_DIM = 512


def _resize(image_bytes: bytes, max_dim: int = MAX_IMAGE_DIM) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            s = max_dim / max(w, h)
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return image_bytes


def _denormalized_fields(post: dict) -> dict:
    """Fields we copy onto each detection so compute_resonance and the UI can
    render rich info without N+1 lookups."""
    return {
        "creatorHandle": post.get("creatorHandle"),
        "platform": post.get("platform"),
        "postedAt": post.get("postedAt"),
        "postHashtags": post.get("hashtags") or [],
        "postMentions": post.get("mentions") or [],
        "likesCount": post.get("likesCount"),
        "commentsCount": post.get("commentsCount"),
        "viewsCount": post.get("viewsCount"),
        "followerCount": post.get("followerCount"),
        "creatorTier": post.get("creatorTier"),
        "postUrl": post.get("url"),
        "postCaption": (post.get("caption") or "")[:500],
        "music": post.get("music"),       # {title, artist, url, ...} or None
        "extras": post.get("extras"),     # {effects, location, author, ...} or None
    }


def _mirror_to_storage(brand_id: str, image_hash: str, image_bytes: bytes) -> str | None:
    """Upload the image to Cloud Storage so the UI has a permanent URL.
    Instagram/TikTok source URLs expire within hours. Returns the public URL
    or None on failure (UI will fall back to the original URL)."""
    try:
        bucket = fs.bucket()
        path = f"thumbnails/{brand_id}/{image_hash}.jpg"
        blob = bucket.blob(path)
        if not blob.exists():
            blob.upload_from_string(image_bytes, content_type="image/jpeg")
            blob.make_public()
        return blob.public_url
    except Exception as e:
        log.warning(f"storage mirror failed: {e}")
        return None


def _bump_hashtag_yield(brand_id: str, hashtags: list[str]) -> None:
    """Incrementally update /brands/{id}.hashtagYield counters on a hit.
    Saves a full re-stream of detections in compute_resonance."""
    if not hashtags:
        return
    fs.brand_doc(brand_id).set({
        "hashtagYield": {h.lower(): Increment(1) for h in hashtags if h},
    }, merge=True)


def _log_attempt(brand_id: str, post_id: str, image_url: str, outcome: str, reason: str, extra: dict | None = None) -> None:
    """Write a debug-log doc for every detect-image attempt so the UI can
    show why no detection was produced (fetch_failed, no_brand, etc)."""
    doc = {
        "postId": post_id,
        "imageUrl": image_url,
        "outcome": outcome,  # 'wrote' | 'skipped' | 'error'
        "reason": reason,    # short tag like 'fetch_failed' | 'budget_exhausted' | 'detected_false'
        "createdAt": SERVER_TIMESTAMP,
        **(extra or {}),
    }
    try:
        fs.brand_doc(brand_id).collection("detectLog").add(doc)
    except Exception:
        pass


def run(brand_id: str, post_id: str, image_url: str, frame_idx: int | None = None) -> dict[str, Any]:
    if usage.budget_exhausted(brand_id):
        _log_attempt(brand_id, post_id, image_url, "skipped", "budget_exhausted")
        return {"status": "skip", "reason": "budget_exhausted"}

    brand_snap = fs.brand_doc(brand_id).get()
    if not brand_snap.exists:
        _log_attempt(brand_id, post_id, image_url, "skipped", "no_brand")
        return {"status": "skip", "reason": "no_brand"}
    brand = brand_snap.to_dict() or {}
    brand_name = brand.get("name", brand_id)
    product_lines = brand.get("productLines") or {}
    brand_identity = brand.get("visualIdentity")
    wordmarks = brand.get("wordmarkAliases") or None

    post_snap = fs.posts_col(brand_id).document(post_id).get()
    if not post_snap.exists:
        _log_attempt(brand_id, post_id, image_url, "skipped", "no_post")
        return {"status": "skip", "reason": "no_post"}
    post = post_snap.to_dict() or {}

    # ── 1. Fetch image bytes + hash ───────────────────────────────────
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
        image_bytes = resp.content
    except Exception as e:
        log.error(f"image fetch failed: {e}")
        _log_attempt(brand_id, post_id, image_url, "error", "fetch_failed", {"errMsg": str(e)[:200]})
        return {"status": "error", "reason": "fetch_failed"}
    image_hash = cache.sha256_of(image_bytes)

    # Mirror image to Cloud Storage so the UI keeps a permanent URL.
    # Instagram/TikTok URLs are signed and expire within hours.
    stored_url = _mirror_to_storage(brand_id, image_hash, image_bytes)

    det_id = fs.composite_id(post_id, image_hash[:12])
    if frame_idx is not None:
        det_id = fs.composite_id(post_id, image_hash[:12], f"f{frame_idx}")
    # NB: never include verified / isFalsePositive here. Rescans merge onto
    # existing docs, and writing None would wipe a moderator's approve/reject
    # decision every time the same post gets re-analyzed.
    base_doc = {
        "postId": post_id,
        "imageHash": image_hash,
        "imageUrl": stored_url or image_url,
        "sourceUrl": image_url,  # keep original for traceability
        "frameIdx": frame_idx,
        "promptVersion": 11,
        "createdAt": SERVER_TIMESTAMP,
        **_denormalized_fields(post),
    }

    # ── 2. imageHashCache shortcut ────────────────────────────────────
    cached = cache.get_cached_detection(brand_id, image_hash, "cascade", prompt_version=11)
    if cached:
        result = cached
        _persist(brand_id, post_id, det_id, base_doc, result, source="cache")
        usage.record(brand_id, detections_written=1, detections_hit=1 if result.get("detected") else 0)
        _log_attempt(brand_id, post_id, image_url, "wrote", "cache_hit", {"detected": bool(result.get("detected"))})
        return {"status": "ok", "source": "cache", "detected": bool(result.get("detected"))}

    # ── 3. Gemini Flash full detection ────────────────────────────────
    # OCR removed entirely — substring matching produced false hits (German
    # "Stelzlagern" → instant 95%), and RapidOCR added ~200MB of deps + cold
    # start for little value. Gemini + the strictness gate is the detector.
    _ = wordmarks  # reserved for a future word-boundary OCR reintroduction
    resized = _resize(image_bytes)
    ref_bytes = refs.load_references(brand_id)
    try:
        # Reuse the existing gemini.detect_image flow but pass the resized bytes
        # by overriding the URL — we already have the bytes, so we patch the
        # SDK fetch by writing bytes to a temp data URI. Simpler: call directly.
        result = gemini.detect_image(
            image_url, brand_name, product_lines,
            brand_identity=brand_identity,
            reference_image_bytes=ref_bytes,
            model="gemini-2.5-flash",
        )
    except Exception as e:
        log.error(f"gemini call failed: {e}")
        result = {"detected": False, "confidence": 0.0, "context": "gemini_error"}
    result["source"] = "gemini"
    usage.record(brand_id, gemini_flash_calls=1)

    # Code-level strictness gate — the prompt asks for honesty, this enforces it.
    result = _strictness_gate(result)

    cache.save_cached_detection(brand_id, image_hash, "cascade", result, prompt_version=11)
    _persist(brand_id, post_id, det_id, base_doc, result, source="gemini")

    detected = bool(result.get("detected"))
    _log_attempt(
        brand_id, post_id, image_url, "wrote", "gemini_hit" if detected else "gemini_miss",
        {
            "confidence": result.get("confidence"),
            "productLine": result.get("product_line"),
            "surfaceType": result.get("surface_type"),
            "visibleText": (result.get("visible_text") or "")[:120] if result.get("visible_text") else None,
            "geminiContext": (result.get("context") or "")[:400],
            "gate": result.get("gate"),
        },
    )
    if detected:
        _bump_hashtag_yield(brand_id, post.get("hashtags") or [])
        _maybe_tier1_alert(brand_id, post, det_id, result)
    usage.record(brand_id, detections_written=1, detections_hit=1 if detected else 0)
    return {"status": "ok", "source": "gemini", "detected": detected}

    _ = resized  # bytes kept for future direct-bytes Gemini path


def _normalize_brand_text(s: str) -> str:
    return (
        s.lower()
        .replace("ë", "e").replace("é", "e").replace("è", "e")
    )


import re as _re

def _has_brand_word(s: str) -> bool:
    """True only when 'stelz' appears as a standalone word (or with a short
    product suffix like 'stelz.'), NOT as a prefix of a longer word — the
    German word 'Stelzlager' (terrace pedestal) burned us via substring
    matching."""
    norm = _normalize_brand_text(s)
    return bool(_re.search(r"(?<![a-z0-9])stelz(?![a-z0-9])", norm))


def _strictness_gate(result: dict) -> dict:
    """Hard post-checks on a Gemini hit. Prompts can be ignored or
    hallucinated around (e.g. the model copying the brand identity text onto
    a microphone); these checks can't.

    Rule 1 — visible_text must contain STELZ as a standalone word, else
             detected=false ("Stelzlagern" prefix matches don't count).
    Rule 2 — confidence >= 0.85 requires the object to be dominant/large in
             frame. A "medium"/"small" object the model claims to read at 95%
             is exactly the hallucination signature (microphone case) — cap
             to 0.70 so it stays out of the default feed but remains findable.
    """
    if not result.get("detected"):
        return result

    if not _has_brand_word(result.get("visible_text") or ""):
        result["detected"] = False
        result["false_positive_risk"] = "high"
        result["gate"] = "rejected_no_brand_text"
        result["context"] = f"auto-rejected (no standalone STELZ wordmark read) — {result.get('context') or ''}"[:400]
        return result

    big = result.get("size_in_frame") in ("dominant", "large")

    # Fabrication signature: fine-print label details (calorie counts, ml
    # volumes, ABV percentages) "read" off an object that is NOT close to the
    # camera. Nobody resolves 8pt print on a medium/small can in a party
    # video — the model copied a template. Hard reject.
    # Real-world case: a Gin & Juice can transcribed as "STËLZ ... 69
    # CALORIES, 4.5% ALC, 250 mle" at size=medium.
    vt_norm = _normalize_brand_text(result.get("visible_text") or "")
    fine_print = sum([
        bool(_re.search(r"\d+\s*calor", vt_norm)),
        bool(_re.search(r"\d+\s*ml", vt_norm)),
        bool(_re.search(r"\d+([.,]\d+)?\s*%", vt_norm)),
    ])
    if not big and fine_print >= 2:
        result["detected"] = False
        result["false_positive_risk"] = "high"
        result["gate"] = "rejected_fabricated_fine_print"
        result["context"] = f"auto-rejected (fine-print label text claimed on a distant object) — {result.get('context') or ''}"[:400]
        return result

    conf = float(result.get("confidence") or 0)
    if conf >= 0.85 and not big:
        result["confidence"] = 0.70
        result["false_positive_risk"] = "high"
        result["gate"] = "capped_small_object"
    return result


def _bump_scan_progress(brand_id: str, hit: bool) -> None:
    """Increment brand.scan detection counters so the UI pill can show
    'Analyzing 4234/5285 posts' after scrape completes."""
    try:
        fs.brand_doc(brand_id).set({
            "scan": {
                "detectionsCompleted": Increment(1),
                "detectionsHit": Increment(1 if hit else 0),
            }
        }, merge=True)
    except Exception:
        pass


def _persist(brand_id: str, post_id: str, det_id: str, base: dict, result: dict, source: str) -> None:
    """Merge result fields onto base doc and write."""
    doc = {**base, **{
        "detected": bool(result.get("detected")),
        "confidence": float(result.get("confidence") or 0),
        "productLine": result.get("product_line"),
        "sizeInFrame": result.get("size_in_frame"),
        "isPrimarySubject": bool(result.get("is_primary_subject")),
        "context": result.get("context"),
        "model": result.get("model"),
        "source": source,
        # Rich prompt-v5 fields — see lib/gemini.py DETECT_PROMPT_V5.
        "surfaceType": result.get("surface_type"),
        "visibleText": result.get("visible_text"),
        "falsePositiveRisk": result.get("false_positive_risk"),
        "peopleCount": result.get("people_count"),
        "setting": result.get("setting"),
        "activity": result.get("activity"),
    }}
    # bbox no longer requested from Gemini (prompt v5); the drawer renders
    # text-based findings instead of an SVG overlay.
    fs.detections_col(brand_id).document(det_id).set(doc, merge=True)

    if doc["detected"]:
        fs.posts_col(brand_id).document(post_id).set(
            {"hasDetection": True, "lastDetectionAt": SERVER_TIMESTAMP},
            merge=True,
        )

    _bump_scan_progress(brand_id, hit=doc["detected"])


def _maybe_tier1_alert(brand_id: str, post: dict, det_id: str, result: dict) -> None:
    """Push an inbox event for a tier-1 creator hit (highest signal events)."""
    tier = post.get("creatorTier")
    if tier != "tier_1":
        return
    handle = post.get("creatorHandle") or "creator"
    inbox.publish(
        brand_id,
        event_type="tier1_hit",
        body=f"New tier-1 hit from @{handle}",
        link=f"/?detection={det_id}",
        meta={
            "creatorHandle": handle,
            "confidence": result.get("confidence"),
            "productLine": result.get("product_line"),
        },
    )
