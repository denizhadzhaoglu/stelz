"""Second look at a detection the first pass was not sure about.

WHY A SECOND PASS AT ALL
The first pass sees a 512px downscale (detect_image.MAX_IMAGE_DIM). On a can
that is `medium` or `small` in frame the wordmark is a handful of pixels — the
model is being asked to read text that is physically not resolvable, and
`_strictness_gate` then caps the result to 0.70. Measured on the labelled golden
set, that band runs ~1-in-3 wrong, and NOTHING in the stored fields separates its
good rows from its bad ones: the true and false positives share confidence,
text_legibility, false_positive_risk and gate label. The only way out is to look
at the image again with more pixels.

WHY THIS IS NOT THE VERIFIER THAT ALREADY FAILED
A Pro-model verify chain existed in the legacy Supabase stack
(tools/stelz_brand_watch/17_verify_with_pro.py) and its own training data records
it failing: the moderator note on fewshot_neg_00 reads "The model AND the Pro
verify chain BOTH marked this as a trusted STELZ detection — but a human
moderator rejected it." Two design faults explain that, and both are avoided
here:

  1. It re-asked the SAME QUESTION about the SAME PIXELS — 512px, full frame,
     just a bigger model. Errors between models of one family are correlated, so
     that mostly buys a second vote for the first answer. Here the input changes:
     higher resolution, cropped to the object.

  2. It asked a LEADING question — "A previous less-precise model claimed to
     detect STËLZ in this image. Your job is to verify or reject." VLMs carry a
     documented yes-bias on binary questions (POPE, HallusionBench), so a prompt
     that names the expected answer invites confirmation. Here the verifier is
     never told what the first pass concluded, and the question is open: which
     brand is this, from a list where STELZ is one option among rivals.

Deliberately NOT ported from the legacy chain: it fed the twelve moderator-
REJECTED images into three scripts as unlabelled POSITIVE references
(18_daily_scan.py:139, 33_detect_pending.py:128, 42_zoom_verify.py:130). Any
negative exemplar here must carry its label in text.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any

from PIL import Image

log = logging.getLogger(__name__)

# Bump when the prompt or decision rule changes in a way that makes old verdicts
# incomparable. Stored INSIDE the cached detection result, deliberately not as a
# promptVersion bump: the image cache holds one slot per image hash
# (lib/cache.py) and promptVersion is a stored field, not part of the key — so
# bumping it invalidates the whole corpus and re-bills every image ever scanned.
# Versioning in the payload lets a stale verdict be re-verified lazily, one
# image at a time, on the next cache hit.
VERIFY_VERSION = 1

# Resolution for the second look. 4x the pixel area of the first pass, which is
# the entire point — see the module docstring.
VERIFY_MAX_DIM = 1024

# Fraction of frame area below which a bbox crop is worth a second call. A can
# occupying less than this is still tiny even at 1024px.
CROP_AREA_THRESHOLD = 0.15
# Padding around the bbox, as a fraction of box size. Context helps identify a
# can; a pixel-tight crop of a wordmark loses the shape and cap that distinguish
# a Stelz can from a rival's.
CROP_PADDING = 0.25

# The choices the verifier picks from. Naming rivals explicitly turns a yes/no
# into a discrimination task — the model has to prefer STELZ over a named
# alternative rather than merely assent to it. Sourced from DETECT_PROMPT_V8
# rule 2 plus the brands actually observed in golden-set transcripts.
BRAND_CHOICES = [
    "STELZ", "White Claw", "Truly", "Bavaria", "Heineken", "Grolsch", "Amstel",
    "Red Bull", "Monster", "Coca-Cola", "Desperados", "Corona", "Budweiser",
    "other_brand", "no_readable_brand", "not_a_container",
]

VERIFY_PROMPT = """You are identifying which drinks brand appears in a photo.

You are shown reference photos of ONE brand's products, then a target photo.

Do NOT assume the target contains that brand. It very often does not. Your job
is to say what is actually in the target photo, whatever that turns out to be.

STEP 1 — Find the container. Locate the most prominent beverage container (can,
bottle, glass) in the target photo. If there is none, answer "not_a_container".

STEP 2 — Read it. Transcribe ONLY characters you can genuinely resolve in the
pixels. Use '?' for characters you cannot make out. If the label is too small,
blurry, turned away or occluded, the transcript is null — do not guess what it
"probably" says, and do not copy text from the reference photos.

STEP 3 — Choose. Which of these is on the container?
{choices}

Choose "{brand}" ONLY if you can read its wordmark, or the label layout matches
the reference photos beyond reasonable doubt. Choose "no_readable_brand" when
something is clearly there but you cannot read it — that is a normal, useful
answer, not a failure. Choose "other_brand" for a readable brand not in the list.

Return STRICT JSON ONLY (no prose, no markdown fences):
{{
  "brand": "<exactly one value from the list above>",
  "visible_text": "<what you actually read, or null>",
  "confidence": 0.0-1.0,
  "box_2d": [y1, x1, y2, x2] or null,
  "reason": "<one short sentence: which features decided it>"
}}

box_2d: normalized 0-1000, origin TOP-LEFT, y before x, tight to the container.
Return null rather than a guess if you cannot localize it confidently.
"""


def build_prompt(brand_name: str = "STELZ") -> str:
    """Render the verifier prompt. Separate from the constant so the choice list
    stays in one place and the tests can assert on it."""
    return VERIFY_PROMPT.format(
        choices="\n".join(f"  - {c}" for c in BRAND_CHOICES),
        brand=brand_name.upper(),
    )


def should_verify(result: dict[str, Any]) -> bool:
    """Is this detection in the population the verifier exists for?

    Only demoted hits. A clean read of a large can (>=0.85, ungated) is not where
    the errors are — measured 8/8 correct on the golden set — and verifying it
    would multiply cost for no precision gain. A non-detection is not verified
    either: this pass exists to remove false positives and rescue capped true
    ones, not to re-open everything the gate rejected.
    """
    if not result.get("detected"):
        return False
    if result.get("gate") in ("capped_small_object", "accepted_partial_wordmark"):
        return True
    return float(result.get("confidence") or 0) < 0.85


def needs_reverify(result: dict[str, Any]) -> bool:
    """Should a CACHED detection be sent through the verifier?

    The imageHashCache short-circuits detection entirely: on a hit,
    detect_image.run persists the stored verdict and returns before the verify
    pass. That is correct for the Gemini call — the answer would be identical
    and it would be re-billed — but it meant the verifier only ever touched
    images the pipeline had never seen. The existing back catalogue, which is
    what the operator actually looks at in the feed, kept its pre-verifier
    verdicts forever.

    So a cache hit is re-verified once, when it is a demoted hit that carries no
    verdict at the current version. It is then written back to the cache and
    never re-verified again.

    Deliberately lazy rather than a backfill job: work happens only on images a
    scan actually re-encounters, so the cost is bounded by scan volume instead of
    by catalogue size, and no migration has to be scheduled or supervised.

    Why not just bump promptVersion to force this? Because the cache holds ONE
    slot per image hash and promptVersion is a stored field, not part of the key
    — bumping it invalidates every entry and re-bills full detection on the whole
    corpus. This re-runs only the cheap second pass, only where it is missing.
    """
    if not should_verify(result):
        return False
    # Coerce defensively. This runs inside the detection path on every cache
    # hit, and the value comes back out of Firestore where a bad write or an
    # older schema could leave anything at all. A crash here would take down
    # detection for that image, so an unreadable version counts as "not
    # verified" and the image simply gets a second look.
    try:
        seen = int(result.get("verify_version") or 0)
    except (TypeError, ValueError):
        seen = 0
    return seen < VERIFY_VERSION


def needs_crop(box: list | None, threshold: float = CROP_AREA_THRESHOLD) -> bool:
    """Is the located container small enough that a crop would add real detail?"""
    if not box or len(box) != 4:
        return False
    y1, x1, y2, x2 = box
    area = (max(0, y2 - y1) / 1000.0) * (max(0, x2 - x1) / 1000.0)
    return 0 < area < threshold


def crop_to_box(image_bytes: bytes, box: list, padding: float = CROP_PADDING) -> bytes | None:
    """Crop to a normalized [y1,x1,y2,x2] box (0-1000), with padding.

    Returns None when the box is degenerate — a caller must treat that as "no
    crop available" rather than falling back to the full frame silently, or the
    second call is just the first call again at extra cost.
    """
    try:
        y1, x1, y2, x2 = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if y2 <= y1 or x2 <= x1:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        bw, bh = (x2 - x1) / 1000.0 * w, (y2 - y1) / 1000.0 * h
        px, py = bw * padding, bh * padding
        left = max(0, int(x1 / 1000.0 * w - px))
        top = max(0, int(y1 / 1000.0 * h - py))
        right = min(w, int(x2 / 1000.0 * w + px))
        bottom = min(h, int(y2 / 1000.0 * h + py))
        if right <= left or bottom <= top:
            return None
        out = io.BytesIO()
        img.crop((left, top, right, bottom)).save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception as e:
        log.warning(f"crop failed: {e}")
        return None


def decide(result: dict[str, Any], verdict: dict[str, Any], brand_slug: str = "stelz") -> dict[str, Any]:
    """Merge a verifier verdict into a detection result.

    Three outcomes, not two. `upgraded` matters as much as `rejected`: the whole
    reason these rows sit at 0.70 is that the first pass could not resolve the
    label, so a verifier that reads it cleanly should be allowed to RAISE the
    score and lift the row out of the review band. A verifier that can only ever
    remove things makes the feed smaller, which is the opposite of the ask.
    """
    out = dict(result)
    brand = (verdict.get("brand") or "").strip()
    vconf = float(verdict.get("confidence") or 0)
    out["verify_version"] = VERIFY_VERSION
    out["verify_brand"] = brand or None
    out["verify_reason"] = (verdict.get("reason") or "")[:300] or None

    if brand.lower() == brand_slug.lower():
        # Only promote on a confident, clean read. A hesitant "probably STELZ"
        # leaves the row exactly where it was — visible, but still flagged.
        if vconf >= 0.85:
            out["confidence"] = max(float(out.get("confidence") or 0), 0.90)
            out["verify_verdict"] = "upgraded"
            out["gate"] = "verified_upgraded"
        else:
            out["verify_verdict"] = "confirmed"
        return out

    # LEGIBILITY CONTRADICTION.
    #
    # The first pass claimed it read the label CLEARLY. This pass looked at the
    # same image with 4x the pixel area and could not find a readable brand at
    # all. Both cannot be true: added resolution can only make text easier to
    # read, never harder. So the "clear" read was fabricated, and the first pass
    # is what gets disbelieved.
    #
    # This is a monotonicity argument, not a tuned threshold — which matters,
    # because it is currently validated on exactly one image (fewshot_neg_00,
    # the HIGH_SIGNAL case that fooled both the original model and the legacy
    # Pro verify chain). The reasoning is what justifies it, not the sample.
    #
    # Deliberately narrow: only an EXPLICIT "no_readable_brand" counts. A missing
    # or garbled verdict means the call failed, which is not evidence of
    # anything, and must not delete a detection.
    if brand == "no_readable_brand" and result.get("text_legibility") == "clear":
        out["detected"] = False
        out["verify_verdict"] = "rejected"
        out["gate"] = "rejected_legibility_contradiction"
        out["false_positive_risk"] = "high"
        out["verify_reason"] = (
            "The first pass reported a clear read of the label; at higher resolution "
            "no brand was readable at all. A clear read that disappears with more "
            "pixels was not a read."
        )
        return out

    # "no_readable_brand" where the first pass ALSO admitted the label was
    # partial or unreadable — the two passes agree, and neither could resolve it.
    # NOT a rejection: the first pass may have had a frame or crop this call did
    # not, and treating "I can't tell" as "it isn't there" deletes true positives
    # on model uncertainty rather than on evidence.
    #
    # This check MUST come before the rejection branch below. It did not, and the
    # test caught it: "no_readable_brand" is a non-empty string that isn't the
    # brand slug, so it fell straight through into a rejection — the exact
    # failure mode this whole module is written to avoid.
    if not brand or brand == "no_readable_brand":
        out["verify_verdict"] = "inconclusive"
        return out

    # Everything left is something the verifier could actually read, and it is
    # not ours: a rival's wordmark, an unlisted brand, or not a container.
    out["detected"] = False
    out["verify_verdict"] = "rejected"
    out["gate"] = "rejected_by_verifier"
    out["false_positive_risk"] = "high"
    return out


def parse_verdict(text: str) -> dict[str, Any]:
    """Parse the verifier's JSON, tolerating markdown fences.

    Mirrors gemini._parse_json rather than importing it, so this module stays
    importable without the google genai SDK (the tests rely on that).
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1] if "```" in t[3:] else t[3:]
        if t.startswith("json"):
            t = t[4:]
    try:
        parsed = json.loads(t.strip())
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


# ─────────────────── moderator feedback ───────────────────
#
# Every ✕ a moderator clicks currently teaches the system NOTHING. api_rate_detection
# (main.py) writes `isFalsePositive` to the detection doc, and no server-side code
# reads it back — grep it: the only consumers are the web UI's filters. The same
# image on a repost is re-detected as a hit, forever.
#
# These helpers close that loop for the verifier: confirmed false positives become
# LABELLED NEGATIVE exemplars in the verify prompt.
#
# THE BUG NOT TO REPEAT. The legacy stack built exactly this training set
# (29_train_from_moderator.py) and then three scripts loaded it with
# `include_training=True` and emitted the images as bare "Reference {i}:" parts —
# feeding twelve confirmed FALSE POSITIVES to the detector as POSITIVE examples of
# the brand (18_daily_scan.py:139, 33_detect_pending.py:128, 42_zoom_verify.py:130).
# That is a plausible standalone cause of the competitor-can false positives this
# module exists to fix.
#
# Hence: an exemplar here is a (label, bytes) PAIR and there is no API that returns
# the bytes alone. The label always travels with the image, and the tests assert it.

MAX_NEGATIVE_EXEMPLARS = 4

NEGATIVE_LABEL = (
    "NEGATIVE EXAMPLE — a human reviewer confirmed this is NOT {brand}. "
    "The detector claimed to see it here and was wrong. Do not treat this as "
    "a picture of the product."
)


def build_negative_exemplars(
    rejected: list[dict],
    brand_name: str = "STELZ",
    limit: int = MAX_NEGATIVE_EXEMPLARS,
) -> list[tuple[str, bytes]]:
    """Turn moderator-rejected detections into labelled negative exemplars.

    `rejected` items need `imageBytes`, and may carry `visibleText` (what the
    detector wrongly claimed to read) and `highSignal`.

    Ordering is deliberate: HIGH-SIGNAL rejections first. Those are the ones a
    human overturned after the model was CONFIDENT — the legacy trainer's note
    calls them "the most valuable negatives because they teach the model where
    its own confident predictions fail". With only a handful of slots, spending
    them on the model's confident mistakes beats spending them on its hesitant
    ones.
    """
    ordered = sorted(rejected, key=lambda r: not r.get("highSignal"))
    out: list[tuple[str, bytes]] = []
    for r in ordered:
        if len(out) >= limit:
            break
        blob = r.get("imageBytes")
        if not blob:
            continue
        label = NEGATIVE_LABEL.format(brand=brand_name)
        claimed = (r.get("visibleText") or "").strip()
        if claimed:
            # Naming the specific hallucinated string is the whole lesson: the
            # model is being shown the text it invented, next to the image that
            # does not contain it.
            label += f' It wrongly read "{claimed[:120]}" here.'
        out.append((label, blob))
    return out
