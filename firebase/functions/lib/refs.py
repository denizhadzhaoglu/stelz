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


def load_references(brand_id: str, max_count: int = 8) -> list[bytes]:
    """Return up to N reference image byte blobs for the brand."""
    cached = _CACHE.get(brand_id)
    if cached and (time.time() - cached[0] < _TTL_SECONDS):
        return cached[1][:max_count]

    # Pull doc URLs from Firestore
    urls: list[str] = []
    for d in fs.reference_images_col(brand_id).limit(15).stream():
        data = d.to_dict() or {}
        url = data.get("url")
        if url:
            urls.append(url)
        if len(urls) >= max_count:
            break

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
