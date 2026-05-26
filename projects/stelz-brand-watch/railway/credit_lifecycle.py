#!/usr/bin/env python3
"""Daily credit lifecycle: monthly renewal + expiry of stale grants.

Runs idempotently in the daily Railway cron:
  1. For every brand with an active or trial subscription, call
     monthly_renewal_for_brand() — the RPC no-ops if already renewed
     this calendar month.
  2. Call expire_old_grants() once globally — sweeps any grant past
     its expires_at, deducts remaining from balance, logs a -X tx.

Both RPCs are atomic + idempotent. Safe to run as often as the cron does.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def main():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    # 1. Expire old grants globally (no per-brand loop needed).
    res = sb.rpc("expire_old_grants", {}).execute()
    expired = res.data if isinstance(res.data, int) else 0
    print(f"Expired {expired} stale grant(s)", file=sys.stderr)

    # 2. Monthly renewal for every active/trial brand. The RPC is idempotent
    #    per (brand, calendar-month) so we can hammer it daily.
    brands = (sb.table("brands").select("id, slug, name")
              .eq("active", True)
              .execute().data) or []
    renewed = 0
    for b in brands:
        try:
            res = sb.rpc("monthly_renewal_for_brand", {"p_brand_id": b["id"]}).execute()
            row = res.data
            if isinstance(row, list):
                row = row[0] if row else None
            if not row:
                print(f"  {b['slug']}: no result", file=sys.stderr)
                continue
            if row.get("ok") and row.get("granted", 0) > 0:
                renewed += 1
                print(f"  {b['slug']}: +{row['granted']} cr (balance now {row['new_balance']})", file=sys.stderr)
        except Exception as e:
            print(f"  {b['slug']}: error {e}", file=sys.stderr)

    print(f"\n=== CREDIT LIFECYCLE: expired={expired} renewed_this_month={renewed} ===", file=sys.stderr)


if __name__ == "__main__":
    main()
