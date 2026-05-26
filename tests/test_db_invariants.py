"""DB invariant suite — every check should return 0 rows.

These are structural rules the data must always satisfy. The first thing
that breaks when the pipeline mis-fires is one of these. Add any new
invariant here when we find a new class of data corruption.

Run from project root:
    python3 tests/test_db_invariants.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))


# Each check: (label, threshold, sql). Check passes when COUNT(*) <= threshold.
CHECKS = [
    # Structural integrity
    ("creators_no_brand", 0, "SELECT COUNT(*) FROM creators WHERE brand_id IS NULL"),
    ("creators_no_platform", 0, "SELECT COUNT(*) FROM creators WHERE platform IS NULL"),
    ("creators_no_handle", 0, "SELECT COUNT(*) FROM creators WHERE handle IS NULL OR handle=''"),
    ("creators_dup_handle", 0,
        "SELECT COUNT(*) FROM (SELECT brand_id, platform, handle FROM creators GROUP BY 1,2,3 HAVING COUNT(*)>1) x"),

    ("content_no_brand", 0, "SELECT COUNT(*) FROM content_items WHERE brand_id IS NULL"),
    ("content_no_creator", 0, "SELECT COUNT(*) FROM content_items WHERE creator_id IS NULL"),
    ("content_no_external_id", 0,
        "SELECT COUNT(*) FROM content_items WHERE external_id IS NULL OR external_id=''"),
    ("content_brand_mismatch_creator", 0,
        "SELECT COUNT(*) FROM content_items ci JOIN creators c ON c.id=ci.creator_id WHERE ci.brand_id != c.brand_id"),

    ("images_orphan", 0,
        "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM content_items ci WHERE ci.id=img.content_item_id)"),
    ("images_no_brand", 0, "SELECT COUNT(*) FROM content_images WHERE brand_id IS NULL"),
    ("images_brand_mismatch", 0,
        "SELECT COUNT(*) FROM content_images img JOIN content_items ci ON ci.id=img.content_item_id WHERE img.brand_id != ci.brand_id"),

    ("detections_orphan_image", 0,
        "SELECT COUNT(*) FROM detections d WHERE NOT EXISTS (SELECT 1 FROM content_images img WHERE img.id=d.content_image_id)"),
    ("detections_no_brand", 0, "SELECT COUNT(*) FROM detections WHERE brand_id IS NULL"),
    ("detections_brand_mismatch", 0,
        "SELECT COUNT(*) FROM detections d JOIN content_images img ON img.id=d.content_image_id WHERE d.brand_id != img.brand_id"),
    ("hit_no_product_line", 0,
        "SELECT COUNT(*) FROM detections WHERE detected=true AND product_line IS NULL"),

    # Pipeline freshness (these are soft thresholds — bump if needed)
    ("scans_stuck_running_30m", 0,
        "SELECT COUNT(*) FROM scan_requests WHERE status='running' AND requested_at < NOW() - INTERVAL '30 minutes'"),
    ("scans_stuck_pending_24h", 0,
        "SELECT COUNT(*) FROM scan_requests WHERE status='pending' AND requested_at < NOW() - INTERVAL '24 hours'"),
    ("pending_detection_images_high", 500,  # soft cap
        "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM detections d WHERE d.content_image_id=img.id)"),

    # Billing integrity
    ("brand_active_no_credit_row", 0,
        "SELECT COUNT(*) FROM brands b WHERE active=true AND NOT EXISTS (SELECT 1 FROM credit_balances cb WHERE cb.brand_id=b.id)"),
    ("credit_balance_negative", 0, "SELECT COUNT(*) FROM credit_balances WHERE balance < 0"),

    # Moderator reject must be sticky: no rejected detection should appear
    # in v_detections_full (the surface that drives the feed). If this
    # fails, a Pro re-verify or new prompt resurrected a previously-rejected
    # hit. Image-level exclusion should prevent this.
    ("resurrected_rejections", 0,
        "SELECT COUNT(*) FROM v_detections_full v WHERE v.detected=true AND EXISTS (SELECT 1 FROM detections d WHERE d.id=v.detection_id AND d.moderation_label='rejected')"),

    # Mojibake detection — text columns containing double-UTF-8 encoding
    # signature "√ã" (or other common ones). Caught the STELZ brand name
    # bug that sat in DB for 9+ days. Add patterns as we find them.
    ("brands_mojibake", 0,
        "SELECT COUNT(*) FROM brands WHERE name LIKE '%√ã%' OR name LIKE '%Ã©%' OR name LIKE '%Ã«%'"),
    ("creators_mojibake", 0,
        "SELECT COUNT(*) FROM creators WHERE full_name LIKE '%√ã%' OR full_name LIKE '%Ã©%' OR full_name LIKE '%Ã«%'"),
    ("subcultures_mojibake", 0,
        "SELECT COUNT(*) FROM subcultures WHERE name LIKE '%√ã%' OR description LIKE '%√ã%'"),
    ("plans_mojibake", 0, "SELECT COUNT(*) FROM plans WHERE name LIKE '%√ã%'"),
]


def run() -> tuple[int, int]:
    passed, failed = 0, 0
    print("=== DB invariant suite ===")
    for label, threshold, sql in CHECKS:
        try:
            r = sb.rpc("exec_sql_count", {"q": sql}).execute()
            count = r.data
        except Exception:
            # Fallback: PostgREST query of a known view. Run via raw select
            # if exec_sql_count RPC isn't installed yet.
            # Use the supabase-py PostgREST escape hatch.
            try:
                import requests
                url = f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/exec_sql_count"
                hdr = {
                    "apikey": os.getenv("SUPABASE_SECRET_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SECRET_KEY')}",
                    "Content-Type": "application/json",
                }
                resp = requests.post(url, headers=hdr, json={"q": sql}, timeout=30)
                if resp.status_code == 404:
                    raise Exception("exec_sql_count RPC not installed — install via migration")
                resp.raise_for_status()
                count = resp.json()
            except Exception as e:
                print(f"  ⚠ {label:<40} could not run: {e}")
                failed += 1
                continue

        try:
            count = int(count)
        except Exception:
            count = -1
        ok = count <= threshold
        status = "✓" if ok else "✗"
        suffix = "" if threshold == 0 else f" (threshold {threshold})"
        print(f"  {status} {label:<40} count={count}{suffix}")
        if ok:
            passed += 1
        else:
            failed += 1
    return passed, failed


if __name__ == "__main__":
    p, f = run()
    print(f"\n{p} passed, {f} failed")
    sys.exit(0 if f == 0 else 1)
