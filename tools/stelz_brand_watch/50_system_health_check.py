#!/usr/bin/env python3
"""Daily system-health check. Runs the same invariants the spot-api
/system/health endpoint runs, but queries Supabase directly so it works
from the Railway worker without needing a Vercel SSO bypass token.

When a check fails (or returns a 'warn' threshold), a row is inserted into
public.system_health_alerts (status='open'). On the next run, when a
previously-failing check returns OK, the open alert is auto-resolved.

Designed to run from the aux cron once per day. Trivial cost.

Usage:
    python3 tools/stelz_brand_watch/50_system_health_check.py
    python3 tools/stelz_brand_watch/50_system_health_check.py --dry-run
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# (name, threshold, op, sql, severity)
CHECKS = [
    # Structural — fail
    ("creators_no_brand", 0, "<=", "SELECT COUNT(*) FROM creators WHERE brand_id IS NULL", "fail"),
    ("creators_no_handle", 0, "<=", "SELECT COUNT(*) FROM creators WHERE handle IS NULL OR handle=''", "fail"),
    ("creators_dup", 0, "<=",
     "SELECT COUNT(*) FROM (SELECT brand_id, platform, handle FROM creators GROUP BY 1,2,3 HAVING COUNT(*)>1) x", "fail"),
    ("content_no_brand", 0, "<=", "SELECT COUNT(*) FROM content_items WHERE brand_id IS NULL", "fail"),
    ("content_no_creator", 0, "<=", "SELECT COUNT(*) FROM content_items WHERE creator_id IS NULL", "fail"),
    ("content_brand_mismatch", 0, "<=",
     "SELECT COUNT(*) FROM content_items ci JOIN creators c ON c.id=ci.creator_id WHERE ci.brand_id != c.brand_id", "fail"),
    ("images_orphan", 0, "<=",
     "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM content_items ci WHERE ci.id=img.content_item_id)", "fail"),
    ("images_brand_mismatch", 0, "<=",
     "SELECT COUNT(*) FROM content_images img JOIN content_items ci ON ci.id=img.content_item_id WHERE img.brand_id != ci.brand_id", "fail"),
    ("detections_orphan", 0, "<=",
     "SELECT COUNT(*) FROM detections d WHERE NOT EXISTS (SELECT 1 FROM content_images img WHERE img.id=d.content_image_id)", "fail"),
    ("detections_brand_mismatch", 0, "<=",
     "SELECT COUNT(*) FROM detections d JOIN content_images img ON img.id=d.content_image_id WHERE d.brand_id != img.brand_id", "fail"),
    # Pipeline — warn
    ("scans_stuck_running_30m", 0, "<=",
     "SELECT COUNT(*) FROM scan_requests WHERE status='running' AND requested_at < NOW() - INTERVAL '30 minutes'", "warn"),
    ("scans_stuck_pending_24h", 0, "<=",
     "SELECT COUNT(*) FROM scan_requests WHERE status='pending' AND requested_at < NOW() - INTERVAL '24 hours'", "warn"),
    ("pending_detection_images", 500, "<=",
     "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM detections d WHERE d.content_image_id=img.id)", "warn"),
    ("detections_last_1h", 1, ">=",
     "SELECT COUNT(*) FROM detections WHERE created_at > NOW() - INTERVAL '1 hour'", "warn"),
    ("hits_last_24h", 1, ">=",
     "SELECT COUNT(*) FROM detections WHERE detected=true AND created_at > NOW() - INTERVAL '24 hours'", "warn"),
    # Billing
    ("brand_active_no_credit_row", 0, "<=",
     "SELECT COUNT(*) FROM brands b WHERE active=true AND NOT EXISTS (SELECT 1 FROM credit_balances cb WHERE cb.brand_id=b.id)", "fail"),
    ("credit_balance_negative", 0, "<=", "SELECT COUNT(*) FROM credit_balances WHERE balance < 0", "fail"),
    # Mojibake — added 21 May after STELZ brand-name corruption was visible 9+ days
    ("brands_mojibake", 0, "<=",
     "SELECT COUNT(*) FROM brands WHERE name LIKE '%√ã%' OR name LIKE '%Ã©%' OR name LIKE '%Ã«%'", "warn"),
    ("creators_mojibake", 0, "<=",
     "SELECT COUNT(*) FROM creators WHERE full_name LIKE '%√ã%' OR full_name LIKE '%Ã©%' OR full_name LIKE '%Ã«%'", "warn"),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    run_id = str(uuid.uuid4())

    results = []
    for name, threshold, op, sql, severity in CHECKS:
        try:
            v = int(sb.rpc("exec_sql_count", {"q": sql}).execute().data or 0)
        except Exception as e:
            print(f"  ERR {name}: {e}", file=sys.stderr)
            v = -1
        ok = (v <= threshold) if op == "<=" else (v >= threshold)
        status = "ok" if ok else severity
        results.append({"name": name, "status": status, "value": v, "threshold": threshold, "op": op, "severity": severity})

    fails = [r for r in results if r["status"] == "fail"]
    warns = [r for r in results if r["status"] == "warn"]
    oks = [r for r in results if r["status"] == "ok"]
    print(f"ok={len(oks)} warn={len(warns)} fail={len(fails)} run_id={run_id}", file=sys.stderr)
    for r in fails + warns:
        print(f"  {r['status']:<4} {r['name']:<32} {r['value']} {r['op']} {r['threshold']}", file=sys.stderr)

    if args.dry_run:
        return

    # Auto-resolve previously-open alerts that are now OK
    ok_names = [r["name"] for r in oks]
    if ok_names:
        sb.table("system_health_alerts").update({
            "resolved_at": "now()", "status": "resolved",
        }).eq("status", "open").in_("check_name", ok_names).execute()

    # Raise new alerts for failures/warns (skip if already open for this check)
    for r in fails + warns:
        existing = (sb.table("system_health_alerts")
                      .select("id")
                      .eq("check_name", r["name"])
                      .eq("status", "open")
                      .limit(1).execute())
        if existing.data:
            continue
        sb.table("system_health_alerts").insert({
            "run_id": run_id,
            "check_name": r["name"],
            "severity": r["status"],
            "observed_value": r["value"],
            "threshold_value": r["threshold"],
            "op": r["op"],
            "message": f"{r['name']} = {r['value']} (expected {r['op']} {r['threshold']})",
            "status": "open",
        }).execute()


if __name__ == "__main__":
    main()
