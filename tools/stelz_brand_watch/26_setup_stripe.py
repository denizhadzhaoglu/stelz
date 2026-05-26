#!/usr/bin/env python3
"""Setup Stripe products + prices for Lens plans.

Creates (idempotent):
- Stripe Product: Lens Starter, Lens Pro, Lens Enterprise
- Stripe Price (monthly EUR): linked to each product
- Backfills stripe_price_id into plans table

Requires STRIPE_SECRET_KEY in .env (test or live).

Usage:
    python3 tools/stelz_brand_watch/26_setup_stripe.py
    python3 tools/stelz_brand_watch/26_setup_stripe.py --live  # use live mode
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

STRIPE_BASE = "https://api.stripe.com/v1"

PLANS = [
    {"slug": "starter", "name": "Lens Starter", "amount_eur": 500, "description": "200 creators, Instagram, 7-day backfill, weekly reports"},
    {"slug": "pro", "name": "Lens Pro", "amount_eur": 1500, "description": "1000 creators, IG + TikTok, 90-day backfill, daily reports, Slack alerts"},
    # Enterprise is custom-priced, no Stripe price
]


def stripe(method: str, path: str, key: str, data: dict | None = None) -> dict:
    r = requests.request(
        method,
        STRIPE_BASE + path,
        auth=(key, ""),
        data=data,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe {method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def find_or_create_product(key: str, name: str, description: str) -> str:
    # List products to find existing
    res = stripe("GET", f"/products?limit=100", key)
    for p in res.get("data", []):
        if p["name"] == name and p["active"]:
            return p["id"]
    res = stripe("POST", "/products", key, {"name": name, "description": description})
    return res["id"]


def find_or_create_price(key: str, product_id: str, amount_cents: int) -> str:
    res = stripe("GET", f"/prices?product={product_id}&active=true&limit=20", key)
    for p in res.get("data", []):
        if p.get("recurring", {}).get("interval") == "month" and p["unit_amount"] == amount_cents and p["currency"] == "eur":
            return p["id"]
    res = stripe("POST", "/prices", key, {
        "product": product_id,
        "unit_amount": amount_cents,
        "currency": "eur",
        "recurring[interval]": "month",
    })
    return res["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use live mode key (default: test)")
    args = parser.parse_args()

    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        sys.exit("STRIPE_SECRET_KEY not in .env")
    if not args.live and not key.startswith("sk_test_"):
        print(f"WARNING: STRIPE_SECRET_KEY does not start with sk_test_ — proceeding anyway", file=sys.stderr)

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    for plan in PLANS:
        print(f"\n--- {plan['name']} ---", file=sys.stderr)
        product_id = find_or_create_product(key, plan["name"], plan["description"])
        print(f"  product: {product_id}", file=sys.stderr)
        price_id = find_or_create_price(key, product_id, plan["amount_eur"] * 100)
        print(f"  price:   {price_id}  (€{plan['amount_eur']}/month)", file=sys.stderr)

        # Update plans table
        sb.table("plans").update({"stripe_price_id": price_id}).eq("slug", plan["slug"]).execute()
        print(f"  → backfilled plans.stripe_price_id", file=sys.stderr)

    print(f"\n=== Stripe setup complete ===", file=sys.stderr)
    plans = sb.table("plans").select("slug, name, stripe_price_id, price_eur_month").execute().data
    for p in plans:
        print(f"  {p['slug']:<12} {p['name']:<22} €{p['price_eur_month']}/mo   price_id: {p.get('stripe_price_id') or 'n/a'}", file=sys.stderr)


if __name__ == "__main__":
    main()
