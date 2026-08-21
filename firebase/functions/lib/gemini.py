"""Gemini Vision wrapper for brand detection."""
from __future__ import annotations
import io
import json
import os
import re
import threading
from typing import Any

import requests
from google import genai
from google.genai import types as genai_types

from lib import sentiment, verifier


def _key() -> str:
    k = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not k:
        raise RuntimeError("GOOGLE_AI_API_KEY not set")
    return k


_client = None
_client_lock = threading.Lock()


def client():
    """One genai.Client per process, built exactly once.

    The lock is not decoration. Unsynchronised lazy init lets two threads both
    see None, both construct a Client, and only one assignment win — the loser's
    client is then garbage-collected, which closes the httpx connection pool
    underneath any request still using it. That surfaces as
    "Cannot send a request, as the client has been closed", and it did: two of
    three items failed the moment the local analyser started running items in
    parallel. The same race is reachable in a Cloud Function, where concurrency
    is on by default for v2 functions.

    The Client itself is safe to share afterwards — httpx.Client is documented
    thread-safe — so the lock is only around construction, not around use.
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = genai.Client(api_key=_key())
    return _client


DETECT_PROMPT_V8 = """You are a STRICT visual brand detector for {brand_name}. Your default answer is detected=false. The ONLY source of truth for what the product looks like is the set of reference photos provided above — study them, then judge the target image.

Work in TWO STAGES:

STAGE 1 — TRANSCRIBE FROM PIXELS ONLY.
Look at the target image. Find any beverage cans, bottles, or branded objects.
Transcribe ONLY the characters you can actually resolve in the pixels.
- You have NOT been told what the label text says. If your transcript happens to contain marketing details you could not plausibly resolve at this size (calorie counts, ml volumes, ABV percentages), you are inventing text — that is a critical failure.
- If a label is too small, blurry, turned away, or occluded: the transcript is null. Do not guess what it "probably" says.
- Use '?' for characters you cannot make out (e.g. "ST??Z").

STAGE 2 — VERIFY against the reference photos and rules below.

The brand wordmark is "{brand_name}" (may appear as STELZ or STËLZ).

PRODUCT LINES: {product_lines}

Return STRICT JSON ONLY (no prose, no markdown fences):
{{
  "detected": true/false,
  "surface_type": "can" | "bottle" | "glass" | "tshirt" | "hat" | "hoodie" | "jacket" | "banner" | "poster" | "flag" | "sticker" | "neon_sign" | "cooler" | "parasol" | "tote" | "background_signage" | "tattoo" | "merchandise" | "other" | null,
  "product_line": "<one of: {product_line_keys} or null>",
  "visible_text": "<STAGE 1 transcript: only characters truly readable in pixels, '?' for unclear, or null>",
  "text_legibility": "clear" | "partial" | "unreadable",
  "confidence": 0.0-1.0,
  "size_in_frame": "dominant" | "large" | "medium" | "small" | null,
  "is_primary_subject": true/false,
  "context": "<one short sentence: what's happening AND where the brand appears>",
  "false_positive_risk": "low" | "medium" | "high",
  "people_count": <integer>,
  "setting": "indoor" | "outdoor" | "unclear",
  "activity": "<drinking, partying, sports, posing, eating, none, etc.>"
}}

STRICT RULES — err on the side of REJECT:

1. detected=true REQUIRES the STELZ wordmark readable in STAGE 1:
   - confidence >= 0.85 only when text_legibility="clear" AND visible_text contains STELZ/STËLZ
   - partial read ("STE??", "..ELZ") with can shape matching references → confidence 0.70-0.84 max
   - No readable brand text → detected=false. No exceptions — not for colors, not for can shape, not for vibes.

2. OTHER BRANDS' hard iced tea / hard lemonade / hard seltzer are NOT matches:
   - "{brand_name} makes iced tea" does NOT mean every iced tea can is {brand_name}
   - A can that says anything else (or nothing readable) is NOT {brand_name}, even if the flavor/category matches a product line
   - White Claw, Truly, Bavaria, Heineken, Viper, Kokanee or ANY other readable brand → detected=false

3. NON-PRODUCT OBJECTS ARE NOT CANS:
   - Microphones, deodorant, thermoses, vapes, phones, glow sticks, drink shakers often look like cans in dark/party footage
   - If you cannot rule these out AND cannot read the wordmark → detected=false

4. RING ICON ALONE IS NOT ENOUGH — a circle/ring logo without readable STELZ text → detected=false.

5. REFERENCE CHECK IS MANDATORY — proportions, cap, label layout must match the reference photos.

6. NO BOUNDING BOXES OR COORDINATES — text only.
"""

# Default brand identity (Stelz). For multi-tenant we'll read this from the
# brand Firestore doc instead.
DEFAULT_BRAND_IDENTITY = """- "STËLZ" wordmark with an umlaut on the E, set in navy blue
- An S-in-circle ring icon; ring color encodes the product line:
  orange = Hard Lemonade, red/pink = Hard Seltzer, teal/green = Hard Iced Tea,
  yellow = Mixed Classics, brown = 0.0 (non-alc)
- Curved tagline on the can: HARD SELTZER / HARD LEMONADE / HARD ICED TEA / MIXED CLASSICS
- Slim Dutch beverage can (250ml or 330ml) with these visual cues
- Logo-only matches are ok if no can is visible but the wordmark is clear"""


def _fetch_image_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def _parse_json(text: str) -> dict:
    # Strip ```json fences if any
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _sniff_mime(b: bytes) -> str:
    """Detect image type from magic bytes.

    The type was previously hardcoded to image/jpeg for whatever came back from
    the URL. Instagram and TikTok serve webp/heic variants, and the repo's own
    reference images include .avif/.png/.webp — a mislabelled MIME makes the
    call fail, which (before the cache fix) got stored as a permanent negative.
    """
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    if b[4:8] == b"ftyp" and b[8:12] in (b"heic", b"heix", b"mif1"):
        return "image/heic"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"  # last-resort default, matches previous behaviour


def detect_image(
    image_url: str,
    brand_name: str,
    product_lines: dict[str, str],
    brand_identity: str | None = None,
    reference_image_bytes: list[bytes] | None = None,
    model: str = "gemini-2.5-flash",
    image_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Run Gemini detection on a single image, with optional reference images of
    the brand product so the model can visually match (much higher precision).

    Pass `image_bytes` to skip the network fetch — used by the offline eval
    harness (tools/eval) and by callers that already hold the bytes, which
    avoids a second round-trip against an expiring signed URL.
    """
    if image_bytes is None:
        image_bytes = _fetch_image_bytes(image_url)
    # v8: brand identity text is intentionally NOT in the prompt anymore.
    # Whenever it was included, the model copied its details ("69 calories",
    # "250ml", product-line taglines) into visible_text for cans it couldn't
    # actually read — fabricating perfect-looking Stelz hits on other brands.
    # Reference photos are the only product knowledge the model gets.
    _ = brand_identity  # accepted for call-compat; unused by design
    prompt = DETECT_PROMPT_V8.format(
        brand_name=brand_name,
        product_lines=", ".join(f"{k} ({v})" for k, v in product_lines.items()),
        product_line_keys=", ".join(product_lines.keys()),
    )
    # Build contents: reference images first, then user-post image, then prompt.
    # Order matters — Gemini anchors on earlier images as the "what we're looking for".
    contents: list[Any] = []
    if reference_image_bytes:
        contents.append("Reference images of the brand product (what to look for):")
        for ref in reference_image_bytes[:8]:  # cap to 8 refs for token cost
            contents.append(genai_types.Part.from_bytes(data=ref, mime_type=_sniff_mime(ref)))
    contents.append("Target image (user post — does this contain the brand?):")
    contents.append(genai_types.Part.from_bytes(data=image_bytes, mime_type=_sniff_mime(image_bytes)))
    contents.append(prompt)

    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    try:
        parsed = _parse_json(resp.text or "{}")
    except json.JSONDecodeError:
        return {"detected": False, "confidence": 0.0, "context": "parse_error", "raw": resp.text}
    parsed["model"] = model
    return parsed


BATCH_FRAMES_SUFFIX = """

MULTI-FRAME MODE
You are given {n} frames sampled from ONE short video, labelled FRAME 0 ... FRAME {last}.
Judge EACH frame independently against the rules above — a wordmark you read in
one frame does NOT license a detection in another where you cannot read it.

Return a STRICT JSON array of exactly {n} objects, one per frame, in frame order.
Each object uses the schema above PLUS an integer "frame_index" field naming the
frame it describes. No prose, no markdown fences, no wrapper object.
"""


def detect_frames_batch(
    frames: list[tuple[int, bytes]],
    brand_name: str,
    product_lines: dict[str, str],
    reference_image_bytes: list[bytes] | None = None,
    model: str = "gemini-2.5-flash",
    usage_out: dict | None = None,
) -> list[dict[str, Any]]:
    """Judge every sampled frame of one video in a SINGLE Gemini call.

    Returns a list aligned to `frames`, each entry the same shape as
    detect_image(). Raises on any response that cannot be aligned, so the
    caller can fall back to per-frame calls rather than silently mis-attribute
    a detection to the wrong frame.

    Why: detect_video called detect_image.run() once per frame, and every one
    of those calls re-sent all 8 reference images. At 6 frames that is 48
    reference images transmitted to describe one video — roughly 62% of the
    spend was retransmitting identical bytes. Batching sends the references
    once, so each extra frame costs only its own ~258 image tokens.

    Order is [references, prompt, frames]: the references and prompt form a
    stable prefix shared by every video, which is what Gemini's implicit
    context caching can discount. Putting a frame before the prompt (as the
    single-image path does) would break that prefix on every call.
    """
    if not frames:
        return []
    n = len(frames)
    prompt = DETECT_PROMPT_V8.format(
        brand_name=brand_name,
        product_lines=", ".join(f"{k} ({v})" for k, v in product_lines.items()),
        product_line_keys=", ".join(product_lines.keys()),
    ) + BATCH_FRAMES_SUFFIX.format(n=n, last=n - 1)

    contents: list[Any] = []
    if reference_image_bytes:
        contents.append("Reference images of the brand product (what to look for):")
        for ref in reference_image_bytes[:8]:
            contents.append(genai_types.Part.from_bytes(data=ref, mime_type=_sniff_mime(ref)))
    contents.append(prompt)
    for i, (_src_idx, jpeg) in enumerate(frames):
        # Label every frame in text. Relying on positional order alone makes a
        # dropped or merged frame silently shift every later verdict onto the
        # wrong frame — a detection attributed to the wrong timestamp.
        contents.append(f"FRAME {i}:")
        contents.append(genai_types.Part.from_bytes(data=jpeg, mime_type=_sniff_mime(jpeg)))

    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    if usage_out is not None:
        # Real token counts, so spend can be recorded from what was actually
        # billed rather than a flat per-call constant. `cached` is the portion
        # discounted by implicit context caching — the number that tells you
        # whether the stable [references, prompt] prefix is doing its job.
        um = getattr(resp, "usage_metadata", None)
        usage_out.update({
            "prompt_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "cached_tokens": getattr(um, "cached_content_token_count", None),
            "total_tokens": getattr(um, "total_token_count", None),
            "frames": n,
        })

    parsed = _parse_json(resp.text or "[]")
    # Tolerate a wrapper object — models sometimes return {"frames": [...]}.
    if isinstance(parsed, dict):
        for key in ("frames", "results", "detections"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
    if not isinstance(parsed, list):
        raise ValueError(f"batch response is {type(parsed).__name__}, expected list")
    if len(parsed) != n:
        raise ValueError(f"batch returned {len(parsed)} objects for {n} frames")

    out: list[dict[str, Any]] = [{} for _ in range(n)]
    for pos, obj in enumerate(parsed):
        if not isinstance(obj, dict):
            raise ValueError(f"batch entry {pos} is {type(obj).__name__}, expected object")
        # Trust frame_index when it is present and sane; fall back to position.
        idx = obj.get("frame_index")
        slot = idx if isinstance(idx, int) and 0 <= idx < n else pos
        if out[slot]:
            raise ValueError(f"batch assigned two verdicts to frame {slot}")
        obj["model"] = model
        obj["batched"] = True
        out[slot] = obj
    if any(not o for o in out):
        raise ValueError("batch left a frame unjudged")
    return out


# NOTE: score_creator_relevance was removed in the productization cleanup.
# Its signal (relevance 0-10, dutch speaker, content theme) is already
# covered by SRS layers (hashtag cosine + geo) at zero Gemini cost.
# See plan: ~/.claude/plans/slack-gibi-disariya-bisye-witty-dream.md §B.


def analyze_sentiment(
    brand_name: str,
    summary: str,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any] | None:
    """How this post talks about the brand. Text-only — no images.

    Returns None when the model's answer is unusable, so the caller can leave
    the field unset and retry the post on a later run rather than persist a
    guess. See lib/sentiment.py for why this is not folded into detect_image.
    """
    contents: list[Any] = [sentiment.build_prompt(brand_name), summary]
    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            # Fixed answer set, same reasoning as verify_brand: sampling
            # variance on a four-way classification is pure downside.
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    parsed = sentiment.parse_verdict(resp.text or "")
    if parsed is None:
        return None
    parsed["model"] = model
    return parsed


def verify_brand(
    image_bytes: bytes,
    brand_name: str,
    reference_image_bytes: list[bytes] | None = None,
    negative_exemplars: list[tuple[str, bytes]] | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Second look: open-choice brand identification on one image.

    Deliberately different from detect_image in three ways, all of them the
    reason this call is worth making at all (see lib/verifier.py docstring):

      * the caller passes a HIGHER-RESOLUTION or CROPPED image — more pixels is
        the actual new information, not a smarter judge;
      * the prompt never states what the first pass concluded, so there is
        nothing to acquiesce to;
      * the answer is a choice among named brands, not a yes/no about one.

    Reference images still go first (Gemini anchors on earlier images), but the
    prompt explicitly warns that the target usually does NOT contain them —
    without that line, showing 8 Stelz packshots is itself a leading question.
    """
    prompt = verifier.build_prompt(brand_name)
    contents: list[Any] = []
    if reference_image_bytes:
        contents.append(
            f"Reference photos of {brand_name} products. The target photo below "
            f"often shows a DIFFERENT brand — use these to compare, not to expect:"
        )
        for ref in reference_image_bytes[:8]:
            contents.append(genai_types.Part.from_bytes(data=ref, mime_type=_sniff_mime(ref)))

    # Moderator-confirmed false positives, each preceded by its own label. The
    # label is NOT optional decoration: the legacy pipeline emitted these same
    # images as bare "Reference {i}:" parts and so taught the detector that
    # twelve confirmed non-Stelz photos WERE Stelz. verifier.build_negative_exemplars
    # only ever returns (label, bytes) pairs so this cannot be got wrong here.
    for label, blob in (negative_exemplars or []):
        contents.append(label)
        contents.append(genai_types.Part.from_bytes(data=blob, mime_type=_sniff_mime(blob)))

    contents.append("Target photo — identify the brand actually shown:")
    contents.append(genai_types.Part.from_bytes(data=image_bytes, mime_type=_sniff_mime(image_bytes)))
    contents.append(prompt)

    resp = client().models.generate_content(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            # 0.0, not the 0.1 used for detection: this is a classification with
            # a fixed answer set, so sampling variance is pure downside.
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    parsed = verifier.parse_verdict(resp.text or "{}")
    parsed["model"] = model
    return parsed
