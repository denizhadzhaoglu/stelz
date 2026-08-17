"""Reference image loader.

Pulls the brand's uploaded reference images from Firestore + Cloud Storage,
resizes them to a max-dim of 512px (smaller payload = cheaper Gemini call +
faster), and caches the bytes in-process for the lifetime of the Cloud
Function instance. A new function instance refetches once.
"""
from __future__ import annotations
import io
import logging
import time
from typing import Optional

import requests
from PIL import Image

from . import fs

log = logging.getLogger(__name__)

# In-process cache: brand_id -> (timestamp, [bytes])
_CACHE: dict[str, tuple[float, list[bytes]]] = {}
_TTL_SECONDS = 30 * 60  # 30 min: refresh refs every half hour
_MAX_DIM = 512


def _resize(b: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(b))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > _MAX_DIM:
            s = _MAX_DIM / max(w, h)
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        log.warning(f"resize failed: {e}")
        return b


def _select_reference_docs(docs: list[dict], max_count: int) -> list[dict]:
    """Pick which reference photos the model gets to see.

    Two rules, in order:
      1. Cover every product line at least once. An unstratified pick can end up
         all Hard Seltzer, leaving the model with no idea what a Hard Iced Tea or
         Mixed Classics can looks like — a plausible source of whole-product-line
         misses.
      2. Within that, prefer the most recently uploaded (newer packshots are the
         curated ones; the earliest uploads are usually first-pass scraps).

    Sorting happens in Python rather than via Firestore order_by on purpose:
    an order_by silently EXCLUDES documents missing the sort field, and
    server-seeded reference docs may not carry `uploadedAt`.
    """
    def _key(d: dict):
        ts = d.get("uploadedAt")
        # Firestore timestamps sort natively; missing -> oldest.
        return (ts is not None, ts)

    ordered = sorted(docs, key=_key, reverse=True)

    picked: list[dict] = []
    seen_lines: set[str] = set()
    # Pass 1 — one per product line.
    for d in ordered:
        if len(picked) >= max_count:
            break
        line = d.get("productLine") or "_none"
        if line not in seen_lines:
            seen_lines.add(line)
            picked.append(d)
    # Pass 2 — fill remaining slots newest-first.
    for d in ordered:
        if len(picked) >= max_count:
            break
        if d not in picked:
            picked.append(d)
    return picked


def load_references(brand_id: str, max_count: int = 8) -> list[bytes]:
    """Return up to N reference image byte blobs for the brand."""
    cached = _CACHE.get(brand_id)
    if cached and (time.time() - cached[0] < _TTL_SECONDS):
        return cached[1][:max_count]

    # Fetch a wider pool than we need, then select. The previous version took
    # the first `max_count` docs from an UNORDERED query — and since Firestore
    # returns document-name ascending and reference doc IDs are prefixed with
    # `Date.now()` (web/src/lib/firestore.ts:268), that was deterministically
    # the 8 OLDEST uploads. Every packshot uploaded after the first 8 was
    # silently invisible to the detector, no matter how good it was.
    raw = [d.to_dict() or {} for d in fs.reference_images_col(brand_id).limit(60).stream()]
    urls = [d["url"] for d in _select_reference_docs(raw, max_count) if d.get("url")]

    blobs: list[bytes] = []
    for url in urls:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            blobs.append(_resize(r.content))
        except Exception as e:
            log.warning(f"ref fetch failed for {url}: {e}")
            continue

    _CACHE[brand_id] = (time.time(), blobs)
    log.info(f"[{brand_id}] loaded {len(blobs)} reference images")
    return blobs


def invalidate(brand_id: Optional[str] = None):
    """Manually clear cache (e.g. after a new upload)."""
    if brand_id:
        _CACHE.pop(brand_id, None)
    else:
        _CACHE.clear()


# In-process cache for negative exemplars: brand_id -> (timestamp, [(label, bytes)])
_NEG_CACHE: dict[str, tuple[float, list[tuple[str, bytes]]]] = {}


def load_negative_exemplars(brand_id: str, brand_name: str = "STELZ", limit: int = 4):
    """Moderator-rejected detections, as labelled negative exemplars.

    This is the only thing in the pipeline that reads `isFalsePositive` back out
    of Firestore. Before it, a moderator's ✕ changed nothing: the rejection was
    written to the detection doc and consumed solely by the web UI's filters, so
    the same image on a repost was re-detected as a hit forever.

    Returns (label, bytes) PAIRS — never bare bytes. See verifier.build_negative_exemplars
    for why that signature is load-bearing.

    Failures return [] rather than raising: a missing thumbnail or a Firestore
    hiccup must degrade the verifier to "no exemplars", never break detection.
    """
    from lib import verifier  # local import: verifier imports nothing from refs

    cached = _NEG_CACHE.get(brand_id)
    if cached and (time.time() - cached[0] < _TTL_SECONDS):
        return cached[1]

    rows: list[dict] = []
    try:
        # Ordered by verifiedAt desc so the exemplars track what the moderator is
        # rejecting NOW. Pull a wider slice than needed: rows whose thumbnail has
        # expired are dropped below, and without slack a few dead URLs would
        # leave the verifier with no exemplars at all.
        q = (
            fs.detections_col(brand_id)
            .where("isFalsePositive", "==", True)
            .order_by("verifiedAt", direction="DESCENDING")
            .limit(limit * 4)
        )
        for d in q.stream():
            x = d.to_dict() or {}
            url = x.get("storedUrl") or x.get("imageUrl")
            if not url:
                continue
            rows.append({
                "url": url,
                "visibleText": x.get("visibleText"),
                # A rejection of something the model was CONFIDENT about teaches
                # more than a rejection of something it already doubted.
                "highSignal": float(x.get("modelConfidence") or x.get("confidence") or 0) >= 0.9,
            })
    except Exception as e:
        log.warning(f"[{brand_id}] could not load rejected detections: {e}")
        return []

    fetched: list[dict] = []
    for r in rows:
        if len(fetched) >= limit:
            break
        try:
            resp = requests.get(r["url"], timeout=15)
            resp.raise_for_status()
            fetched.append({**r, "imageBytes": _resize(resp.content)})
        except Exception:
            continue  # expired CDN link; skip quietly

    out = verifier.build_negative_exemplars(fetched, brand_name=brand_name, limit=limit)
    _NEG_CACHE[brand_id] = (time.time(), out)
    log.info(f"[{brand_id}] loaded {len(out)} negative exemplars from moderator rejections")
    return out
