#!/usr/bin/env python3
"""Show the hashtag pool that would be seeded, and what it would cost.

No Firebase, no network — pure generation from lib/hashtags.py. Use it to
review the tag list before anyone deploys or re-seeds.

    python3 tools/eval/preview_hashtags.py
    python3 tools/eval/preview_hashtags.py --platform tiktok
    python3 tools/eval/preview_hashtags.py --diff      # vs the old hardcoded list
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / ".." / ".." / "firebase" / "functions"))

from lib import hashtags  # noqa: E402

# What was actually seeded before this change (handlers/bootstrap_brand.py).
OLD_IG = {"stelz", "drinkstelz", "stelzhardseltzer", "stelzhardlemonade",
          "stelzhardicedtea", "vrijmibo", "huisfeest", "koningsdag", "studentenleven"}
OLD_TT = {"stelz", "drinkstelz", "stelzhardseltzer", "stelzhardlemonade",
          "stelzhardicedtea", "vrijmibo", "carnaval2026", "nederland",
          "studentenleven", "hardseltzer"}

COST_PER_RESULT = 0.0023   # $2.30 / 1k — measured, see lib/usage.py
BOLD, DIM, GREEN, OFF = "\033[1m", "\033[2m", "\033[32m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="instagram", choices=["instagram", "tiktok"])
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--per-tag", type=int, default=500, help="global cap from the UI")
    a = ap.parse_args()

    pool = hashtags.stelz_pool(a.platform)
    old = OLD_IG if a.platform == "instagram" else OLD_TT

    by_family: dict[str, list[dict]] = {}
    for t in pool:
        by_family.setdefault(t["family"], []).append(t)

    print(f"{BOLD}{a.platform} — {len(pool)} tags (was {len(old)}){OFF}\n")
    worst = 0.0
    for fam, (prio, cap, why) in hashtags.FAMILIES.items():
        tags = by_family.get(fam, [])
        if not tags:
            continue
        eff = min(a.per_tag, cap) if cap else a.per_tag
        fam_cost = len(tags) * eff * COST_PER_RESULT
        worst += fam_cost
        print(f"{BOLD}{fam}{OFF}  {DIM}priority {prio} · cap {cap or a.per_tag}/tag "
              f"· {len(tags)} tags · worst case ${fam_cost:.2f}{OFF}")
        print(f"  {DIM}{why}{OFF}")
        for t in tags:
            new = f" {GREEN}NEW{OFF}" if t["tag"] not in old else ""
            print(f"    #{t['tag']}{new}")
        print()

    added = [t["tag"] for t in pool if t["tag"] not in old]
    removed = sorted(old - {t["tag"] for t in pool})

    print(f"{BOLD}{'=' * 58}{OFF}")
    print(f"added   {len(added)}")
    if removed:
        # Seeding writes with merge=True and never deletes, so these stay
        # active in Firestore — they are simply no longer in the generated
        # list. Deactivate them by hand if you actually want them gone.
        print(f"no longer generated ({len(removed)}, but NOT deleted on re-seed): "
              f"{', '.join(removed)}")
    print(f"\nWorst-case Apify cost for ONE full sweep: ${worst:.2f}")
    flat = len(pool) * a.per_tag * COST_PER_RESULT
    print(f"  ...vs ${flat:.2f} if every tag used the global perTag={a.per_tag}")
    print(f"  {DIM}Per-family caps save ${flat - worst:.2f} per sweep.{OFF}")
    print(f"\n{DIM}Worst case assumes every tag is saturated. Brand and typo tags")
    print("are nowhere near it — a hashtag nobody has used returns 0 results,")
    print(f"and Apify bills per result, so most of these cost nothing.{OFF}")

    if a.diff:
        print(f"\n{BOLD}NEW TAGS{OFF}")
        for t in added:
            print(f"  #{t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
