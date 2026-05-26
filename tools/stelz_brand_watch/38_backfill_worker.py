#!/usr/bin/env python3
"""Backfill worker for newly-activated paid brands.

Finds subscriptions that just went active on a plan with a positive
backfill_days feature and haven't run a backfill yet. For each, enqueues a
scan_request with scope='backfill'. The existing scan queue worker
(32_process_scan_queue.py) picks it up and runs the deeper pipeline defined
in build_steps('backfill').

When that scan completes, the queue worker writes backfill_completed_at on
the subscription, so this worker won't re-enqueue.

Run as a Railway cron every 5-15 min; safe to run every minute (no-op when
nothing to do).

Usage:
    python3 tools/stelz_brand_watch/38_backfill_worker.py
    python3 tools/stelz_brand_watch/38_backfill_worker.py --brand stelz
    python3 tools/stelz_brand_watch/38_backfill_worker.py --dry-run
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

# Conservative credit charge for a backfill: it's a single deep run, so we
# bill the same as a 'deep' scan to keep credit accounting consistent.
BACKFILL_CREDITS = 50


def find_backfill_candidates(sb, brand_slug: str | None = None):
    """Active paid subscriptions on a plan with backfill_days>0 that haven't
    run a backfill yet. Skips trial-only plans (free).
    """
    q = sb.table("subscriptions").select(
        "id, brand_id, status, backfill_started_at, backfill_completed_at, backfill_scan_id, "
        "plan:plans!inner(slug, name, features), "
        "brand:brands!inner(id, slug, name)"
    ).eq("status", "active").is_("backfill_completed_at", "null")
    rows = (q.execute().data) or []
    out = []
    for r in rows:
        plan = r.get("plan") or {}
        brand = r.get("brand") or {}
        if brand_slug and brand.get("slug") != brand_slug:
            continue
        feats = plan.get("features") or {}
        days = feats.get("backfill_days") or 0
        if days <= 0:
            continue  # free tier or no historical entitlement
        out.append({**r, "_backfill_days": days})
    return out


def enqueue_backfill(sb, sub: dict, dry_run: bool) -> str | None:
    brand = sub.get("brand") or {}
    brand_id = brand.get("id")
    if not brand_id:
        return None

    print(f"  → enqueue backfill for {brand.get('slug')} ({sub['_backfill_days']}d)", file=sys.stderr)
    if dry_run:
        return None

    # Check if there's already an enqueued/running backfill we never finished
    # (e.g. worker died mid-run). Prefer reusing that row over creating new.
    existing = (sb.table("scan_requests")
                .select("id, status")
                .eq("brand_id", brand_id).eq("scope", "backfill")
                .in_("status", ["queued", "running"])
                .order("requested_at", desc=True).limit(1)
                .execute().data) or []
    if existing:
        scan_id = existing[0]["id"]
        print(f"    re-using in-flight backfill scan {scan_id}", file=sys.stderr)
    else:
        ins = sb.table("scan_requests").insert({
            "brand_id": brand_id,
            "status": "queued",
            "scope": "backfill",
            "credits_charged": BACKFILL_CREDITS,
            "requested_by": "system:backfill_worker",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        scan_id = ins.data[0]["id"]
        print(f"    queued scan {scan_id}", file=sys.stderr)

    # Mark on the subscription so we don't double-enqueue and so the queue
    # worker can flip backfill_completed_at when this exact scan finishes.
    sb.table("subscriptions").update({
        "backfill_started_at": datetime.now(timezone.utc).isoformat(),
        "backfill_scan_id": scan_id,
    }).eq("id", sub["id"]).execute()

    return scan_id


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", help="Restrict to a single brand slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    candidates = find_backfill_candidates(sb, brand_slug=args.brand)
    if not candidates:
        print("No backfill candidates.", file=sys.stderr)
        return

    print(f"{len(candidates)} subscription(s) need backfill", file=sys.stderr)
    queued = 0
    for sub in candidates:
        scan_id = enqueue_backfill(sb, sub, args.dry_run)
        if scan_id:
            queued += 1

    print(f"\n=== BACKFILL WORKER: queued {queued} scan(s) ===", file=sys.stderr)


if __name__ == "__main__":
    main()
