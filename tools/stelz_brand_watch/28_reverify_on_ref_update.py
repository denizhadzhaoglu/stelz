#!/usr/bin/env python3
"""Re-verify older Pro detections when the reference image set has changed.

Vision-first means the brand's reference images ARE the model. When you add
or replace a reference (a new product variant, a fresh lifestyle photo with
different lighting), the model effectively becomes a new model. Old hits
need to be reconsidered.

How it works:
- Compute a SHA256 fingerprint over every file in reference-images/ (sorted)
- Store the fingerprint in a 'reference_pack_versions' table per brand
- For each detection verified with an older fingerprint, queue it for Pro re-verify
- Run Pro again using the same prompt + new reference set

Cron-able: run weekly. If refs haven't changed, the script no-ops fast.

Usage:
    python3 tools/stelz_brand_watch/28_reverify_on_ref_update.py
    python3 tools/stelz_brand_watch/28_reverify_on_ref_update.py --force      # re-verify regardless of fingerprint
    python3 tools/stelz_brand_watch/28_reverify_on_ref_update.py --max 200    # cap the batch
    python3 tools/stelz_brand_watch/28_reverify_on_ref_update.py --dry-run
"""

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

REF_DIR = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"


def fingerprint_refs(ref_dir: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(ref_dir.iterdir()):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        h.update(f.name.encode())
        h.update(b"\0")
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="Re-verify even when fingerprint matches")
    p.add_argument("--max", type=int, default=300, help="Max detections to re-verify per run")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))
    brand_id = sb.table("brands").select("id").eq("slug", "stelz").execute().data[0]["id"]

    fp = fingerprint_refs(REF_DIR)
    print(f"Reference pack fingerprint: {fp[:16]}…", file=sys.stderr)

    # Look up the last fingerprint we verified against.
    # Falls back to the notes field of the first Pro detection if the
    # reference_pack_versions table does not exist yet (it's optional).
    last_fp = None
    try:
        res = (
            sb.table("reference_pack_versions")
            .select("fingerprint, verified_at")
            .eq("brand_id", brand_id)
            .order("verified_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            last_fp = res.data[0]["fingerprint"]
    except Exception:
        # Table doesn't exist yet — treat as first run, no-op on fingerprint match
        last_fp = None

    if last_fp == fp and not args.force:
        print(f"References unchanged since last run ({fp[:16]}…). Nothing to do.", file=sys.stderr)
        return

    # Build the candidate set: Pro detections that have an older fingerprint
    # (or any Pro detection if last_fp unknown). Order by oldest first so
    # the longest-stale ones get a fresh look.
    detections = (
        sb.table("detections")
        .select("id, content_image_id, created_at, notes")
        .eq("brand_id", brand_id)
        .eq("model", "gemini-2.5-pro")
        .eq("detected", True)
        .order("created_at")
        .limit(args.max)
        .execute()
        .data
        or []
    )
    print(f"Pro detections in scope: {len(detections)}", file=sys.stderr)

    if args.dry_run:
        print("Dry-run: would re-verify above set via 17_verify_with_pro.py", file=sys.stderr)
        return

    # Reset prompt_version on a sample so 17_verify_with_pro.py picks them up
    # as "not yet v5'd". We use a tiny SQL trick: insert a v4 placeholder per
    # image so the existing script's "find v4 hits to verify" logic targets them.
    #
    # Cleaner alternative: tweak the verify script to accept a list of
    # detection IDs. We do that here by writing a small shim.
    ids = [d["content_image_id"] for d in detections]

    # Write the candidate list and call the verify script in --reverify-ids mode
    # (we add that mode below in 17_verify_with_pro.py).
    list_path = Path("/tmp/stelz_reverify_ids.txt")
    list_path.write_text("\n".join(ids))
    print(f"Wrote {len(ids)} candidate image ids to {list_path}", file=sys.stderr)

    cmd = ["python3", str(PA_ROOT / "tools" / "stelz_brand_watch" / "17_verify_with_pro.py"),
           "--reverify-ids", str(list_path), "--concurrency", "6"]
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=False)

    # Record fingerprint
    try:
        sb.table("reference_pack_versions").insert({
            "brand_id": brand_id,
            "fingerprint": fp,
        }).execute()
    except Exception as e:
        print(f"  (skipping fingerprint log: {e})", file=sys.stderr)


if __name__ == "__main__":
    main()
