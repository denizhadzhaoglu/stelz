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

from lib import fs  # noqa: E402
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

HASHTAGS_IG = [
    ("stelz", 10),
    ("drinkstelz", 9),
    ("stelzhardseltzer", 9),
    ("stelzhardlemonade", 9),
    ("stelzhardicedtea", 9),
    ("vrijmibo", 6),
    ("huisfeest", 5),
    ("koningsdag", 5),
    ("studentenleven", 4),
]

HASHTAGS_TIKTOK = [
    ("stelz", 10),
    ("drinkstelz", 9),
    ("vrijmibo", 5),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--uid", help="Firebase Auth UID to grant brand membership")
    args = p.parse_args()

    fs.brand_doc(BRAND_ID).set(BRAND_DOC, merge=True)
    print(f"✓ brand {BRAND_ID} seeded")

    for tag, prio in HASHTAGS_IG:
        fs.hashtag_pool_col(BRAND_ID).document(f"instagram_{tag}").set({
            "tag": tag, "platform": "instagram", "priority": prio, "active": True,
        }, merge=True)
    for tag, prio in HASHTAGS_TIKTOK:
        fs.hashtag_pool_col(BRAND_ID).document(f"tiktok_{tag}").set({
            "tag": tag, "platform": "tiktok", "priority": prio, "active": True,
        }, merge=True)
    print(f"✓ {len(HASHTAGS_IG) + len(HASHTAGS_TIKTOK)} hashtags seeded")

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
