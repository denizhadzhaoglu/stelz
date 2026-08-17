#!/usr/bin/env python3
"""One-off: bootstrap the Stelz brand document in Firestore.

Run locally with:
  GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json python firebase/seed_brand.py

Creates:
  /brands/stelz
  /brands/stelz/hashtagPool/{tag}   (initial set)
  /brands/stelz/members/<your-uid>  (optional, pass --uid)
"""
import argparse
import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "functions"))

from lib import fs, hashtags  # noqa: E402
from google.cloud.firestore import SERVER_TIMESTAMP  # noqa: E402

BRAND_ID = "stelz"

BRAND_DOC = {
    "slug": "stelz",
    "name": "Stelz",
    "active": True,
    "productLines": {
        "hard_lemonade": "Hard Lemonade",
        "hard_seltzer": "Hard Seltzer",
        "hard_iced_tea": "Hard Iced Tea",
        "mixed_classics": "Mixed Classics",
        "logo_only": "Logo only",
        "zero_zero": "Zero-zero",
    },
    "createdAt": SERVER_TIMESTAMP,
}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uid", help="Firebase Auth UID to grant brand membership")
    args = p.parse_args()

    fs.brand_doc(BRAND_ID).set(BRAND_DOC, merge=True)
    print(f"✓ brand {BRAND_ID} seeded")

    # Single source of truth: lib/hashtags. This file and
    # handlers/bootstrap_brand.py used to keep separate hand-written lists that
    # had already drifted (10 TikTok tags there, 3 here), and neither carried a
    # single misspelling of the brand name.
    total = 0
    for platform in ("instagram", "tiktok"):
        for e in hashtags.stelz_pool(platform):
            fs.hashtag_pool_col(BRAND_ID).document(f"{platform}_{e['tag']}").set({
                "tag": e["tag"],
                "platform": platform,
                "priority": e["priority"],
                "family": e["family"],
                # Per-tag Apify ceiling. Apify bills per RESULT, so without
                # this a ~0%-yield lifestyle tag costs the same as #stelz.
                "maxResults": e["maxResults"],
                "active": True,
            }, merge=True)
            total += 1
    print(f"✓ {total} hashtags seeded")

    if args.uid:
        fs.brand_doc(BRAND_ID).collection("members").document(args.uid).set({
            "role": "owner",
            "addedAt": SERVER_TIMESTAMP,
        }, merge=True)
        print(f"✓ added {args.uid} as owner of {BRAND_ID}")
    else:
        print("(no --uid given — security rules will block reads until you add a member)")


if __name__ == "__main__":
    main()
