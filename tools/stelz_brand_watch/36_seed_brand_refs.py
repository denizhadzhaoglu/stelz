#!/usr/bin/env python3
"""One-shot: upload all local STELZ reference images to Supabase Storage.

After this runs, detection scripts can load refs from Storage instead of
hardcoded local paths. New brands automatically get their own folder via
the upload UI on /account.html.

Usage:
    python3 tools/stelz_brand_watch/36_seed_brand_refs.py
    python3 tools/stelz_brand_watch/36_seed_brand_refs.py --brand stelz --force
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

REF_BUCKET = "brand-watch-thumbnails"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", default="stelz")
    p.add_argument("--force", action="store_true",
                   help="Overwrite if files already exist in Storage")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    local_dir = PA_ROOT / "projects" / "stelz-brand-watch" / "reference-images"
    if not local_dir.exists():
        sys.exit(f"No local references dir at {local_dir}")

    # Main reference packshots (sit in the root of reference-images/)
    main_files = [f for f in local_dir.iterdir()
                  if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
    # Training set lives under reference-images/training/
    train_dir = local_dir / "training"
    train_files = []
    if train_dir.exists():
        train_files = [f for f in train_dir.iterdir()
                       if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}]

    print(f"Uploading {len(main_files)} packshots + {len(train_files)} training images "
          f"for brand={args.brand}", file=sys.stderr)

    uploaded = 0
    skipped = 0
    for f in main_files:
        path = f"references/{args.brand}/{f.name}"
        try:
            sb.storage.from_(REF_BUCKET).upload(
                path=path, file=f.read_bytes(),
                file_options={"content-type": "image/jpeg",
                              "upsert": "true" if args.force else "false"},
            )
            uploaded += 1
        except Exception as e:
            if "already exists" in str(e).lower() or "Duplicate" in str(e):
                skipped += 1
            else:
                print(f"  {f.name}: {e}", file=sys.stderr)
    for f in train_files:
        path = f"references/{args.brand}/training/{f.name}"
        try:
            sb.storage.from_(REF_BUCKET).upload(
                path=path, file=f.read_bytes(),
                file_options={"content-type": "image/jpeg",
                              "upsert": "true" if args.force else "false"},
            )
            uploaded += 1
        except Exception as e:
            if "already exists" in str(e).lower() or "Duplicate" in str(e):
                skipped += 1
            else:
                print(f"  training/{f.name}: {e}", file=sys.stderr)

    print(f"\n=== SEED COMPLETE ===", file=sys.stderr)
    print(f"  Uploaded: {uploaded}", file=sys.stderr)
    print(f"  Skipped (already exist): {skipped}", file=sys.stderr)
    print(f"  Storage path: references/{args.brand}/", file=sys.stderr)


if __name__ == "__main__":
    main()
