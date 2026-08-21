#!/usr/bin/env python3
"""Snapshot Instagram stories to disk before Instagram deletes them.

A story is gone 24 hours after it is posted, and the image behind it is a
signed CDN link that dies sooner than that. Until scan_stories is deployed
there is nothing capturing them, so every hour of a running campaign is
permanently lost — and Lowlands is running right now.

This needs no deploy and no Firebase credentials: it talks to Apify and to the
CDN, and writes to .tmp/stories-archive/ (already gitignored). 63_stories_
backfill.py replays the archive into Firestore once the deploy lands.

    # free: re-read the dataset the last run already produced
    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/62_stories_archive.py --from-last-run

    # ~$0.18: fresh sweep of the roster
    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/62_stories_archive.py --handles anna bob
    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/62_stories_archive.py --event lowlands-2026

Re-runnable and idempotent: stories already archived are skipped by id, so
running it every few hours through a festival weekend accumulates rather than
duplicates. Images are fetched once; a story whose image already downloaded is
never re-fetched even if a later sweep returns it again.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firebase" / "functions"))
from handlers.scan_stories import STORIES_ACTOR, _actor_payload, _normalize_item  # noqa: E402

APIFY = "https://api.apify.com/v2"

_spec = importlib.util.spec_from_file_location(
    "_events", Path(__file__).with_name("_events.py"))
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

# Assigned in main() from --event. See the note in 70_tiktok_archive.py.
P: "E.Paths" = None  # type: ignore[assignment]


def token() -> str | None:
    import os
    t = os.getenv("APIFY_API_TOKEN")
    if t:
        return t
    env = ROOT / "firebase" / "functions" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("APIFY_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def fetch_items(tok: str, handles: list[str] | None, from_last_run: bool) -> list[dict]:
    act = STORIES_ACTOR.replace("/", "~")
    if from_last_run:
        runs = requests.get(f"{APIFY}/acts/{act}/runs",
                            params={"token": tok, "limit": 1, "desc": "true"}, timeout=60)
        runs.raise_for_status()
        items = runs.json().get("data", {}).get("items", [])
        if not items:
            print("  no previous run to read")
            return []
        run = items[0]
        print(f"  reusing run {run.get('id')} ({run.get('status')}, started {run.get('startedAt')}) — free")
        ds = run.get("defaultDatasetId")
        if not ds:
            return []
        r = requests.get(f"{APIFY}/datasets/{ds}/items", params={"token": tok}, timeout=180)
        r.raise_for_status()
        return r.json()

    print(f"  starting a fresh run for {len(handles or [])} handles (~$0.10 + $0.003/handle)")
    r = requests.post(
        f"{APIFY}/acts/{act}/run-sync-get-dataset-items",
        params={"token": tok, "timeout": 300, "memory": 1024},
        json=_actor_payload(handles or []),
        timeout=330,
    )
    r.raise_for_status()
    return r.json()


def known_ids() -> set[str]:
    if not P.index.exists():
        return set()
    out = set()
    for line in P.index.read_text().splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["story_id"])
            except Exception:
                continue
    return out


def download(url: str, dest: Path) -> int:
    """Bytes written, or 0. A dead link is expected, not exceptional — these
    are signed URLs and some are already stale by the time we get here."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest.stat().st_size
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"    ✕ {dest.name}: {str(e)[:80]}")
        return 0
    dest.write_bytes(r.content)
    return len(r.content)


def main() -> int:
    global P
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", default="lowlands-2026", choices=E.available(),
                    help="which event's roster and archive (default lowlands-2026)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--from-last-run", action="store_true",
                     help="re-read the dataset of the most recent run (free, no new scrape)")
    src.add_argument("--handles", nargs="+", metavar="HANDLE",
                     help="sweep these instead of the event roster")
    ap.add_argument("--no-video", action="store_true",
                    help="skip story videos; covers are still archived")
    args = ap.parse_args()

    tok = token()
    if not tok:
        print("APIFY_API_TOKEN not set (and not in firebase/functions/.env)")
        return 2

    ev = E.load(args.event)
    P = E.paths(ev, "stories")
    handles = None if args.from_last_run else (args.handles or E.roster_ig(ev))
    if handles:
        handles = [h.strip().lstrip("@").lower() for h in handles if h.strip()]
    print(f"  {ev['name']}")

    P.mkdirs()

    items = fetch_items(tok, handles, args.from_last_run)
    print(f"  raw items: {len(items)}")
    if not items:
        return 1

    seen = known_ids()
    added, skipped, leaked, bytes_saved, dead = 0, 0, 0, 0, 0
    with P.index.open("a") as idx:
        for item in items:
            norm = _normalize_item(item)
            if norm is None:
                leaked += 1
                continue
            sid = norm["story_id"]
            if sid in seen:
                skipped += 1
                continue

            # The raw payload is kept verbatim: the backfill re-normalises with
            # whatever _normalize_item looks like THEN, so a later fix to the
            # parser can be applied to stories already archived. A pre-digested
            # archive would freeze today's bugs into the record.
            (P.raw / f"{sid}.json").write_text(json.dumps(item))

            img = P.media / f"{sid}.jpg"
            n = download(norm["image_url"], img) if norm["image_url"] else 0
            if not n:
                dead += 1
            bytes_saved += n
            vid_name = None
            if norm["video_url"] and not args.no_video:
                vid = P.media / f"{sid}.mp4"
                vn = download(norm["video_url"], vid)
                if vn:
                    bytes_saved += vn
                    vid_name = vid.name

            idx.write(json.dumps({
                "story_id": sid,
                "handle": norm["handle"],
                "posted_at": norm["posted_at"].isoformat() if norm["posted_at"] else None,
                "expires_at": norm["expires_at"].isoformat() if norm["expires_at"] else None,
                "image_file": img.name if n else None,
                "video_file": vid_name,
                "raw_file": f"{sid}.json",
                "event": ev["id"],
            }) + "\n")
            seen.add(sid)
            added += 1

    total = len(known_ids())
    print(f"\n  archived {added} new · {skipped} already had · {leaked} not stories")
    if dead:
        print(f"  {dead} image link(s) already dead — metadata kept, picture lost")
    print(f"  +{bytes_saved / 1e6:.1f} MB · {total} stories in {P.label()}")
    print("\n  Re-run every few hours while the campaign runs; already-archived")
    print("  stories are skipped. Load into the tool with 63_stories_backfill.py")
    print("  once api_ingest_stories is deployed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
