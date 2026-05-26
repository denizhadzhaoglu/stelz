"""Brand-specific reference image loader.

Loads reference images for a given brand from Supabase Storage, with a
local-cache fallback. Used by all detection scripts so they no longer
hardcode STELZ paths.

Storage layout per brand:
    references/<brand_slug>/         -- product packshots + lifestyle (auth-managed)
    references/<brand_slug>/training/ -- few-shot examples from moderator decisions

The local cache lives in /tmp/spotthebrand/refs/<brand_slug>/ so multiple
invocations within a Railway run don't re-download.
"""

import io
import os
from pathlib import Path

import requests
from PIL import Image
from supabase import create_client

REF_BUCKET = "brand-watch-thumbnails"
LOCAL_CACHE_BASE = Path("/tmp/spotthebrand/refs")
DEFAULT_MAX_DIM = 512


def _resize(b: bytes, max_dim: int) -> bytes:
    img = Image.open(io.BytesIO(b))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dim:
        s = max_dim / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def load_brand_refs(brand_slug: str, max_dim: int = DEFAULT_MAX_DIM, include_training: bool = True) -> list[bytes]:
    """Return a list of resized JPEG byte strings, one per reference image.

    The brand_slug determines the Storage folder. Anonymous public bucket
    URLs are used so the script does not need extra auth.
    """
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    cache_dir = LOCAL_CACHE_BASE / brand_slug
    cache_dir.mkdir(parents=True, exist_ok=True)

    folders = [f"references/{brand_slug}"]
    if include_training:
        folders.append(f"references/{brand_slug}/training")

    out: list[bytes] = []
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    for folder in folders:
        try:
            files = sb.storage.from_(REF_BUCKET).list(folder, {"limit": 100})
        except Exception as e:
            print(f"  [brand_refs] list {folder} err: {e}")
            continue
        for f in files or []:
            name = f.get("name")
            if not name or name.startswith("."):
                continue
            # Skip subfolder entries (Supabase returns folders as items too).
            # Subfolders have no metadata.size; real files do.
            meta = f.get("metadata") or {}
            if not meta.get("size") and not any(name.lower().endswith(ext) for ext in image_exts):
                # Either a subfolder pseudo-entry or a non-image file (manifest.json etc.)
                continue
            # Even if size is set, ignore non-image files (manifest.json, .DS_Store).
            if not any(name.lower().endswith(ext) for ext in image_exts):
                continue
            local = cache_dir / name
            if local.exists():
                data = local.read_bytes()
            else:
                url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/{REF_BUCKET}/{folder}/{name}"
                try:
                    r = requests.get(url, timeout=15)
                    r.raise_for_status()
                    data = _resize(r.content, max_dim)
                    local.write_bytes(data)
                except Exception as e:
                    print(f"  [brand_refs] fetch {name} err: {e}")
                    continue
            out.append(data)
    return out


def has_brand_refs(brand_slug: str) -> bool:
    """Quick check: does this brand have at least one reference image?"""
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    try:
        files = sb.storage.from_(REF_BUCKET).list(f"references/{brand_slug}", {"limit": 1})
        return any(f.get("name") and not f["name"].startswith(".") for f in (files or []))
    except Exception:
        return False
