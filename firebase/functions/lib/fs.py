"""Firestore helpers: typed paths + cached client.

Schema (Firestore):
  /brands/{brandId}
    /members/{uid}
    /creators/{creatorId}
    /posts/{postId}
      /images/{imageId}
    /detections/{detectionId}
    /resonance/{handle_platform}
    /edges/{edgeId}
    /discoveryQueue/{handle_platform}
    /hashtagPool/{hashtag}
    /referenceImages/{imageId}
    /imageHashCache/{hash}
    /scanRuns/{runId}

  /users/{uid}
    /shortlists/{detectionId}
"""
from __future__ import annotations
import os
from typing import Any

import firebase_admin
from firebase_admin import firestore, storage, credentials

_app = None


def _ensure_app() -> firebase_admin.App:
    global _app
    if _app is not None:
        return _app
    # On Cloud Functions, default credentials are available.
    if not firebase_admin._apps:
        bucket = os.getenv("STORAGE_BUCKET", "brand-audit-4b2cc.firebasestorage.app")
        try:
            _app = firebase_admin.initialize_app(options={"storageBucket": bucket})
        except ValueError:
            # Local dev: use service-account JSON path
            sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if sa_path and os.path.exists(sa_path):
                _app = firebase_admin.initialize_app(
                    credentials.Certificate(sa_path),
                    options={"storageBucket": bucket},
                )
            else:
                raise
    else:
        _app = firebase_admin.get_app()
    return _app


def db():
    """Get the Firestore client (cached)."""
    _ensure_app()
    return firestore.client()


def bucket():
    """Get the default Cloud Storage bucket."""
    _ensure_app()
    return storage.bucket()


# ─── Path helpers ───────────────────────────────────────────

def brands_col():
    return db().collection("brands")


def brand_doc(brand_id: str):
    return brands_col().document(brand_id)


def creators_col(brand_id: str):
    return brand_doc(brand_id).collection("creators")


def posts_col(brand_id: str):
    return brand_doc(brand_id).collection("posts")


def detections_col(brand_id: str):
    return brand_doc(brand_id).collection("detections")


def resonance_col(brand_id: str):
    return brand_doc(brand_id).collection("resonance")


def edges_col(brand_id: str):
    return brand_doc(brand_id).collection("edges")


def discovery_queue_col(brand_id: str):
    return brand_doc(brand_id).collection("discoveryQueue")


def hashtag_pool_col(brand_id: str):
    return brand_doc(brand_id).collection("hashtagPool")


def reference_images_col(brand_id: str):
    return brand_doc(brand_id).collection("referenceImages")


def image_hash_cache_col(brand_id: str):
    return brand_doc(brand_id).collection("imageHashCache")


def scan_runs_col(brand_id: str):
    return brand_doc(brand_id).collection("scanRuns")


def usage_doc(brand_id: str, day_iso: str | None = None):
    """Per-day usage counter doc — incremented from each handler.
    day_iso defaults to today's UTC date YYYY-MM-DD."""
    import datetime as _dt
    if day_iso is None:
        day_iso = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    return brand_doc(brand_id).collection("usage").document(day_iso)


def inbox_col(uid: str):
    return db().collection("users").document(uid).collection("inbox")


def members_col(brand_id: str):
    return brand_doc(brand_id).collection("members")


# ─── Batch helpers ──────────────────────────────────────────

def chunked(items: list[Any], n: int = 400):
    """Yield items in chunks for Firestore batched writes (max 500/batch)."""
    for i in range(0, len(items), n):
        yield items[i : i + n]


def batch_set(col, docs: list[tuple[str, dict]], merge: bool = True):
    """Batch write (doc_id, data) pairs."""
    fs = db()
    for chunk in chunked(docs):
        b = fs.batch()
        for doc_id, data in chunk:
            b.set(col.document(doc_id), data, merge=merge)
        b.commit()


def composite_id(*parts: str) -> str:
    """Build a deterministic doc id from string parts (lowercased, _ joined)."""
    return "_".join(p.lower().replace("/", "_") for p in parts if p)
