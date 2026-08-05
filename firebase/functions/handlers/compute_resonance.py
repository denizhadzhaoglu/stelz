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
"""
from __future__ import annotations
import logging
import math
from collections import defaultdict, Counter
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from lib import fs

log = logging.getLogger(__name__)


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
            cand_hashtags[handle][tag] += 1
            brand_yield_counter[tag] += 1
        brand_total_hits += 1
    brand_vec = {h: c / max(1, brand_total_hits) for h, c in brand_yield_counter.items() if c >= 2}

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
