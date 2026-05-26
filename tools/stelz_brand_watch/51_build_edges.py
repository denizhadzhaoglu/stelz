#!/usr/bin/env python3
"""51_build_edges.py — Hydrate creator_edges from existing data.

Builds three of the four edge types in creator_edges (the fourth,
'comment', is filled by 52_mine_comments.py):

  - mention    : src_creator's posts @-mention dst_handle
  - tag        : src_creator tagged dst in a post (Instagram tagged_users)
  - subculture : src and dst are both in the same subculture (light, weight 0.3)

Idempotent. Upserts with on_conflict on the primary key, bumping
last_seen_at on touch. Edges that aren't touched for 30 days get
pruned by prune_stale_edges().

Used by: 53_compute_resonance.py (GraphScore layer).

Usage:
    python3 tools/stelz_brand_watch/51_build_edges.py
    python3 tools/stelz_brand_watch/51_build_edges.py --brand stelz
    python3 tools/stelz_brand_watch/51_build_edges.py --skip-subculture --skip-tag
    python3 tools/stelz_brand_watch/51_build_edges.py --window-days 90
"""

import argparse
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# Self / brand-owned handles to never store as edges.
BRAND_OWNED = {"drinkstelz", "stelz", "stelz_official", "stelz.official", "stelz_int"}

HANDLE_OK = re.compile(r"^[a-zA-Z0-9_.]{2,30}$")

# Reject anything that looks like a domain — Apify mention-extraction
# sometimes picks up email domains (gmail.com, outlook.com) and parses
# trailing "stuff.nl" / "stuff.com" as if they were @-mentions.
DOMAIN_LIKE = re.compile(r"\.(com|nl|org|net|io|co|de|be|fr|uk|info|biz|app|tv|me)$")
MULTI_DOT   = re.compile(r"\.[a-z]{2,}\.")  # foo.bar.com style


def normalize_handle(h: str) -> str:
    return (h or "").strip().lstrip("@").lower()


def is_real_handle(h: str) -> bool:
    if not h or not HANDLE_OK.match(h): return False
    if h in BRAND_OWNED: return False
    if DOMAIN_LIKE.search(h): return False
    if MULTI_DOT.search(h): return False
    # Pure numeric tokens, single-character handles, etc.
    if h.isdigit(): return False
    return True


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


def dedupe_edge_rows(rows):
    """Keep one row per (src, dst, platform, type). If duplicate, sum weights."""
    deduped = {}
    for r in rows:
        k = (r["brand_id"], r["src_creator_id"], r["dst_handle"], r["dst_platform"], r["edge_type"])
        if k in deduped:
            # keep larger weight
            if r.get("weight", 0) > deduped[k].get("weight", 0):
                deduped[k] = r
        else:
            deduped[k] = r
    return list(deduped.values())


def fetch_content_items_for_brand(sb, brand_id, window_days):
    """Pull content_items with mentions/tagged_users for the window."""
    cutoff = (datetime.now(timezone.utc) - __import__("datetime").timedelta(days=window_days)).isoformat()
    all_items, offset, page = [], 0, 1000
    while True:
        r = (sb.table("content_items")
             .select("id, creator_id, platform, mentions, raw, posted_at, scraped_at")
             .eq("brand_id", brand_id)
             .gte("scraped_at", cutoff)
             .range(offset, offset + page - 1)
             .execute()).data or []
        if not r:
            break
        all_items.extend(r)
        if len(r) < page:
            break
        offset += page
    return all_items


def build_mention_edges(sb, brand_id, items, dry_run=False):
    """src_creator → dst_handle (mention type). Weight = co-occurrence count."""
    cooc = defaultdict(lambda: Counter())  # creator_id -> Counter of (platform, handle)
    for it in items:
        cid = it.get("creator_id")
        if not cid: continue
        platform = it.get("platform") or "instagram"
        for m in (it.get("mentions") or []):
            h = normalize_handle(m)
            if not is_real_handle(h): continue
            cooc[cid][(platform, h)] += 1
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for cid, counter in cooc.items():
        for (platform, dst), w in counter.items():
            rows.append({
                "brand_id": brand_id,
                "src_creator_id": cid,
                "dst_handle": dst,
                "dst_platform": platform,
                "edge_type": "mention",
                "weight": int(w),
                "last_seen_at": now,
            })
    print(f"  mention edges: {len(rows)} (from {len(items)} items)", file=sys.stderr)
    if not dry_run and rows:
        deduped = dedupe_edge_rows(rows)
        for batch in chunked(deduped, 500):
            sb.table("creator_edges").upsert(
                batch, on_conflict="brand_id,src_creator_id,dst_handle,dst_platform,edge_type"
            ).execute()
    return len(rows)


def build_tag_edges(sb, brand_id, items, dry_run=False):
    """src_creator → dst_handle (tag type). From Instagram tagged_users in raw payload."""
    cooc = defaultdict(lambda: Counter())
    for it in items:
        cid = it.get("creator_id")
        if not cid: continue
        platform = it.get("platform") or "instagram"
        raw = it.get("raw") or {}
        if not isinstance(raw, dict): continue
        tagged = raw.get("taggedUsers") or raw.get("tagged_users") or []
        if not isinstance(tagged, list): continue
        for t in tagged:
            if isinstance(t, dict):
                h = normalize_handle(t.get("username") or t.get("user", {}).get("username") or "")
            else:
                h = normalize_handle(str(t))
            if not is_real_handle(h): continue
            cooc[cid][(platform, h)] += 1
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for cid, counter in cooc.items():
        for (platform, dst), w in counter.items():
            rows.append({
                "brand_id": brand_id,
                "src_creator_id": cid,
                "dst_handle": dst,
                "dst_platform": platform,
                "edge_type": "tag",
                "weight": int(w),
                "last_seen_at": now,
            })
    print(f"  tag edges: {len(rows)}", file=sys.stderr)
    if not dry_run and rows:
        deduped = dedupe_edge_rows(rows)
        for batch in chunked(deduped, 500):
            sb.table("creator_edges").upsert(
                batch, on_conflict="brand_id,src_creator_id,dst_handle,dst_platform,edge_type"
            ).execute()
    return len(rows)


def build_subculture_edges(sb, brand_id, dry_run=False):
    """For each subculture, link every member-pair with edge_type='subculture' weight=0.3.
    Bidirectional: a→b and b→a both inserted so GraphScore works in any direction."""
    # Pull all creator_subcultures for this brand's creators
    creators = sb.table("creators").select("id, handle, platform").eq("brand_id", brand_id).execute().data or []
    creator_meta = {c["id"]: c for c in creators}
    creator_ids = list(creator_meta.keys())
    if not creator_ids:
        return 0
    cs_rows = []
    for batch in chunked(creator_ids, 200):
        r = sb.table("creator_subcultures").select("creator_id, subculture_id").in_("creator_id", batch).execute().data or []
        cs_rows.extend(r)
    if not cs_rows:
        return 0
    sc_members = defaultdict(list)  # subculture_id -> [creator_id]
    for cs in cs_rows:
        sc_members[cs["subculture_id"]].append(cs["creator_id"])
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for sc_id, member_ids in sc_members.items():
        if len(member_ids) < 2:
            continue
        for src in member_ids:
            src_meta = creator_meta.get(src)
            if not src_meta: continue
            for dst in member_ids:
                if dst == src: continue
                dst_meta = creator_meta.get(dst)
                if not dst_meta: continue
                rows.append({
                    "brand_id": brand_id,
                    "src_creator_id": src,
                    "dst_handle": normalize_handle(dst_meta["handle"]),
                    "dst_platform": dst_meta["platform"],
                    "edge_type": "subculture",
                    "weight": 0.3,
                    "last_seen_at": now,
                })
    print(f"  subculture edges: {len(rows)} (from {len(sc_members)} subcultures)", file=sys.stderr)
    if not dry_run and rows:
        deduped = dedupe_edge_rows(rows)
        for batch in chunked(deduped, 500):
            sb.table("creator_edges").upsert(
                batch, on_conflict="brand_id,src_creator_id,dst_handle,dst_platform,edge_type"
            ).execute()
    return len(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--window-days", type=int, default=180,
                   help="Only consider content_items scraped within this many days")
    p.add_argument("--skip-mention", action="store_true")
    p.add_argument("--skip-tag", action="store_true")
    p.add_argument("--skip-subculture", action="store_true")
    p.add_argument("--prune", action="store_true",
                   help="Also call prune_stale_edges(30) after the build")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = sb.table("brands").select("id, slug").execute().data or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]
    if not brands:
        print("No brands selected", file=sys.stderr); return

    grand_m, grand_t, grand_s = 0, 0, 0
    t0 = time.time()
    for b in brands:
        bid, slug = b["id"], b["slug"]
        print(f"\n[{slug}] {bid}", file=sys.stderr)
        items = fetch_content_items_for_brand(sb, bid, args.window_days)
        print(f"  content_items in window: {len(items)}", file=sys.stderr)
        if not args.skip_mention:
            grand_m += build_mention_edges(sb, bid, items, dry_run=args.dry_run)
        if not args.skip_tag:
            grand_t += build_tag_edges(sb, bid, items, dry_run=args.dry_run)
        if not args.skip_subculture:
            grand_s += build_subculture_edges(sb, bid, dry_run=args.dry_run)

    if args.prune and not args.dry_run:
        r = sb.rpc("prune_stale_edges", {"p_age_days": 30}).execute()
        pruned = r.data if isinstance(r.data, int) else (r.data or 0)
        print(f"\npruned stale edges (>30d): {pruned}", file=sys.stderr)

    print(f"\n=== EDGE BUILD COMPLETE in {time.time()-t0:.1f}s ===", file=sys.stderr)
    print(f"mention: {grand_m}, tag: {grand_t}, subculture: {grand_s}", file=sys.stderr)


if __name__ == "__main__":
    main()
