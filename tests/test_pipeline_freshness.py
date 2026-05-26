"""Pipeline freshness checks — soft thresholds that surface drift before it
becomes a customer-visible bug.

Run from project root:
    python3 tests/test_pipeline_freshness.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))


def _count(sql: str) -> int:
    r = sb.rpc("exec_sql_count", {"q": sql}).execute()
    return int(r.data or 0)


def _scalar(sql: str) -> int:
    # Reuses exec_sql_count; SQL must be a SELECT COUNT(*) statement.
    return _count(sql)


CHECKS = [
    ("scans_completed_last_24h", 1, ">=",
        "SELECT COUNT(*) FROM scan_requests WHERE status='completed' AND completed_at > NOW() - INTERVAL '24 hours'"),
    ("detections_last_1h", 0, ">=",
        "SELECT COUNT(*) FROM detections WHERE created_at > NOW() - INTERVAL '1 hour'"),
    ("detections_last_24h", 50, ">=",
        "SELECT COUNT(*) FROM detections WHERE created_at > NOW() - INTERVAL '24 hours'"),
    ("hits_last_24h", 5, ">=",
        "SELECT COUNT(*) FROM detections WHERE detected=true AND created_at > NOW() - INTERVAL '24 hours'"),
    ("pending_detection_images", 500, "<=",
        "SELECT COUNT(*) FROM content_images img WHERE NOT EXISTS (SELECT 1 FROM detections d WHERE d.content_image_id=img.id)"),
    ("creators_active_brand", 100, ">=",
        "SELECT COUNT(*) FROM creators WHERE brand_id='68a715dd-751e-4f62-9392-734370837120'"),
    ("active_brands", 1, ">=",
        "SELECT COUNT(*) FROM brands WHERE active=true"),
]


def run() -> tuple[int, int]:
    passed = failed = 0
    print("=== Pipeline freshness ===")
    for label, threshold, op, sql in CHECKS:
        try:
            v = _scalar(sql)
        except Exception as e:
            print(f"  ⚠ {label:<40} could not run: {str(e)[:80]}")
            failed += 1
            continue
        if op == ">=":
            ok = v >= threshold
        else:
            ok = v <= threshold
        marker = "✓" if ok else "✗"
        print(f"  {marker} {label:<40} {v} {op} {threshold}")
        if ok:
            passed += 1
        else:
            failed += 1
    return passed, failed


if __name__ == "__main__":
    p, f = run()
    print(f"\n{p} passed, {f} failed")
    sys.exit(0 if f == 0 else 1)
