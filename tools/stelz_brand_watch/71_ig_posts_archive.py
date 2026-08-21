#!/usr/bin/env python3
"""Archive the roster's Instagram FEED posts — carousels, photos and reels.

The stories archive (62) covers the 24-hour surface and nothing else. A can in
a carousel's third slide, or in a reel, is invisible to this tool today: the
creator-scan that would find it runs in a Cloud Function that is not deployed.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/71_ig_posts_archive.py --roster lowlands
        ... --per-handle 12        # posts per creator (default 12)
        ... --since 2026-08-01     # ignore anything older
        ... --no-video             # covers and stills only

COST: apify/instagram-scraper bills PER RESULT at $0.0023 — 28 handles x 12
posts = 336 results = $0.77. Unlike the TikTok actor this one is not free, so
--per-handle is a real budget lever and the estimate is printed before the run
starts, not after.

EVERY SLIDE, NOT JUST THE FIRST. A carousel arrives as one item with
`childPosts`; taking only `displayUrl` would judge a ten-slide post by slide
one. Each child is archived as its own row with a `slot` index, which is also
how the backend persists them (scan_hashtags._persist_sidecar_child) — so the
post id keeps the two-segment shape the frontend groups on.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firebase" / "functions"))

ARCHIVE = ROOT / ".tmp" / "ig-posts-archive"
INDEX = ARCHIVE / "index.jsonl"
MEDIA = ARCHIVE / "media"
RAW = ARCHIVE / "raw"

APIFY = "https://api.apify.com/v2"
ACTOR = "apify/instagram-scraper"
COST_PER_RESULT = 0.0023
ROSTERS = {"lowlands": ROOT / "projects" / "stelz-brand-watch" / "web" / "src" / "data" / "lowlandsSeed.ts"}
BATCH = 10   # the cap scrape_profile_ig documents; large batches time out


def token() -> str | None:
    t = os.getenv("APIFY_API_TOKEN")
    if t:
        return t
    env = ROOT / "firebase" / "functions" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("APIFY_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def roster_handles(name: str) -> list[str]:
    """Instagram handles — column 2, same parse as 62_stories_archive.py."""
    tsv = ROSTERS[name].read_text().split("`", 1)[1].rsplit("`", 1)[0]
    rows = [l.split("\t") for l in tsv.strip().splitlines()[1:] if l.strip()]
    out = []
    for r in rows:
        if len(r) > 1:
            h = r[1].strip().lstrip("@").lower()
            if h and h != "geen":
                out.append(h)
    return out


def scrape(handles: list[str], per_handle: int, tok: str) -> list[dict]:
    urls = [f"https://www.instagram.com/{h}/" for h in handles]
    r = requests.post(
        f"{APIFY}/acts/{ACTOR.replace('/', '~')}/run-sync-get-dataset-items",
        params={"token": tok, "timeout": 300, "memory": 1024},
        json={"directUrls": urls, "resultsType": "posts", "resultsLimit": per_handle,
              "addParentData": False, "searchType": "user", "searchLimit": 1},
        timeout=330,
    )
    r.raise_for_status()
    items = r.json()
    return items if isinstance(items, list) else []


def rows_for(item: dict) -> list[dict]:
    """One post -> one row per image/video to analyse.

    A carousel yields one row per child. The id keeps the shape the frontend's
    parentPostKey expects: the slot goes in a field, never as a third
    underscore-separated segment of the id.
    """
    handle = (item.get("ownerUsername") or "").strip().lower()
    code = str(item.get("shortCode") or item.get("id") or "")
    if not handle or not code:
        return []
    base = {
        "handle": handle,
        "short_code": code,
        "url": item.get("url") or f"https://www.instagram.com/p/{code}/",
        "posted_at": item.get("timestamp"),
        "caption": item.get("caption") or "",
        "hashtags": item.get("hashtags") or [],
        "mentions": item.get("mentions") or [],
        "likes_count": item.get("likesCount") or 0,
        "comments_count": item.get("commentsCount") or 0,
        # Reels report plays; a photo post reports nothing. Zero would read as
        # "nobody watched" for a surface that has no such number at all.
        "views_count": item.get("videoViewCount") or None,
        "full_name": item.get("ownerFullName"),
        "is_sponsored": bool(item.get("isSponsored")),
    }
    children = item.get("childPosts") or []
    out: list[dict] = []
    if children:
        for i, ch in enumerate(children):
            vurl = ch.get("videoUrl")
            out.append({**base, "item_id": f"{code}s{i}", "slot": i,
                        "slots": len(children),
                        "media_type": "video" if vurl else "image",
                        "cover_url": ch.get("displayUrl"), "video_url": vurl})
    else:
        vurl = item.get("videoUrl")
        out.append({**base, "item_id": code, "slot": 0, "slots": 1,
                    "media_type": "video" if vurl else "image",
                    "cover_url": item.get("displayUrl"), "video_url": vurl})
    return [r for r in out if r.get("cover_url") or r.get("video_url")]


def download(url: str | None, dest: Path) -> int:
    if not url:
        return 0
    if dest.exists() and dest.stat().st_size > 0:
        return dest.stat().st_size
    try:
        r = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"    ✕ {dest.name}: {str(e)[:70]}")
        return 0
    dest.write_bytes(r.content)
    return len(r.content)


def known_ids() -> set[str]:
    if not INDEX.exists():
        return set()
    out = set()
    for line in INDEX.read_text().splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["item_id"])
            except Exception:
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--roster", choices=sorted(ROSTERS))
    src.add_argument("--handles", nargs="+", metavar="HANDLE")
    ap.add_argument("--per-handle", type=int, default=12)
    ap.add_argument("--since", help="ISO date; skip posts older than this")
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()

    tok = token()
    if not tok:
        print("APIFY_API_TOKEN not set (and not in firebase/functions/.env)")
        return 2

    handles = [h.lstrip("@").lower() for h in (args.handles or roster_handles(args.roster))]
    est = len(handles) * args.per_handle * COST_PER_RESULT
    print(f"{len(handles)} handles x {args.per_handle} posts = "
          f"{len(handles) * args.per_handle} results ≈ ${est:.2f} at Apify\n")

    for d in (ARCHIVE, MEDIA, RAW):
        d.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    for i in range(0, len(handles), BATCH):
        batch = handles[i:i + BATCH]
        print(f"  batch {i // BATCH + 1}: {', '.join(batch)}")
        try:
            got = scrape(batch, args.per_handle, tok)
        except Exception as e:
            print(f"    ✕ {str(e)[:100]}")
            continue
        print(f"    {len(got)} posts")
        items.extend(got)

    cutoff = None
    if args.since:
        cutoff = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc)

    already = known_ids()
    added = skipped = old = 0
    bytes_saved = 0
    with INDEX.open("a") as idx:
        for item in items:
            rows = rows_for(item)
            if not rows:
                continue
            if cutoff and rows[0].get("posted_at"):
                try:
                    when = dt.datetime.fromisoformat(
                        rows[0]["posted_at"].replace("Z", "+00:00"))
                    if when < cutoff:
                        old += 1
                        continue
                except Exception:
                    pass
            code = rows[0]["short_code"]
            (RAW / f"{code}.json").write_text(json.dumps(item, indent=1))
            for e in rows:
                if e["item_id"] in already:
                    skipped += 1
                    continue
                iid = e["item_id"]
                e["raw_file"] = f"{code}.json"
                e["image_file"] = None
                n = download(e["cover_url"], MEDIA / f"{iid}.jpg")
                if n:
                    e["image_file"] = f"{iid}.jpg"
                    bytes_saved += n
                e["video_file"] = None
                e["video_unavailable"] = False
                if e["media_type"] == "video" and not args.no_video:
                    n = download(e["video_url"], MEDIA / f"{iid}.mp4")
                    if n:
                        e["video_file"] = f"{iid}.mp4"
                        bytes_saved += n
                    else:
                        e["video_unavailable"] = True
                if not e["image_file"] and not e["video_file"]:
                    continue
                idx.write(json.dumps(e) + "\n")
                already.add(iid)
                added += 1

    print(f"\n  +{added} new · {skipped} already archived · {old} older than --since")
    print(f"  +{bytes_saved / 1e6:.1f} MB · {len(known_ids())} in {ARCHIVE.relative_to(ROOT)}")
    print(f"  Apify: {len(items)} results ≈ ${len(items) * COST_PER_RESULT:.2f}")
    print("\n  Next: 74_tiktok_analyse.py --archive ig-posts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
