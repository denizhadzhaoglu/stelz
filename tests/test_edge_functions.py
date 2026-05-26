"""Edge Function health probes.

Each function gets a smoke test: send an empty / invalid request and check
that we get the EXPECTED error code (not a 5xx crash). This catches:
- function not deployed
- env var missing
- import-time crash
- auth misconfiguration

Run from project root:
    python3 tests/test_edge_functions.py
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
SUPA = os.environ["SUPABASE_URL"].rstrip("/")

# (slug, method, body, expected_status, must_be_json)
CASES = [
    # Anon-callable endpoints — should validate input and return 4xx, never 5xx
    ("cold-start-preview", "POST", {}, 400, True),
    ("cold-start-preview", "POST", {"handle": "nonexistent_zzz_xyz"}, 200, True),  # graceful empty result
    ("live-preview-scan", "POST", {}, 400, True),
    ("og-image", "GET", None, 200, False),  # generates image, may not be JSON

    # Auth-required — should return 401 with empty body
    ("stripe-create-topup-checkout", "POST", {}, 401, False),
    ("stripe-create-subscription-checkout", "POST", {}, 401, False),
    ("stripe-create-portal-session", "POST", {}, 401, False),
    ("creator-dm-draft", "POST", {}, 401, False),
    ("seed-brand-refs", "POST", {}, 401, False),

    # Webhook with no signature — should reject with 400/401
    ("stripe-webhook", "POST", {}, 400, False),
]


def run() -> tuple[int, int]:
    passed, failed = 0, 0
    print("=== Edge Function health probes ===")
    for slug, method, body, expect, want_json in CASES:
        url = f"{SUPA}/functions/v1/{slug}"
        try:
            if method == "POST":
                r = requests.post(url, json=body, timeout=20)
            else:
                r = requests.get(url, timeout=20)
        except Exception as e:
            print(f"  ✗ {slug:<40} EXCEPTION {type(e).__name__}: {str(e)[:80]}")
            failed += 1
            continue

        status_ok = r.status_code == expect
        body_msg = ""
        if want_json:
            try:
                _ = r.json()
            except Exception:
                body_msg = " (non-JSON body)"

        marker = "✓" if (status_ok and not body_msg) else "✗"
        print(f"  {marker} {slug:<40} {method} → HTTP {r.status_code} (expect {expect}){body_msg}")
        if status_ok and not body_msg:
            passed += 1
        else:
            failed += 1
    return passed, failed


if __name__ == "__main__":
    p, f = run()
    print(f"\n{p} passed, {f} failed")
    sys.exit(0 if f == 0 else 1)
