"""Gemini Vision wrapper for brand detection."""
from __future__ import annotations
import io
import json
import os
import re
from typing import Any

import requests
from google import genai
from google.genai import types as genai_types


def _key() -> str:
    k = os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not k:
        raise RuntimeError("GOOGLE_AI_API_KEY not set")
    return k


_client = None

def client():
    global _client
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


def detect_image(
    image_url: str,
    brand_name: str,
    product_lines: dict[str, str],
    brand_identity: str | None = None,
    reference_image_bytes: list[bytes] | None = None,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Run Gemini detection on a single image URL, with optional reference images
    of the brand product so the model can visually match (much higher precision)."""
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
            contents.append(genai_types.Part.from_bytes(data=ref, mime_type="image/jpeg"))
    contents.append("Target image (user post — does this contain the brand?):")
    contents.append(genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
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


# NOTE: score_creator_relevance was removed in the productization cleanup.
# Its signal (relevance 0-10, dutch speaker, content theme) is already
# covered by SRS layers (hashtag cosine + geo) at zero Gemini cost.
# See plan: ~/.claude/plans/slack-gibi-disariya-bisye-witty-dream.md §B.
