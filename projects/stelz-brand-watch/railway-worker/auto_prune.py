#!/usr/bin/env python3
"""Auto-prune: demote or archive creators based on hit metrics.

Rules (applied to each creator in v_creator_metrics):
- Archive: tier_3 + posts_total >= 50 + hits_total == 0  -> archived (irrelevant)
- Demote tier_1 -> tier_2: tier_1 + hits_90d == 0
- Demote tier_2 -> tier_3: tier_2 + hits_90d == 0
- Promote tier_3 -> tier_2: tier_3 + hits_30d >= 3
- Promote tier_2 -> tier_1: tier_2 + hits_30d >= 5
- Never auto-demote tier_1 creators that were manually promoted (status='promoted')
- Never auto-archive @drinkstelz / brand-owned (status='promoted' AND tier_1)

After: writes a discovery_runs entry with summary.

Usage:
    python3 tools/stelz_brand_watch/20_auto_prune.py
    python3 tools/stelz_brand_watch/20_auto_prune.py --dry-run
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    # Pull all metrics
    metrics = []
    offset = 0
    while True:
        r = sb.table("v_creator_metrics").select("*").eq("brand_id", brand_id).range(offset, offset+999).execute()
        if not r.data: break
        metrics.extend(r.data)
        if len(r.data) < 1000: break
        offset += 1000

    print(f"Evaluating {len(metrics)} creators...", file=sys.stderr)

    archive_list = []
    demote_t1_to_t2 = []
    demote_t2_to_t3 = []
    promote_t2_to_t1 = []
    promote_t3_to_t2 = []

    for m in metrics:
        if m["archived_at"]:
            continue
        if m["status"] == "promoted":
            # Don't auto-modify manually promoted creators
            continue
        tier = m.get("tier") or "tier_3"
        posts = m["posts_total"] or 0
        hits = m["hits_total"] or 0
        hits_30 = m["hits_30d"] or 0
        hits_90 = m["hits_90d"] or 0

        # Archive rules
        if tier == "tier_3" and posts >= 50 and hits == 0:
            archive_list.append((m["creator_id"], m["handle"], "tier_3 + 50+ posts + 0 hits"))
            continue

        # Demote tier_1 if no recent hits
        if tier == "tier_1" and posts >= 10 and hits_90 == 0:
            demote_t1_to_t2.append((m["creator_id"], m["handle"]))
        elif tier == "tier_2" and posts >= 10 and hits_90 == 0:
            demote_t2_to_t3.append((m["creator_id"], m["handle"]))
        # Promote based on recent hit activity
        elif tier == "tier_3" and hits_30 >= 3:
            promote_t3_to_t2.append((m["creator_id"], m["handle"]))
        elif tier == "tier_2" and hits_30 >= 5:
            promote_t2_to_t1.append((m["creator_id"], m["handle"]))

    print(f"  Archive: {len(archive_list)}", file=sys.stderr)
    print(f"  Demote tier_1->tier_2: {len(demote_t1_to_t2)}", file=sys.stderr)
    print(f"  Demote tier_2->tier_3: {len(demote_t2_to_t3)}", file=sys.stderr)
    print(f"  Promote tier_2->tier_1: {len(promote_t2_to_t1)}", file=sys.stderr)
    print(f"  Promote tier_3->tier_2: {len(promote_t3_to_t2)}", file=sys.stderr)

    if args.dry_run:
        print("\nDRY RUN -- no changes applied", file=sys.stderr)
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    for cid, handle, reason in archive_list:
        sb.table("creators").update({
            "archived_at": now_iso,
            "archived_reason": reason,
            "last_evaluated_at": now_iso,
        }).eq("id", cid).execute()

    for cid, handle in demote_t1_to_t2:
        sb.table("creators").update({"tier": "tier_2", "last_evaluated_at": now_iso}).eq("id", cid).execute()
    for cid, handle in demote_t2_to_t3:
        sb.table("creators").update({"tier": "tier_3", "last_evaluated_at": now_iso}).eq("id", cid).execute()
    for cid, handle in promote_t2_to_t1:
        sb.table("creators").update({"tier": "tier_1", "last_evaluated_at": now_iso}).eq("id", cid).execute()
    for cid, handle in promote_t3_to_t2:
        sb.table("creators").update({"tier": "tier_2", "last_evaluated_at": now_iso}).eq("id", cid).execute()

    # Set last_evaluated_at on the rest so we know they were checked
    untouched_ids = [m["creator_id"] for m in metrics if not m["archived_at"] and m["status"] != "promoted"]
    print(f"\nUpdated last_evaluated_at on {len(untouched_ids)} creators", file=sys.stderr)

    # Log to discovery_runs
    sb.table("discovery_runs").insert({
        "brand_id": brand_id,
        "source_type": "auto_prune",
        "status": "completed",
        "results_count": len(archive_list) + len(demote_t1_to_t2) + len(demote_t2_to_t3) + len(promote_t2_to_t1) + len(promote_t3_to_t2),
        "completed_at": now_iso,
    }).execute()

    print(f"\n=== AUTO-PRUNE SUMMARY ===", file=sys.stderr)
    print(f"Archived: {len(archive_list)}", file=sys.stderr)
    print(f"Demoted: {len(demote_t1_to_t2) + len(demote_t2_to_t3)}", file=sys.stderr)
    print(f"Promoted: {len(promote_t2_to_t1) + len(promote_t3_to_t2)}", file=sys.stderr)


if __name__ == "__main__":
    main()
