#!/usr/bin/env python3
"""53_compute_resonance.py — Compute STELZ Resonance Score (SRS) per candidate.

Five layers (visual layer in 55_score_visual.py):

  SRS = 0.30·GraphScore + 0.20·HashtagFingerprint + 0.15·SubcultureFit
      + 0.15·CommentEngagement + 0.10·GeoLangFit

Bootstrap mode shifts weights for brands with few hits:
  - cold (<10 confirmed hits):  0·Graph + 0.55·Hashtag + 0.25·GeoLang + 0.20·Subculture
  - warm (10-100 hits):         0.20·Graph + 0.30·Hashtag + 0.20·Subculture + 0.10·Comment + 0.10·GeoLang + 0.10·Visual
  - hot  (100+ hits, STELZ):    full weights

Writes to resonance_scores table.
Reads from: creator_edges, v_brand_hashtag_yield, creator_subcultures, creators.

Usage:
    python3 tools/stelz_brand_watch/53_compute_resonance.py
    python3 tools/stelz_brand_watch/53_compute_resonance.py --brand stelz
    python3 tools/stelz_brand_watch/53_compute_resonance.py --top 50 --dry-run
"""

import argparse
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


# ─── Weight presets ────────────────────────────────────────
WEIGHTS = {
    "hot":  {"graph": 0.30, "hashtag": 0.20, "subculture": 0.15, "comment": 0.15, "geo": 0.10, "visual": 0.10},
    "warm": {"graph": 0.20, "hashtag": 0.30, "subculture": 0.20, "comment": 0.10, "geo": 0.10, "visual": 0.10},
    "cold": {"graph": 0.00, "hashtag": 0.55, "subculture": 0.20, "comment": 0.00, "geo": 0.25, "visual": 0.00},
}


def determine_bootstrap_mode(hit_count: int) -> str:
    if hit_count >= 100: return "hot"
    if hit_count >= 10:  return "warm"
    return "cold"


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


def fetch_seeds(sb, brand_id):
    """Seed = creators with at least 2 confirmed visual hits (clear visibility)."""
    # Use v_creator_stats for this
    r = (sb.table("v_creator_stats")
         .select("creator_id, handle, platform, tier, clear_visibility_hits")
         .eq("brand_id", brand_id)
         .gte("clear_visibility_hits", 2)
         .execute()).data or []
    return r


def fetch_all_edges(sb, brand_id):
    """Pull all creator_edges for the brand, paginated."""
    all_rows, offset, page = [], 0, 1000
    while True:
        r = (sb.table("creator_edges")
             .select("src_creator_id, dst_handle, dst_platform, edge_type, weight")
             .eq("brand_id", brand_id)
             .range(offset, offset + page - 1)
             .execute()).data or []
        if not r: break
        all_rows.extend(r)
        if len(r) < page: break
        offset += page
    return all_rows


def compute_graph_score(edges, seed_ids, max_per_seed_pct=0.15):
    """GraphScore per (dst_handle, dst_platform).

    Edge type weights:
      mention = 1.0
      tag     = 1.2 (stronger: explicit tag in post)
      comment = 0.7
      subculture = 0.3 (light proximity)

    Cap any single seed's contribution at max_per_seed_pct of total to
    prevent influencer-clique drift.
    """
    type_w = {"mention": 1.0, "tag": 1.2, "comment": 0.7, "subculture": 0.3}
    # First aggregate by (dst, src) so we know one src's contribution
    by_dst_src = defaultdict(lambda: defaultdict(float))  # dst_key -> src_id -> contribution
    for e in edges:
        if e["src_creator_id"] not in seed_ids:
            continue
        dst_key = (e["dst_handle"], e["dst_platform"])
        weight = float(e.get("weight") or 1)
        tw = type_w.get(e["edge_type"], 0)
        by_dst_src[dst_key][e["src_creator_id"]] += weight * tw

    raw = {}
    for dst_key, src_contribs in by_dst_src.items():
        if not src_contribs:
            continue
        total = sum(src_contribs.values())
        # apply cap
        cap = max_per_seed_pct * total if len(src_contribs) > 1 else total
        capped_total = sum(min(c, cap) for c in src_contribs.values())
        # also bump by sqrt(n_distinct_sources) — multi-source signal stronger than concentrated
        n_sources = len(src_contribs)
        raw[dst_key] = capped_total * math.sqrt(n_sources)

    # Normalize to 0-100: log scale + max-norm
    if not raw:
        return {}
    max_raw = max(raw.values())
    scaled = {k: 100 * math.log1p(v) / math.log1p(max_raw) for k, v in raw.items()}
    return scaled


def fetch_hashtag_yield(sb, brand_id):
    """Pull v_brand_hashtag_yield as {hashtag: yield}."""
    r = (sb.table("v_brand_hashtag_yield")
         .select("hashtag, yield, total_count")
         .eq("brand_id", brand_id)
         .execute()).data or []
    return {row["hashtag"]: float(row["yield"]) for row in r}


def fetch_candidate_hashtags(sb, brand_id):
    """For every (handle, platform) (= candidate or existing creator),
    return their hashtag distribution over content_items in window.

    Returns {(handle, platform): {hashtag: count}}.
    """
    # Pull creators with their content_items' hashtags
    creators = sb.table("creators").select("id, handle, platform").eq("brand_id", brand_id).execute().data or []
    creator_meta = {c["id"]: (c["handle"].lower(), c["platform"]) for c in creators}

    out = defaultdict(lambda: defaultdict(int))
    creator_ids = list(creator_meta.keys())
    for chunk in chunked(creator_ids, 200):
        items = (sb.table("content_items")
                 .select("creator_id, hashtags")
                 .eq("brand_id", brand_id)
                 .in_("creator_id", chunk)
                 .execute()).data or []
        for it in items:
            key = creator_meta.get(it["creator_id"])
            if not key: continue
            for h in (it.get("hashtags") or []):
                if not h: continue
                out[key][h.lower()] += 1
    return out


def compute_hashtag_fingerprint(candidate_hashtags, brand_yield):
    """For each candidate, compute cosine-ish similarity between their hashtag
    distribution and the brand's yield vector.

    score = sum(candidate_count[h] * brand_yield[h] * idf[h])
    """
    # IDF: how many candidates use each hashtag? Rare = high IDF.
    df = defaultdict(int)
    for cand_hashtags in candidate_hashtags.values():
        for h in cand_hashtags:
            df[h] += 1
    n_candidates = max(len(candidate_hashtags), 1)
    idf = {h: math.log(1 + n_candidates / max(c, 1)) for h, c in df.items()}

    raw = {}
    for key, hashtags in candidate_hashtags.items():
        total_count = sum(hashtags.values())
        if not total_count:
            continue
        score = 0.0
        for h, c in hashtags.items():
            if h not in brand_yield:
                continue
            # Weight = (their_normalized_use) * (brand_yield) * IDF
            score += (c / total_count) * brand_yield[h] * idf.get(h, 1)
        raw[key] = score

    if not raw:
        return {}
    max_raw = max(raw.values()) or 1
    return {k: 100 * v / max_raw for k, v in raw.items()}


def fetch_subculture_fit(sb, brand_id, tier_set=("tier_1", "tier_2")):
    """For each subculture, compute %tier_1+tier_2 of its members.
    Then for each creator in that subculture, score = max(% across their subcultures) * 100.
    """
    # subculture_id -> [creator_id]
    sc_members = defaultdict(list)
    # Pull creator_subcultures + creator tier
    creators = sb.table("creators").select("id, handle, platform, tier").eq("brand_id", brand_id).execute().data or []
    creator_meta = {c["id"]: c for c in creators}

    cs_rows = []
    for chunk in chunked(list(creator_meta.keys()), 200):
        r = sb.table("creator_subcultures").select("creator_id, subculture_id").in_("creator_id", chunk).execute().data or []
        cs_rows.extend(r)
    if not cs_rows:
        return {}
    for cs in cs_rows:
        sc_members[cs["subculture_id"]].append(cs["creator_id"])

    # Score per subculture
    sc_score = {}
    for sc_id, members in sc_members.items():
        if not members: continue
        n_tier = sum(1 for m in members if creator_meta.get(m, {}).get("tier") in tier_set)
        sc_score[sc_id] = n_tier / len(members)

    # Each creator gets max subculture score
    out = {}
    member_subcultures = defaultdict(list)
    for cs in cs_rows:
        member_subcultures[cs["creator_id"]].append(cs["subculture_id"])
    for cid, sc_ids in member_subcultures.items():
        meta = creator_meta.get(cid)
        if not meta: continue
        key = (meta["handle"].lower(), meta["platform"])
        score = max((sc_score.get(s, 0) for s in sc_ids), default=0)
        out[key] = score * 100
    return out


def compute_comment_engagement(edges, seed_ids):
    """For each dst_handle, count comment-type edges from seed sources."""
    counts = defaultdict(set)
    for e in edges:
        if e["edge_type"] != "comment":
            continue
        if e["src_creator_id"] not in seed_ids:
            continue
        key = (e["dst_handle"], e["dst_platform"])
        counts[key].add(e["src_creator_id"])
    raw = {k: len(v) for k, v in counts.items()}
    if not raw:
        return {}
    max_raw = max(raw.values()) or 1
    return {k: 100 * math.log1p(v) / math.log1p(max_raw) for k, v in raw.items()}


def fetch_geo_lang_fit(sb, brand_id):
    """Use ai_summary.is_dutch_speaker (set by 21_ai_score_creators) if available.
    Score 100 if NL, 50 if unknown, 30 if explicit non-NL."""
    creators = sb.table("creators").select("handle, platform, ai_summary").eq("brand_id", brand_id).execute().data or []
    out = {}
    for c in creators:
        key = (c["handle"].lower(), c["platform"])
        ai = c.get("ai_summary") or {}
        if isinstance(ai, dict):
            nl = ai.get("is_dutch_speaker")
            if nl is True: out[key] = 100
            elif nl is False: out[key] = 30
            else: out[key] = 50
        else:
            out[key] = 50
    return out


def compose_srs(graph, hashtag, subculture, comment, geo, weights, visual=None):
    """Combine layers into composite SRS."""
    all_keys = set(graph) | set(hashtag) | set(subculture) | set(comment) | set(geo)
    if visual: all_keys |= set(visual)
    out = {}
    for key in all_keys:
        layers = {
            "graph": graph.get(key, 0),
            "hashtag": hashtag.get(key, 0),
            "subculture": subculture.get(key, 0),
            "comment": comment.get(key, 0),
            "geo": geo.get(key, 0),
            "visual": (visual or {}).get(key, 0),
        }
        srs = sum(layers[k] * weights[k] for k in weights)
        srs = max(0, min(100, srs))
        out[key] = (srs, layers)
    return out


def process_brand(sb, brand_id, brand_slug, top_print, dry_run):
    print(f"\n[{brand_slug}] computing SRS", file=sys.stderr)
    t0 = time.time()

    seeds = fetch_seeds(sb, brand_id)
    seed_ids = {s["creator_id"] for s in seeds}
    hit_count = sum(s.get("clear_visibility_hits", 0) for s in seeds)
    mode = determine_bootstrap_mode(hit_count)
    weights = WEIGHTS[mode]
    print(f"  seeds: {len(seeds)} creators with ≥2 visibility hits", file=sys.stderr)
    print(f"  bootstrap mode: {mode} (total hits across seeds: {hit_count})", file=sys.stderr)
    print(f"  weights: {weights}", file=sys.stderr)

    edges = fetch_all_edges(sb, brand_id)
    print(f"  edges loaded: {len(edges)}", file=sys.stderr)

    graph_scores = compute_graph_score(edges, seed_ids)
    print(f"  graph candidates: {len(graph_scores)} ({time.time()-t0:.1f}s)", file=sys.stderr)

    cand_hashtags = fetch_candidate_hashtags(sb, brand_id)
    brand_yield = fetch_hashtag_yield(sb, brand_id)
    print(f"  brand hashtag-yield vector: {len(brand_yield)} terms", file=sys.stderr)
    hashtag_scores = compute_hashtag_fingerprint(cand_hashtags, brand_yield)
    print(f"  hashtag candidates: {len(hashtag_scores)} ({time.time()-t0:.1f}s)", file=sys.stderr)

    subc_scores = fetch_subculture_fit(sb, brand_id)
    print(f"  subculture candidates: {len(subc_scores)} ({time.time()-t0:.1f}s)", file=sys.stderr)

    comment_scores = compute_comment_engagement(edges, seed_ids)
    print(f"  comment candidates: {len(comment_scores)}", file=sys.stderr)

    geo_scores = fetch_geo_lang_fit(sb, brand_id)
    print(f"  geo candidates: {len(geo_scores)}", file=sys.stderr)

    srs_map = compose_srs(graph_scores, hashtag_scores, subc_scores, comment_scores, geo_scores, weights)
    print(f"  total scored: {len(srs_map)} ({time.time()-t0:.1f}s)", file=sys.stderr)

    # Top N
    top = sorted(srs_map.items(), key=lambda x: -x[1][0])[:top_print]
    print(f"\n  TOP {top_print}:", file=sys.stderr)
    print(f"  {'handle':<32} {'platform':<10} {'SRS':>6}  {'graph':>6} {'hash':>6} {'sub':>6} {'cmt':>6} {'geo':>5}", file=sys.stderr)
    for (handle, platform), (srs, layers) in top:
        print(f"  {handle:<32} {platform:<10} {srs:>6.1f}  "
              f"{layers['graph']:>6.1f} {layers['hashtag']:>6.1f} {layers['subculture']:>6.1f} "
              f"{layers['comment']:>6.1f} {layers['geo']:>5.1f}", file=sys.stderr)

    if dry_run:
        return len(srs_map)

    # Write to resonance_scores
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for (handle, platform), (srs, layers) in srs_map.items():
        rows.append({
            "brand_id": brand_id,
            "creator_handle": handle,
            "platform": platform,
            "srs": round(srs, 2),
            "graph": round(layers["graph"], 2),
            "hashtag": round(layers["hashtag"], 2),
            "subculture": round(layers["subculture"], 2),
            "comment": round(layers["comment"], 2),
            "geo": round(layers["geo"], 2),
            "visual": None,
            "bootstrap_mode": mode,
            "computed_at": now,
        })
    for batch in chunked(rows, 500):
        sb.table("resonance_scores").upsert(
            batch, on_conflict="brand_id,platform,creator_handle"
        ).execute()
    print(f"\n  upserted {len(rows)} resonance_scores rows", file=sys.stderr)
    return len(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--top", type=int, default=20, help="Print top N to stderr")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = sb.table("brands").select("id, slug").execute().data or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    if not brands:
        print("No brands selected", file=sys.stderr); return

    total = 0
    t0 = time.time()
    for b in brands:
        total += process_brand(sb, b["id"], b["slug"], args.top, args.dry_run)
    print(f"\n=== RESONANCE COMPUTE COMPLETE in {time.time()-t0:.1f}s ===", file=sys.stderr)
    print(f"total candidates scored: {total}", file=sys.stderr)


if __name__ == "__main__":
    main()
