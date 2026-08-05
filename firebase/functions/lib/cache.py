"""Image hash cache: avoids re-running Gemini on repost/dup images."""
from __future__ import annotations
import hashlib
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from .fs import image_hash_cache_col


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_cached_detection(brand_id: str, image_hash: str, model: str, prompt_version: int = 6) -> dict[str, Any] | None:
    doc = image_hash_cache_col(brand_id).document(image_hash).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    if data.get("model") != model or data.get("promptVersion") != prompt_version:
        return None
    return data.get("result")


def save_cached_detection(brand_id: str, image_hash: str, model: str, result: dict, prompt_version: int = 6) -> None:
    image_hash_cache_col(brand_id).document(image_hash).set({
        "model": model,
        "promptVersion": prompt_version,
        "result": result,
        "lastSeen": SERVER_TIMESTAMP,
    }, merge=True)
