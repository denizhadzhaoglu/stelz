"""Compute 5-layer SRS (Spot Resonance Score).

Pure compute over Firestore data. No external APIs.

Layers (weights in 'hot' mode after subculture drop in productization cleanup):
  Graph 35%, Hashtag 25%, Comment 20%, Geo 10%, Visual 10%
  (Subculture layer dropped — no creator_subcultures seed data; its 15%
  weight was redistributed: +5 graph, +5 hashtag, +5 comment.)

Bootstrap modes (auto-selected from #tier-1 verified hits):
  cold (<10):  Hashtag 45, Geo 30, Comment 20, Graph 5, Visual 0
  warm (10-50): Hashtag 30, Graph 25, Comment 20, Geo 15, Visual 10
  hot (>=50):   Graph 35, Hashtag 25, Comment 20, Geo 10, Visual 10

v2 (SRS_VERSION = 2): the Hashtag layer now EXCLUDES brand-specific tags. It
previously scored a creator on how well their hashtags matched the brand's —
i.e. on how much they already tag the brand — which is the inverse of what this
tool sells, since anyone can follow a hashtag for free. It now measures
lifestyle/topical affinity instead. If that leaves no signal at all, the layer's
weight is redistributed rather than scored as zero (see redistribute_weight).

NOTE this score is currently DISPLAY-ONLY: scan_creators selects creators by
nextScanAt + tier, never by srs, so nothing downstream acts on these numbers.
"""
from __future__ import annotations
import logging
import math
from collections import defaultdict, Counter
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from lib import fs, identity

log = logging.getLogger(__name__)

# Bump whenever the scoring changes in a way that makes old and new scores
# incomparable. v2: brand-specific hashtags excluded from the hashtag layer —
# see the long comment in run(). Persisted on every resonance doc.
SRS_VERSION = 2


def redistribute_weight(weights: dict[str, int], dead_layer: str) -> dict[str, int]:
    """Zero out a layer that has no signal and spread its weight over the rest.

    Scoring a dead layer as 0.0 for every candidate is NOT the same as removing
    it: it silently shrinks every score toward zero and lets the remaining
    layers dominate by accident rather than by design. Weights must still sum
    to 100 afterwards, or SRS values stop being comparable across brands and
    across bootstrap modes.

    Proportional split, with the rounding remainder going to the largest
    surviving layer so the total lands exactly on the original sum.
    """
    w = dict(weights)
    spare = w.get(dead_layer, 0)
    if not spare:
        return w
    target_total = sum(w.values())
    w[dead_layer] = 0
    others = {k: v for k, v in w.items() if k != dead_layer and v > 0}
    if not others:
        return w  # nothing left to carry the weight; caller gets an all-zero score
    total_other = sum(others.values())
    for k, v in others.items():
        w[k] = v + int(spare * v / total_other)
    drift = target_total - sum(w.values())
    if drift:
        w[max(others, key=lambda k: w[k])] += drift
    return w


def run(brand_id: str) -> dict[str, Any]:
    brand = fs.brand_doc(brand_id).get()
    if not brand.exists:
        return {"status": "skip", "reason": "no_brand"}

    # 1) Bootstrap mode by counting tier-1 verified hits (single aggregation, ~1 read)
    tier1_q = (
        fs.detections_col(brand_id)
        .where("detected", "==", True)
        .where("verified", "==", True)
        .count()
        .get()
    )
    n_tier1 = tier1_q[0][0].value if tier1_q else 0
    # Weights sum to 100. Subculture removed (no seed data); its share split
    # across graph + hashtag + comment.
    if n_tier1 < 10:
        mode = "cold"
        w = {"graph": 5, "hashtag": 45, "comment": 20, "geo": 30, "visual": 0}
    elif n_tier1 < 50:
        mode = "warm"
        w = {"graph": 25, "hashtag": 30, "comment": 20, "geo": 15, "visual": 10}
    else:
        mode = "hot"
        w = {"graph": 35, "hashtag": 25, "comment": 20, "geo": 10, "visual": 10}

    # 2) Edges → graph in-degree + per-type counts. ONE stream over edges.
    in_deg = defaultdict(float)
    comment_count = defaultdict(int)
    has_edge = set()
    for e in fs.edges_col(brand_id).stream():
        ed = e.to_dict() or {}
        src = ed.get("srcHandle")
        dst = ed.get("dstHandle")
        etype = ed.get("edgeType", "mention")
        weight = float(ed.get("weight") or 1.0)
        type_w = {"mention": 1.0, "tag": 0.9, "comment": 0.7}.get(etype, 0.5)
        if dst:
            in_deg[dst] += weight * type_w
            has_edge.add(dst)
        if etype == "comment" and dst:
            comment_count[dst] += 1
        if src:
            has_edge.add(src)

    # 3) Detections → brand hashtag yield + per-creator hashtag bag (denormalized!).
    # One stream over detections; no per-detection post lookup.
    cand_hashtags: dict[str, Counter] = defaultdict(Counter)
    cand_n_posts: dict[str, int] = defaultdict(int)
    cand_avg_conf: dict[str, list[float]] = defaultdict(list)
    has_hit = set()
    brand_yield_counter: Counter = Counter()
    brand_total_hits = 0

    # BRAND-SPECIFIC TAGS ARE EXCLUDED FROM BOTH VECTORS.
    #
    # brand_vec is built from hashtags on posts that already produced a
    # detection. Discovery is hashtag-seeded, so that corpus is dominated by
    # posts carrying #stelz/#drinkstelz — and the layer then scored a creator on
    # how much they resemble people who ALREADY TAG THE BRAND. At 45% weight in
    # cold-start mode that made the ranking function's heaviest input "how
    # findable is this person without us", which is backwards: anyone can follow
    # a hashtag for free.
    #
    # With brand tags dropped, the layer measures what is actually useful —
    # lifestyle/topical affinity (#vrijmibo, #huisfeest, #studentenleven).
    # brand is a DocumentSnapshot; .get(field) raises KeyError on a missing
    # field, so go through to_dict().
    brand_data = brand.to_dict() or {}
    brand_slug = identity.normalize(brand_data.get("slug") or brand_id)
    brand_aliases = brand_data.get("wordmarkAliases") or []

    def _is_brand_tag(tag: str) -> bool:
        return identity.is_brand_specific_tag(tag, brand_slug, brand_aliases)

    for det in fs.detections_col(brand_id).where("detected", "==", True).stream():
        dd = det.to_dict() or {}
        handle = dd.get("creatorHandle")
        if not handle:
            continue
        has_hit.add(handle)
        cand_n_posts[handle] += 1
        cand_avg_conf[handle].append(float(dd.get("confidence") or 0))
        for h in (dd.get("postHashtags") or []):
            tag = h.lower()
            if _is_brand_tag(tag):
                continue
            cand_hashtags[handle][tag] += 1
            brand_yield_counter[tag] += 1
        brand_total_hits += 1
    brand_vec = {h: c / max(1, brand_total_hits) for h, c in brand_yield_counter.items() if c >= 2}

    # If every detected post carries only brand tags, brand_vec is now empty and
    # _cosine returns 0 for EVERY candidate — silently turning 45% of the
    # cold-start score into dead weight and collapsing all ranking onto
    # geo+comment. Redistribute that weight instead of scoring everyone zero.
    hashtag_layer_live = bool(brand_vec)
    if not hashtag_layer_live and w["hashtag"]:
        spare = w["hashtag"]
        w = redistribute_weight(w, "hashtag")
        log.warning(
            f"[{brand_id}] hashtag layer disabled: every detected post's tags are "
            f"brand-specific, so there is no lifestyle signal to compare. "
            f"Weight {spare} redistributed -> {w}"
        )

    # 4) Candidate set = anyone with a hit OR an edge. Skip dead creators.
    candidate_handles = has_edge | has_hit

    if not candidate_handles:
        return {"scored": 0, "mode": mode, "tier1_hits": n_tier1, "reason": "no_candidates"}

    # 5) Pull metadata only for candidates (NOT all creators). Single batch via composite ID.
    # Creators in Firestore have ID = composite(platform, handle). We don't know the platform
    # for each candidate handle a priori, so we use a where-in query in chunks of 30.
    candidate_meta: dict[str, dict] = {}
    handles_list = list(candidate_handles)
    for i in range(0, len(handles_list), 30):
        chunk = handles_list[i:i + 30]
        q = fs.creators_col(brand_id).where("handle", "in", chunk)
        for c in q.stream():
            cd = c.to_dict() or {}
            candidate_meta[(cd.get("handle") or "").lower()] = cd

    # 6) Score each candidate (pure compute)
    out = []
    for handle in candidate_handles:
        cd = candidate_meta.get(handle, {})
        platform = cd.get("platform", "instagram")

        graph = min(100.0, in_deg.get(handle, 0) * 8.0)

        if cand_n_posts[handle] > 0 and brand_vec:
            tag_vec = {h: c / cand_n_posts[handle] for h, c in cand_hashtags[handle].items()}
            hashtag = _cosine(brand_vec, tag_vec) * 100
        else:
            hashtag = 0.0

        comment = min(100.0, comment_count.get(handle, 0) * 10.0)

        ai = cd.get("aiSummary") or {}
        geo = 80.0 if ai.get("is_dutch_speaker") else 30.0
        visual = float(cd.get("visualScore") or 0)

        srs = (
            graph * w["graph"] + hashtag * w["hashtag"]
            + comment * w["comment"] + geo * w["geo"] + visual * w["visual"]
        ) / 100.0

        out.append({
            "handle": handle,
            "platform": platform,
            "srs": round(srs, 2),
            "graph": round(graph, 1),
            "hashtag": round(hashtag, 1),
            "comment": round(comment, 1),
            "geo": round(geo, 1),
            "visual": round(visual, 1),
            "bootstrapMode": mode,
            # v2 excludes brand-specific tags from the hashtag layer, so scores
            # are NOT comparable with v1 — and the client has already seen v1
            # numbers. Without this field a support conversation about "why did
            # this creator drop" is unanswerable.
            "srsVersion": SRS_VERSION,
            "hashtagLayerLive": hashtag_layer_live,
            "weights": dict(w),
            "tier": cd.get("tier"),
            "fullName": cd.get("fullName"),
            "followerCount": cd.get("followerCount"),
            "category": cd.get("category"),
            "relevanceScore": cd.get("relevanceScore"),
            "clearVisibilityHits": cand_n_posts[handle],
            "latestDetectionAt": cd.get("lastDetectionAt"),
            "computedAt": SERVER_TIMESTAMP,
        })

    # 7) Batched write. Firestore batch max = 500 ops.
    col = fs.resonance_col(brand_id)
    for chunk in fs.chunked(out, 400):
        b = fs.db().batch()
        for s in chunk:
            doc_id = fs.composite_id(s["platform"], s["handle"])
            b.set(col.document(doc_id), s, merge=True)
        b.commit()

    fs.scan_runs_col(brand_id).add({
        "type": "compute_resonance",
        "startedAt": SERVER_TIMESTAMP,
        "finishedAt": SERVER_TIMESTAMP,
        "stats": {"scored": len(out), "mode": mode, "tier1Hits": n_tier1, "edgesRead": sum(1 for _ in [0])},
        "status": "ok",
    })
    return {"scored": len(out), "mode": mode, "tier1_hits": n_tier1}


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0
