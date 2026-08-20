"""Seed the brand's subcultures and file each creator into the ones they fit.

This is the data that was missing. compute_resonance has carried a subculture
layer since the beginning, disabled with the note "no creator_subcultures seed
data" — because the script that produced it (tools/stelz_brand_watch/
30_seed_subcultures.py) wrote to the Supabase database that was removed in
2026-06. Nothing here is new logic; it is that script's classifier moved onto
Firestore, with the matching itself extracted into lib/subcultures.py.

Writes:
  /brands/{id}/subcultures/{slug}            the scene definitions
  /brands/{id}/creatorSubcultures/{handle}   which scenes each creator is in

Idempotent, and cheap enough to re-run after every scan: one stream over
detections, no external calls, no Gemini.

WHY HASHTAGS FROM DETECTIONS, NOT FROM POSTS
--------------------------------------------
detect_image denormalizes postHashtags onto every detection doc, so a creator's
tag history is one stream over a collection we already read elsewhere. Going via
/posts would mean an N+1 per creator. The cost is that only creators with at
least one HIT get classified — which is exactly the population the dashboard and
SRS care about.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from lib import fs, subcultures

log = logging.getLogger(__name__)

# Ceiling on detections streamed in one run. A brand past this is past the point
# where a full reclassification belongs in a request handler.
SCAN_CEILING = 20000


def _write_definitions(brand_id: str, specs: list[dict[str, Any]]) -> int:
    col = fs.brand_doc(brand_id).collection("subcultures")
    for spec in specs:
        col.document(spec["slug"]).set({
            "slug": spec["slug"],
            "name": spec["name"],
            "description": spec.get("description"),
            "signatureHashtags": spec.get("signature_hashtags", []),
            "signatureKeywords": spec.get("signature_keywords", []),
            "categoryMatch": spec.get("category_match", []),
            "color": spec.get("color"),
            "emoji": spec.get("emoji"),
            "status": "active",
            "updatedAt": SERVER_TIMESTAMP,
        }, merge=True)
    return len(specs)


def run(brand_id: str) -> dict[str, Any]:
    brand = fs.brand_doc(brand_id).get()
    if not brand.exists:
        return {"status": "skip", "reason": "no_brand"}

    specs = subcultures.STELZ_SUBCULTURES
    n_defs = _write_definitions(brand_id, specs)

    # 1) One stream over detections → per-creator hashtag bag + category.
    tags_by_creator: dict[str, set[str]] = defaultdict(set)
    category_by_creator: dict[str, str | None] = {}
    seen = 0
    for doc in fs.detections_col(brand_id).limit(SCAN_CEILING).stream():
        d = doc.to_dict() or {}
        handle = d.get("creatorHandle")
        if not handle:
            continue
        seen += 1
        for t in (d.get("postHashtags") or []):
            norm = subcultures.normalize_tag(t)
            if norm:
                tags_by_creator[handle].add(norm)
        # Category is denormalized per detection and identical across a
        # creator's rows; first non-null wins.
        if category_by_creator.get(handle) is None:
            category_by_creator[handle] = d.get("creatorCategory")

    # 2) Match each creator, and write one doc per creator.
    links_col = fs.brand_doc(brand_id).collection("creatorSubcultures")
    per_subculture: dict[str, int] = defaultdict(int)
    linked_creators = 0
    unplaced = 0
    for handle, tags in tags_by_creator.items():
        links = subcultures.match_creator(tags, category_by_creator.get(handle), specs)
        if not links:
            unplaced += 1
            # Write the empty result too. Without it, "no scene" and "not yet
            # classified" are indistinguishable downstream, and the dashboard
            # cannot honestly report its own coverage.
            links_col.document(handle).set({
                "handle": handle,
                "links": [],
                "computedAt": SERVER_TIMESTAMP,
            }, merge=True)
            continue
        linked_creators += 1
        for l in links:
            per_subculture[l["slug"]] += 1
        links_col.document(handle).set({
            "handle": handle,
            "links": [
                {
                    "slug": l["slug"],
                    "confidence": l["confidence"],
                    "matched": l["matched"],
                    "byCategory": l["byCategory"],
                }
                for l in links
            ],
            "primary": links[0]["slug"],
            "computedAt": SERVER_TIMESTAMP,
        }, merge=True)

    return {
        "status": "ok",
        "subcultures": n_defs,
        "detections_scanned": seen,
        "creators_seen": len(tags_by_creator),
        "creators_linked": linked_creators,
        "creators_unplaced": unplaced,
        "per_subculture": dict(sorted(per_subculture.items(), key=lambda kv: -kv[1])),
    }
