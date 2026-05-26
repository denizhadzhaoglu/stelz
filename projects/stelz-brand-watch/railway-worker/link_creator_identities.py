#!/usr/bin/env python3
"""Cross-platform identity match: link the same person across IG + TikTok.

Why this exists:
  Same creator often has an IG handle AND a TikTok handle. Right now we
  treat them as two separate creators, which under-counts their real
  reach. Linking them means: tier-1 status on one platform escalates the
  other; combined follower count tells the truer story; partnership
  outreach can be planned across both.

Strategy:
  For each brand, find pairs (one IG, one TikTok) that match on:
    1. handle_normalized (high signal)
    2. full_name (when both populated, mid signal)
    3. follower count order-of-magnitude (low signal)

  Score = sum of signals (1 each). If score >= 2 → link them with
  identity_id (UUID v4). If score == 1 → log as candidate for manual
  review (no auto-link).

  Idempotent: re-running re-checks unlinked pairs and respects existing
  identity_id values.

Usage:
    python3 tools/stelz_brand_watch/45_link_creator_identities.py
    python3 tools/stelz_brand_watch/45_link_creator_identities.py --brand stelz --dry-run
"""

import argparse
import math
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def normalize_handle(h: str) -> str:
    import re
    return re.sub(r"[._\-]", "", (h or "").lower()).strip()


def normalize_name(n: str) -> str:
    import re
    return re.sub(r"\s+", " ", (n or "").lower()).strip()


def order_of_magnitude(n: int | None) -> int | None:
    if not n or n <= 0:
        return None
    return int(math.log10(n))


def process_brand(sb, brand_id: str, brand_slug: str, dry_run: bool) -> dict:
    rows = (sb.table("creators")
            .select("id, handle, platform, full_name, follower_count, identity_id, tier")
            .eq("brand_id", brand_id)
            .is_("archived_at", "null")
            .execute().data) or []

    by_norm: dict = {}
    for r in rows:
        norm = normalize_handle(r["handle"])
        if not norm:
            continue
        by_norm.setdefault(norm, []).append(r)

    new_links = 0
    candidates = 0
    skipped = 0

    for norm, group in by_norm.items():
        # Need at least one IG + one TikTok in the group
        ig = [r for r in group if r["platform"] == "instagram"]
        tt = [r for r in group if r["platform"] == "tiktok"]
        if not ig or not tt:
            continue

        # For now, link only when there's exactly one of each (clearest case).
        # Multi-handle ambiguity can be addressed later.
        if len(ig) != 1 or len(tt) != 1:
            skipped += 1
            continue

        a, b = ig[0], tt[0]
        # If both already linked to same identity, skip.
        if a.get("identity_id") and a["identity_id"] == b.get("identity_id"):
            continue

        # Score signals
        score = 0
        # 1. handle_normalized match (already true since they share `norm`)
        score += 1
        # 2. full_name match
        if a.get("full_name") and b.get("full_name") and \
           normalize_name(a["full_name"]) == normalize_name(b["full_name"]) and \
           normalize_name(a["full_name"]) != "":
            score += 1
        # 3. follower count order of magnitude match (within 1)
        oa = order_of_magnitude(a.get("follower_count"))
        ob = order_of_magnitude(b.get("follower_count"))
        if oa is not None and ob is not None and abs(oa - ob) <= 1:
            score += 1

        # Decide
        if score >= 2:
            new_id = a.get("identity_id") or b.get("identity_id") or str(uuid.uuid4())
            conf = round(score / 3.0, 2)
            print(f"  [{brand_slug}] LINK score={score}/3 conf={conf} "
                  f"ig=@{a['handle']} ↔ tt=@{b['handle']}", file=sys.stderr)
            if not dry_run:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).isoformat()
                sb.table("creators").update({
                    "identity_id": new_id, "identity_confidence": conf, "identity_linked_at": now,
                }).eq("id", a["id"]).execute()
                sb.table("creators").update({
                    "identity_id": new_id, "identity_confidence": conf, "identity_linked_at": now,
                }).eq("id", b["id"]).execute()
            new_links += 1
        elif score == 1:
            candidates += 1
            print(f"  [{brand_slug}] candidate (manual review) "
                  f"ig=@{a['handle']} ↔ tt=@{b['handle']} (score=1)", file=sys.stderr)

    print(f"  [{brand_slug}] linked={new_links}, candidates_for_review={candidates}, "
          f"ambiguous_groups_skipped={skipped}", file=sys.stderr)
    return {"linked": new_links, "candidates": candidates, "skipped": skipped}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to brand slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brands = (sb.table("brands").select("id, slug").execute().data) or []
    if args.brand:
        brands = [b for b in brands if b["slug"] == args.brand]

    totals = {"linked": 0, "candidates": 0, "skipped": 0}
    for b in brands:
        r = process_brand(sb, b["id"], b["slug"], args.dry_run)
        for k in totals:
            totals[k] += r.get(k, 0)
    print(f"\n=== IDENTITY LINKING: {totals} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
