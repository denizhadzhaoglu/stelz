#!/usr/bin/env python3
"""Provision a new brand from a signup_leads row.

Given a lead id (or 'all' for all pending leads), this script:
1. Creates brand row (slug, name, active)
2. Creates brand_product_lines from notes/parsed input
3. Creates brand_hashtag_pools from notes
4. Creates subscription (trial) linked to the selected plan
5. Initializes credit_balance with 100 trial credits
6. Marks lead status='onboarded'

Idempotent: skip leads already onboarded.

Usage:
    python3 tools/stelz_brand_watch/25_provision_brand.py --lead-id <uuid>
    python3 tools/stelz_brand_watch/25_provision_brand.py --all-pending
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def parse_product_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    return [l for l in lines if l and not l.startswith("#")]


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:50]


def provision(sb, lead: dict) -> dict:
    print(f"\n--- Provisioning {lead['brand_name']} ---", file=sys.stderr)

    slug = lead.get("brand_slug") or slugify(lead["brand_name"])

    # 1. Brand
    existing = sb.table("brands").select("id").eq("slug", slug).execute()
    if existing.data:
        brand_id = existing.data[0]["id"]
        print(f"  brand exists: {brand_id}", file=sys.stderr)
    else:
        r = sb.table("brands").insert({"slug": slug, "name": lead["brand_name"], "active": True}).execute()
        brand_id = r.data[0]["id"]
        print(f"  created brand: {brand_id}", file=sys.stderr)

    # 2. Product lines (from product_lines field or parsed notes)
    pls = lead.get("product_lines") or []
    if not pls and lead.get("notes"):
        # try to extract from notes lines that look like "Product lines: ..."
        match = re.search(r"product\s+lines?[:\s]+(.+?)(?=\n[A-Z]|\Z)", lead["notes"], re.IGNORECASE | re.DOTALL)
        if match:
            pls = parse_product_lines(match.group(1))
    for pl_name in pls:
        pl_slug = slugify(pl_name)
        sb.table("brand_product_lines").upsert({
            "brand_id": brand_id,
            "slug": pl_slug,
            "name": pl_name,
        }, on_conflict="brand_id,slug").execute()
    print(f"  product_lines: {len(pls)}", file=sys.stderr)

    # 3. Hashtag pools
    hashtags = lead.get("hashtags") or []
    for tag in hashtags:
        tag = tag.lstrip("#").lower().strip()
        if not tag:
            continue
        try:
            sb.table("brand_hashtag_pools").upsert({
                "brand_id": brand_id,
                "hashtag": tag,
                "group_label": "user_provided",
                "platform": "instagram",
                "priority": 8,
            }, on_conflict="brand_id,hashtag,platform").execute()
        except Exception:
            pass
    print(f"  hashtags: {len(hashtags)}", file=sys.stderr)

    # 4. Subscription (trial)
    plan_slug = lead.get("plan_slug") or "pro"
    plan = sb.table("plans").select("id").eq("slug", plan_slug).execute()
    if not plan.data:
        plan = sb.table("plans").select("id").eq("slug", "pro").execute()
    plan_id = plan.data[0]["id"]
    trial_end = datetime.now(timezone.utc) + timedelta(days=14)

    existing_sub = sb.table("subscriptions").select("id").eq("brand_id", brand_id).execute()
    if not existing_sub.data:
        sb.table("subscriptions").insert({
            "brand_id": brand_id,
            "plan_id": plan_id,
            "status": "trial",
            "trial_ends_at": trial_end.isoformat(),
            "current_period_start": datetime.now(timezone.utc).isoformat(),
            "current_period_end": trial_end.isoformat(),
        }).execute()
        print(f"  subscription: trial of {plan_slug} until {trial_end.date()}", file=sys.stderr)
    else:
        print(f"  subscription exists", file=sys.stderr)

    # 5. Credit balance
    existing_credit = sb.table("credit_balances").select("brand_id").eq("brand_id", brand_id).execute()
    if not existing_credit.data:
        sb.table("credit_balances").insert({"brand_id": brand_id, "balance": 100}).execute()
        sb.table("credit_transactions").insert({
            "brand_id": brand_id,
            "amount": 100,
            "type": "trial_grant",
            "description": "14-day trial included credits",
        }).execute()
        print(f"  credits: 100 trial", file=sys.stderr)

    # 6. Mark lead as onboarded
    sb.table("signup_leads").update({"status": "onboarded"}).eq("id", lead["id"]).execute()

    return {
        "brand_id": brand_id,
        "slug": slug,
        "plan": plan_slug,
        "trial_ends": trial_end.isoformat(),
        "dashboard_url": f"https://stelz-brand-watch.vercel.app/?brand={slug}",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lead-id", help="Specific signup_leads.id to provision")
    parser.add_argument("--all-pending", action="store_true")
    args = parser.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.lead_id:
        r = sb.table("signup_leads").select("*").eq("id", args.lead_id).execute()
        leads = r.data or []
    elif args.all_pending:
        r = sb.table("signup_leads").select("*").eq("status", "new").execute()
        leads = r.data or []
    else:
        print("Need --lead-id or --all-pending", file=sys.stderr)
        sys.exit(1)

    if not leads:
        print("No leads to provision.", file=sys.stderr)
        return

    print(f"Provisioning {len(leads)} lead(s)...", file=sys.stderr)
    for lead in leads:
        try:
            result = provision(sb, lead)
            print(f"  ✓ {lead['brand_name']} → {result['dashboard_url']}", file=sys.stderr)
        except Exception as e:
            print(f"  ✗ {lead['brand_name']}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
