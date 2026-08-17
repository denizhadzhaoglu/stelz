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

from lib import cache, fs, gemini, identity, inbox, refs, usage, verifier

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
    # Standalone OCR stays removed — substring matching produced false hits
    # (German "Stelzlagern" → instant 95%) and RapidOCR added ~200MB of deps +
    # cold start for little value. Gemini reads the label; the strictness gate
    # decides. `wordmarkAliases` is no longer dead: it now feeds the gate's
    # accept list via _accept_variants(), with word-boundary matching and the
    # denylist that keeps "Stelzlager" rejected (lib/identity.py).
    resized = _resize(image_bytes)
    ref_bytes = refs.load_references(brand_id)
    try:
        # Pass the bytes we already hold. Previously this call took only the
        # URL, so gemini.detect_image re-fetched an image this function had
        # just downloaded, hashed and resized — a second round-trip per image,
        # and per video FRAME.
        #
        # It was also a correctness bug, not just waste: Instagram and TikTok
        # media URLs are short-lived signed CDN links, and this pipeline queues
        # behind max_instances=25. A URL that expires between the two fetches
        # produced `gemini_error` for an image already sitting in memory.
        result = gemini.detect_image(
            image_url, brand_name, product_lines,
            brand_identity=brand_identity,
            reference_image_bytes=ref_bytes,
            model="gemini-2.5-flash",
            image_bytes=resized,
        )
    except Exception as e:
        log.error(f"gemini call failed: {e}")
        result = {"detected": False, "confidence": 0.0, "context": "gemini_error"}
    result["source"] = "gemini"
    usage.record(brand_id, gemini_flash_calls=1)

    # Code-level strictness gate — the prompt asks for honesty, this enforces it.
    result = _strictness_gate(result, accept_variants=_accept_variants(brand))

    # Second look at the hits the gate had to demote. Runs BEFORE the cache save
    # on purpose, so the merged verdict is what gets cached: a replay of the same
    # image is then free and is never re-verified.
    result = _verify_pass(brand_id, brand_name, image_bytes, ref_bytes, result)

    # Never cache a failed call. A 429 during a burst, a timeout, or a malformed
    # response is not evidence the brand is absent — but caching it writes a
    # permanent negative for that image hash, and the only way back is a global
    # promptVersion bump that re-bills the entire corpus. Leave these uncached so
    # the next scan retries them.
    if (result.get("context") or "") not in ("gemini_error", "parse_error"):
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


def _verify_pass(
    brand_id: str,
    brand_name: str,
    image_bytes: bytes,
    ref_bytes: list[bytes],
    result: dict,
) -> dict:
    """Re-examine a demoted hit at higher resolution. See lib/verifier.py.

    Up to two calls. The first re-reads the whole frame at 1024px instead of the
    512px the first pass saw. If the model localizes the container and it is
    small in frame, a second call goes in on a padded crop at native resolution
    — that is where a can held at arm's length in a festival shot finally becomes
    legible. Cans that are already large in frame get one call, because the crop
    would add nothing.

    Failures are swallowed to `inconclusive`. A verifier that is down, rate
    limited or returning garbage must never delete a detection: this pass may
    only act on evidence it actually obtained.
    """
    if not verifier.should_verify(result):
        return result
    try:
        # What the moderator has already rejected, as labelled counter-examples.
        # This is what makes the ✕ button in the feed mean something: before it,
        # isFalsePositive was written and never read by anything server-side.
        negatives = refs.load_negative_exemplars(brand_id, brand_name)
        verdict = gemini.verify_brand(
            _resize(image_bytes, verifier.VERIFY_MAX_DIM),
            brand_name,
            reference_image_bytes=ref_bytes,
            negative_exemplars=negatives,
            model="gemini-2.5-flash",
        )
        usage.record(brand_id, gemini_verify_calls=1)

        box = verdict.get("box_2d")
        if verifier.needs_crop(box):
            crop = verifier.crop_to_box(image_bytes, box)
            if crop:
                refined = gemini.verify_brand(
                    _resize(crop, verifier.VERIFY_MAX_DIM),
                    brand_name,
                    reference_image_bytes=ref_bytes,
                    negative_exemplars=negatives,
                    model="gemini-2.5-flash",
                )
                usage.record(brand_id, gemini_verify_calls=1)
                # The crop is strictly more information about the same object,
                # so it supersedes — but only when it actually resolved a brand.
                # An inconclusive crop must not overwrite a confident full-frame
                # read; that would turn added detail into lost signal.
                if refined.get("brand") not in (None, "", "no_readable_brand"):
                    verdict = refined
                    verdict["from_crop"] = True
    except Exception as e:
        log.warning(f"[{brand_id}] verify pass failed: {e}")
        return {**result, "verify_verdict": "error", "verify_version": verifier.VERIFY_VERSION}

    slug = identity.normalize(brand_name) or "stelz"
    return verifier.decide(result, verdict, brand_slug=slug)


def _normalize_brand_text(s: str) -> str:
    return (
        s.lower()
        .replace("ë", "e").replace("é", "e").replace("è", "e")
    )


import re as _re

def _accept_variants(brand: dict) -> list[str]:
    """Wordmark spellings that may ACCEPT a detection.

    Canonical slug + operator-curated `wordmarkAliases` + generated STRICT typo
    variants (stelzz, stellz, steelz — plausible OCR misreads of a real can).

    LOOSE variants (stels, setlz, stlez) are deliberately excluded. They exist
    to find candidate *content* via hashtag search; letting them accept a
    detection would manufacture false positives. See lib/identity.py.

    ORDER IS MEANINGFUL, not alphabetical: canonical, then curated aliases,
    then generated variants. identity.partial_wordmark_match breaks ties by
    list position, and a wildcard read like "ST??Z" aligns equally well to
    `stelz` and to the leet variant `st3lz`. Sorted order would report the
    latter, which is both wrong and confusing in `matchedVariant`.
    """
    canonical = identity.normalize(brand.get("slug") or "")
    ordered: list[str] = [canonical] if canonical else []
    seen = set(ordered)
    for a in (brand.get("wordmarkAliases") or []):
        na = identity.normalize(a)
        if na and na not in seen:
            seen.add(na)
            ordered.append(na)
    if canonical:
        for v in sorted(identity.generate_variants(canonical)["strict"]):
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)
    return ordered


def _has_brand_word(s: str, variants: list[str] | None = None) -> bool:
    """True only when a brand wordmark appears as a standalone word, NOT as a
    prefix of a longer one — the German 'Stelzlager' (terrace pedestal) burned
    us via substring matching.

    Delegates to lib.identity, which carries the word-boundary rule, the
    denylist, and the offline regression tests (tests/test_identity.py).
    """
    ok, _matched = identity.has_brand_word(s, variants or ["stelz"])
    return ok


def _strictness_gate(result: dict, accept_variants: list[str] | None = None) -> dict:
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
    # Preserve the model's own number before any rule below rewrites it.
    # Rule 2 overwrites `confidence` in place, which is why every capped
    # detection collides on exactly 0.70 and becomes indistinguishable from a
    # genuinely-uncertain hit. Keep the raw value so the UI (and the eval
    # harness) can tell "model was unsure" apart from "model was sure but the
    # can was small".
    result.setdefault("model_confidence", result.get("confidence"))
    # Same problem, same fix, for the risk field: every reject/cap branch below
    # stamps false_positive_risk="high", so the model's own assessment is lost.
    # That cost real analysis time — a "high" read off a stored detection looks
    # like the model flagged it, when in fact the model said "low" and OUR gate
    # capped it for being small. Keep both, and note that the partial-read
    # branch below reads the model's value, so it must be captured first.
    result.setdefault("model_false_positive_risk", result.get("false_positive_risk"))

    if not result.get("detected"):
        return result

    _vt = result.get("visible_text") or ""
    _variants = accept_variants or ["stelz"]
    _ok, _matched = identity.has_brand_word(_vt, _variants)

    # Partial-read fallback. The prompt deliberately produces transcripts like
    # "ST??Z" for a wordmark that is present but not fully resolvable, and
    # assigns them 0.70-0.84 — but the exact-match gate rejected every one, so
    # that whole tier was dead by construction.
    #
    # Accept them only when the model's OWN false_positive_risk is "low", a
    # field the gate previously ignored. On the golden set this is what
    # separates the two partial reads: the genuine can reports low risk, the
    # hallucinated one reports medium.
    if not _ok:
        _p_ok, _p_var, _p_res = identity.partial_wordmark_match(_vt, _variants)
        if _p_ok and result.get("false_positive_risk") == "low":
            _ok, _matched = True, _p_var
            result["partialMatch"] = True
            result["resolvedChars"] = _p_res
            # Never let an incomplete read reach full confidence.
            result["confidence"] = min(float(result.get("confidence") or 0), 0.75)
            result["gate"] = "accepted_partial_wordmark"

    # Record WHICH spelling matched. If a generated typo variant starts showing
    # up on moderator-rejected detections, that is the signal to demote it from
    # the strict list — the loop that would have caught "Stelzlager" early.
    result["matched_variant"] = _matched
    if not _ok:
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
    # Only treat fine print as fabrication when the model ITSELF says the label
    # was not cleanly legible. Claiming to read 8pt print off a label you just
    # reported as blurry is the fabrication signature; reading it off a label
    # you reported as clear is just... reading it.
    #
    # Measured on the 24-image golden set (tools/eval): the unconditional rule
    # rejected 2 genuine Stelz cans — both `legibility=clear, size=medium`, both
    # with a correctly-read STËLZ wordmark — and caught zero actual
    # fabrications. It was pure recall loss.
    legible = (result.get("text_legibility") == "clear")
    if not big and not legible and fine_print >= 2:
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
        # Why the gate demoted/rejected this hit ('capped_small_object',
        # 'rejected_no_brand_text', 'rejected_fabricated_fine_print'), plus the
        # model's pre-gate confidence. Without these the reason a detection is
        # hidden is unrecoverable outside the debug detectLog.
        "gate": result.get("gate"),
        "modelConfidence": result.get("model_confidence"),
        "modelFalsePositiveRisk": result.get("model_false_positive_risk"),
        # Which wordmark spelling matched — canonical, a curated alias, or a
        # generated typo variant. Lets a bad variant be traced and demoted.
        "matchedVariant": result.get("matched_variant"),
        # Second-look outcome (lib/verifier.py): 'confirmed' | 'rejected' |
        # 'upgraded' | 'inconclusive' | 'error', plus which brand the verifier
        # actually read and why. verifyVersion lives here rather than in
        # promptVersion so a verifier change can be rolled out lazily instead of
        # invalidating the whole image cache and re-billing every image.
        "verifyVerdict": result.get("verify_verdict"),
        "verifyBrand": result.get("verify_brand"),
        "verifyReason": result.get("verify_reason"),
        "verifyVersion": result.get("verify_version"),
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
