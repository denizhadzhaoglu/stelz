#!/usr/bin/env python3
"""Stories actor smoke test — run this BEFORE trusting scan_stories in prod.

Why it exists: two earlier prototypes shipped against actors that returned
nothing, and nobody found out until the feature was already promised. The
handler is written so that swapping vendors touches exactly two functions
(_actor_payload and _normalize_item); this script tells you which vendor to
point them at, using real handles and real money (~$0.20).

What it proves, in order of importance:
  1. The actor returns items at all for accounts you can eyeball.
  2. Those items survive the leak filter (a reel filed as a story is worse
     than no story).
  3. The fields _normalize_item expects actually exist under those names.

Usage — note the interpreter: it imports the real handler, which needs the
Cloud Functions dependencies, so run it with the functions venv rather than the
system python:

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/60_stories_smoke_test.py anna bob carla

APIFY_API_TOKEN is read from the environment, or from firebase/functions/.env.

Pick handles you have just checked by hand on instagram.com — an empty result
for an account with no live story proves nothing either way.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

# Reuse the handler's own filter so this tests the real code path, not a copy.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "firebase" / "functions"))
from handlers.scan_stories import STORIES_ACTOR, _actor_payload, _normalize_item  # noqa: E402

FALLBACK_ACTOR = "louisdeconinck/instagram-story-details-scraper"
APIFY_BASE = "https://api.apify.com/v2/acts"


def run_actor(actor: str, handles: list[str], token: str) -> list[dict]:
    url = f"{APIFY_BASE}/{actor.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(
        url,
        params={"token": token, "timeout": 300, "memory": 1024},
        json=_actor_payload(handles),
        timeout=330,
    )
    if r.status_code == 404:
        print(f"  ✕ actor not found / not enabled on this account: {actor}")
        return []
    r.raise_for_status()
    return r.json()


def report(actor: str, handles: list[str], token: str) -> int:
    print(f"\n=== {actor}")
    try:
        items = run_actor(actor, handles, token)
    except Exception as e:
        print(f"  ✕ run failed: {e}")
        return 0
    print(f"  raw items: {len(items)}")
    if not items:
        print("  → no items. Either no live stories right now, or this vendor is dry.")
        return 0

    kept, leaked = [], 0
    for it in items:
        norm = _normalize_item(it)
        if norm is None:
            leaked += 1
        else:
            kept.append(norm)
    print(f"  stories after leak filter: {len(kept)}   rejected as non-story: {leaked}")

    # Field-name check: this is what silently breaks when a vendor renames.
    if kept:
        missing = [k for k in ("handle", "posted_at", "image_url") if not kept[0].get(k)]
        print(f"  first story: {json.dumps({k: str(v)[:60] for k, v in kept[0].items()}, indent=2)}")
        if missing:
            print(f"  ⚠ fields the handler wanted but did not get: {missing}")
            print("    → adjust _normalize_item in handlers/scan_stories.py")
    return len(kept)


def main() -> int:
    handles = [h.strip().lstrip("@").lower() for h in sys.argv[1:] if h.strip()]
    if not handles:
        print(__doc__)
        return 2
    token = os.getenv("APIFY_API_TOKEN")
    if not token:
        env = Path(__file__).resolve().parents[2] / "firebase" / "functions" / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("APIFY_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        print("APIFY_API_TOKEN not set (and not found in firebase/functions/.env)")
        return 2

    print(f"Testing {len(handles)} handles: {', '.join(handles)}")
    print("Check these accounts by hand first — an empty result for an account")
    print("with no live story tells you nothing about the vendor.")
    primary = report(STORIES_ACTOR, handles, token)
    fallback = report(FALLBACK_ACTOR, handles, token)

    print("\n=== verdict")
    if primary:
        print(f"  ✓ keep the primary actor ({STORIES_ACTOR})")
    elif fallback:
        print(f"  → switch STORIES_ACTOR to {FALLBACK_ACTOR} and re-check the field names")
    else:
        print("  ✕ neither vendor returned a story. Do NOT enable storiesAutoScan yet:")
        print("    re-run when you can confirm a live story by hand, and if it is still")
        print("    empty, the vendor's session pool is dry — try another actor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
