#!/usr/bin/env python3
"""56_brand_bootstrap.py — Onboard a new brand into the system.

Phase 5 deliverable: makes it possible to onboard Alpro / Action / fritz-kola
in under 30 minutes instead of weeks of manual seeding.

Pipeline:
  1. Insert brand row (name, slug, owner)
  2. Insert N seed hashtags into brand_hashtag_pools
  3. Trigger 22_perplexity_scout.py for web-discovered hashtags
  4. Trigger 30_seed_subcultures.py with category-appropriate subcultures
  5. Trigger 19_auto_add.py to scrape seed hashtags and populate discovery_queue
  6. Wait for first detection batch (33_detect_pending)
  7. Trigger 51_build_edges + 53_compute_resonance in COLD bootstrap mode
  8. Surface first top-50 candidates in the dashboard

By design, the per-brand machinery is identical to STELZ — only the seed list
differs. The bootstrap-mode logic in 53_compute_resonance.py auto-detects
cold (<10 hits) and shifts weights to emphasize hashtag + geo.

Usage:
    python3 tools/stelz_brand_watch/56_brand_bootstrap.py --slug fritz-kola \\
        --name "fritz-kola" \\
        --hashtags fritzkola,fritzlimonade,fritzcola \\
        --category beverages

  Optional flags:
    --skip-scrape   (don't auto-trigger 19_auto_add; manual run later)
    --dry-run       (print plan, don't execute)
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

CATEGORIES = {
    "beverages":  ["student_life", "vrijmibo", "festivals_events", "house_parties", "horeca_nightlife"],
    "food":       ["foodies_lifestyle", "horeca_nightlife", "expats_internationals"],
    "fashion":    ["student_life", "fitness_wellness", "expats_internationals"],
    "lifestyle":  ["student_life", "vrijmibo", "fitness_wellness", "foodies_lifestyle"],
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True, help="URL-safe brand slug, e.g. 'fritz-kola'")
    p.add_argument("--name", required=True, help="Display name")
    p.add_argument("--hashtags", required=True, help="Comma-separated seed hashtags (no #)")
    p.add_argument("--category", default="beverages", choices=list(CATEGORIES.keys()))
    p.add_argument("--owner-email", default="meinte.stinstra@dorstenlesser.nl")
    p.add_argument("--skip-scrape", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    print(f"\n=== BRAND BOOTSTRAP: {args.name} ({args.slug}) ===\n", file=sys.stderr)

    # Step 1: brand row
    existing = sb.table("brands").select("id").eq("slug", args.slug).execute().data
    if existing:
        brand_id = existing[0]["id"]
        print(f"[1] Brand exists: {brand_id}", file=sys.stderr)
    else:
        if args.dry_run:
            print(f"[1] WOULD insert brand({args.slug}, {args.name})", file=sys.stderr)
            return
        r = sb.table("brands").insert({
            "slug": args.slug, "name": args.name, "active": True,
            "owner_email": args.owner_email,
        }).execute()
        brand_id = r.data[0]["id"]
        print(f"[1] Inserted brand: {brand_id}", file=sys.stderr)

    # Step 2: seed hashtags
    hashtags = [h.strip().lstrip("#").lower() for h in args.hashtags.split(",") if h.strip()]
    print(f"[2] Seeding {len(hashtags)} hashtags: {hashtags}", file=sys.stderr)
    if not args.dry_run:
        rows = [{"brand_id": brand_id, "hashtag": h, "priority": 5, "auto_added": False} for h in hashtags]
        sb.table("brand_hashtag_pools").upsert(rows, on_conflict="brand_id,hashtag").execute()

    # Step 3: Perplexity scout for related hashtags
    print(f"[3] Perplexity hashtag scout (web-discover related tags)", file=sys.stderr)
    if not args.dry_run:
        try:
            subprocess.run(
                ["python3", str(PA_ROOT / "tools" / "stelz_brand_watch" / "22_perplexity_scout.py"),
                 "--brand-slug", args.slug],
                check=False, timeout=300,
            )
        except Exception as e:
            print(f"  Perplexity scout failed (non-fatal): {e}", file=sys.stderr)

    # Step 4: seed subcultures
    subc_list = CATEGORIES[args.category]
    print(f"[4] Seeding subcultures for category '{args.category}': {subc_list}", file=sys.stderr)
    if not args.dry_run:
        try:
            subprocess.run(
                ["python3", str(PA_ROOT / "tools" / "stelz_brand_watch" / "30_seed_subcultures.py"),
                 "--brand-slug", args.slug],
                check=False, timeout=120,
            )
        except Exception as e:
            print(f"  seed_subcultures failed (non-fatal): {e}", file=sys.stderr)

    if args.skip_scrape:
        print("\n[Done] Brand bootstrapped. Manual next steps:", file=sys.stderr)
        print(f"  - python3 tools/stelz_brand_watch/19_auto_add.py  # scrape seed hashtags", file=sys.stderr)
        print(f"  - python3 tools/stelz_brand_watch/18_daily_scan.py  # scrape promoted creators", file=sys.stderr)
        print(f"  - python3 tools/stelz_brand_watch/33_detect_pending.py  # vision detect", file=sys.stderr)
        print(f"  - python3 tools/stelz_brand_watch/51_build_edges.py --brand {args.slug}", file=sys.stderr)
        print(f"  - python3 tools/stelz_brand_watch/53_compute_resonance.py --brand {args.slug}", file=sys.stderr)
        return

    # Step 5-7: full pipeline
    print(f"\n[5-7] Running full discovery pipeline (will take 15-30 min)", file=sys.stderr)
    if args.dry_run:
        print("  WOULD run: 19_auto_add, 18_daily_scan, 33_detect_pending, 51, 53", file=sys.stderr)
        return

    for label, cmd in [
        ("auto_add",        ["19_auto_add.py"]),
        ("daily_scan",      ["18_daily_scan.py", "--max-creators", "50"]),
        ("detect_pending",  ["33_detect_pending.py", "--brand-slug", args.slug, "--limit", "200"]),
        ("build_edges",     ["51_build_edges.py", "--brand", args.slug]),
        ("compute_srs",     ["53_compute_resonance.py", "--brand", args.slug, "--top", "20"]),
    ]:
        print(f"\n  ▸ Running {label}", file=sys.stderr)
        try:
            subprocess.run(
                ["python3", str(PA_ROOT / "tools" / "stelz_brand_watch" / cmd[0])] + cmd[1:],
                check=False, timeout=1800,
            )
        except Exception as e:
            print(f"    failed: {e}", file=sys.stderr)

    print(f"\n=== BOOTSTRAP COMPLETE for {args.slug} ===", file=sys.stderr)
    print(f"View results: https://stelz-brand-watch.vercel.app (switch brand via URL ?brand={args.slug})", file=sys.stderr)


if __name__ == "__main__":
    main()
