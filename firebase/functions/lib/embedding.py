"""Embedding-based pre-filter for brand detection.

Uses **Vertex AI's `multimodalembedding@001`** model which natively accepts
image bytes and returns a 1408-dim vector. We compute one centroid from the
brand's reference images (mean of their embeddings) and then cosine-compare
every candidate image against it. Sub-threshold candidates skip Gemini Flash
entirely.

Why this and not gemini-embedding-001: that model is text-only and rejects
image bytes with "text content is empty".

Cost: $0.0001 per image embedding. With 1000 candidates/day = ~$0.10/day.
That's ~50× cheaper than Gemini Flash detection ($0.005/call).

Storage shape (in Firestore):
  /brands/{brandId}.visualCentroid: list[float]  (1408-dim mean vector)
  /brands/{brandId}.visualCentroidComputedAt: timestamp
  /brands/{brandId}.visualCentroidRefCount: int
"""
from __future__ import annotations
import base64
import logging
import math
import os
from typing import Optional

import requests
import google.auth
import google.auth.transport.requests

from . import fs

log = logging.getLogger(__name__)

CENTROID_DIM = 1408  # multimodalembedding@001 default dim
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
VERTEX_PROJECT = os.getenv("GCLOUD_PROJECT") or os.getenv("GCP_PROJECT") or "brand-audit-4b2cc"

# Cosine threshold: tuned generously (recall > precision at the pre-filter
# stage — Gemini Flash does the precision step downstream).
COSINE_THRESHOLD_DEFAULT = 0.55

# In-process cache: brand_id -> (computedAt iso, centroid list)
_CENTROID_CACHE: dict[str, tuple[str, list[float]]] = {}

_AUTH_CREDS = None


def _get_access_token() -> str:
    """Refresh+cache application-default credentials for Vertex AI REST."""
    global _AUTH_CREDS
    if _AUTH_CREDS is None:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _AUTH_CREDS = creds
    if not _AUTH_CREDS.valid:
        _AUTH_CREDS.refresh(google.auth.transport.requests.Request())
    return _AUTH_CREDS.token


def _embed_image_bytes(image_bytes: bytes) -> Optional[list[float]]:
    """Embed an image via Vertex AI multimodalembedding@001. Returns 1408-dim
    vector or None on failure."""
    url = (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/"
        f"{VERTEX_PROJECT}/locations/{VERTEX_LOCATION}/publishers/google/"
        f"models/multimodalembedding@001:predict"
    )
    body = {
        "instances": [{
            "image": {"bytesBase64Encoded": base64.b64encode(image_bytes).decode("ascii")}
        }]
    }
    try:
        token = _get_access_token()
        r = requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning(f"embed image http {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        preds = data.get("predictions") or []
        if not preds:
            return None
        emb = preds[0].get("imageEmbedding")
        if not emb:
            return None
        return list(emb)
    except Exception as e:
        log.warning(f"embed image failed: {e}")
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(x * x for x in b[:n]))
    return dot / (na * nb) if na and nb else 0.0


def get_brand_centroid(brand_id: str) -> Optional[list[float]]:
    """Load centroid from cache → Firestore. Returns None if not computed."""
    cached = _CENTROID_CACHE.get(brand_id)
    if cached:
        return cached[1]
    snap = fs.brand_doc(brand_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    centroid = data.get("visualCentroid")
    if isinstance(centroid, list) and centroid:
        _CENTROID_CACHE[brand_id] = (data.get("visualCentroidComputedAt") or "", centroid)
        return centroid
    return None


def invalidate_cache(brand_id: Optional[str] = None):
    if brand_id:
        _CENTROID_CACHE.pop(brand_id, None)
    else:
        _CENTROID_CACHE.clear()


def compute_centroid(brand_id: str, max_refs: int = 8) -> tuple[Optional[list[float]], dict]:
    """Recompute the brand visual centroid from referenceImages.
    Returns (centroid_or_none, diagnostic_dict). The diagnostic helps the UI
    explain why centroid couldn't be computed (no refs, all fetches failed, etc.).
    """
    refs_q = fs.reference_images_col(brand_id).limit(max_refs).stream()
    urls = []
    for d in refs_q:
        data = d.to_dict() or {}
        if data.get("url"):
            urls.append(data["url"])

    diag = {"refsFound": len(urls), "refsUsed": 0, "fetchErrors": [], "embedErrors": 0}

    if not urls:
        log.info(f"[{brand_id}] no reference images, skipping centroid")
        # Clear stale centroid so detection doesn't keep matching against an
        # outdated set after the user removed all refs.
        fs.brand_doc(brand_id).set({
            "visualCentroid": None,
            "visualCentroidRefCount": 0,
        }, merge=True)
        invalidate_cache(brand_id)
        return None, diag

    vectors: list[list[float]] = []
    for url in urls:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            emb = _embed_image_bytes(r.content)
            if emb:
                vectors.append(emb)
            else:
                diag["embedErrors"] += 1
        except Exception as e:
            log.warning(f"centroid ref fetch/embed failed for {url}: {e}")
            diag["fetchErrors"].append(str(e)[:120])

    diag["refsUsed"] = len(vectors)

    if not vectors:
        return None, diag

    dim = len(vectors[0])
    centroid = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]

    from google.cloud.firestore import SERVER_TIMESTAMP
    fs.brand_doc(brand_id).set({
        "visualCentroid": centroid,
        "visualCentroidComputedAt": SERVER_TIMESTAMP,
        "visualCentroidRefCount": len(vectors),
    }, merge=True)
    invalidate_cache(brand_id)
    log.info(f"[{brand_id}] centroid recomputed from {len(vectors)} refs")
    return centroid, diag


def score_image_vs_brand(image_bytes: bytes, brand_id: str) -> Optional[float]:
    """Return cosine(image_embedding, brand_centroid), or None if no centroid."""
    centroid = get_brand_centroid(brand_id)
    if centroid is None:
        return None
    emb = _embed_image_bytes(image_bytes)
    if emb is None:
        return None
    return cosine(emb, centroid)
