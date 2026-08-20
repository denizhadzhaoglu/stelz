#!/usr/bin/env python3
"""Turn the LAST stories actor run into a local UI preview fixture.

Why this exists: the stories UI cannot be seen working until scan_stories is
deployed, and deploying needs credentials this machine does not have. This
closes that gap without waiting and without spending again — it re-reads the
dataset the previous run already produced, which is a free API read, and emits
the rows in the shape the frontend expects.

It starts NO actor run. If you want fresh stories, run 60_stories_smoke_test.py
first (that one costs money) and then run this.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/61_stories_preview_fixture.py

Writes projects/stelz-brand-watch/web/public/preview-stories.json, which the
dev server serves at /preview-stories.json for `?preview=stories`. The file is
gitignored: it holds signed Instagram CDN URLs that expire within hours, so a
committed copy would be a snapshot of broken images.

Note what this proves and what it does not. It exercises the real
_normalize_item, the real expiry maths and the real rendering path. It does NOT
exercise the Firestore write or the Gemini detect fan-out — every row comes out
detected=null, because nothing has looked at these images yet.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "firebase" / "functions"))
from handlers.scan_stories import STORIES_ACTOR, STORY_TTL_HOURS, _normalize_item  # noqa: E402

PUBLIC = ROOT / "projects" / "stelz-brand-watch" / "web" / "public"
OUT = PUBLIC / "preview-stories.json"          # DetectionRow[] — the strip
OUT_POSTS = PUBLIC / "preview-story-posts.json"  # StoryPost[] — the /stories page
APIFY = "https://api.apify.com/v2"


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


def last_dataset_items(actor: str, tok: str) -> list[dict]:
    """Items from the most recent finished run. Free — no run is started."""
    runs = requests.get(
        f"{APIFY}/acts/{actor.replace('/', '~')}/runs",
        params={"token": tok, "limit": 1, "desc": "true"},
        timeout=60,
    )
    runs.raise_for_status()
    items = runs.json().get("data", {}).get("items", [])
    if not items:
        return []
    run = items[0]
    print(f"  run {run.get('id')} · {run.get('status')} · started {run.get('startedAt')}")
    ds = run.get("defaultDatasetId")
    if not ds:
        return []
    out = requests.get(f"{APIFY}/datasets/{ds}/items", params={"token": tok}, timeout=120)
    out.raise_for_status()
    return out.json()


def to_row(norm: dict, idx: int) -> dict:
    """One normalized story -> one DetectionRow, matching lib/types.ts.

    Every field the type declares is present. A row missing a key the UI reads
    optionally is fine; a row missing one it reads unconditionally crashes the
    page, and a preview that crashes teaches you nothing.
    """
    posted = norm["posted_at"] or dt.datetime.now(dt.timezone.utc)
    # Same precedence as the handler: Instagram's stated expiry first.
    expires = norm.get("expires_at") or posted + dt.timedelta(hours=STORY_TTL_HOURS)
    handle = norm["handle"]
    story_id = norm["story_id"]
    return {
        "detection_id": f"preview_{story_id}_{idx}",
        "creator_id": None,
        "creator_handle": handle,
        "creator_category": None,
        "platform": "instagram",
        "product_line": None,
        # Nothing has analysed these images, so there is no confidence to state
        # and no verdict to claim. detected=null renders as "captured, not yet
        # judged" rather than as a hit we did not earn.
        "confidence": None,
        "size_in_frame": None,
        "is_primary_subject": None,
        "image_url": norm["image_url"],
        "stored_path": None,
        "post_url": f"https://www.instagram.com/stories/{handle}/{story_id}/",
        "post_caption": None,
        "posted_at": posted.isoformat(),
        "likes_count": None,
        "comments_count": None,
        "views_count": None,
        "follower_count": None,
        "creator_tier": "tier_2",
        "verified": None,
        "context": None,
        "post_hashtags": norm.get("hashtags") or [],
        "post_mentions": norm.get("mentions") or [],
        "music": None,
        "extras": None,
        "content_type": "story",
        "expires_at": expires.isoformat(),
        "frame_idx": None,
        "post_id": f"instagram_story{story_id}",
        "surface_type": None,
        "visible_text": None,
        "false_positive_risk": None,
        "people_count": None,
        "setting": None,
        "activity": None,
        "gate": None,
        "verify_verdict": None,
        "verify_brand": None,
        "verify_reason": None,
        "sentiment": None,
        "sentiment_score": None,
        "sentiment_rationale": None,
        "brand_id": "stelz",
        "detected": None,
        "is_false_positive": None,
    }


def to_post(norm: dict) -> dict:
    """One normalized story -> one StoryPost, matching lib/firestore.ts.

    The /stories page is driven by POSTS, not detections, so the preview has to
    supply posts or it would exercise a different code path than production.
    No detections accompany them, which is correct: nothing has analysed these,
    and the page renders every row as "nog niet geanalyseerd".
    """
    posted = norm["posted_at"] or dt.datetime.now(dt.timezone.utc)
    expires = norm.get("expires_at") or posted + dt.timedelta(hours=STORY_TTL_HOURS)
    story_id = norm["story_id"]
    return {
        "postId": f"instagram_story{story_id}",
        "creatorHandle": norm["handle"],
        "creatorTier": "tier_2",
        "url": f"https://www.instagram.com/stories/{norm['handle']}/{story_id}/",
        "coverUrl": norm["image_url"],
        "videoUrl": norm["video_url"],
        "mediaType": norm["media_type"],
        "videoDuration": norm["video_duration"],
        "postedAt": posted.isoformat(),
        "postedAtEstimated": norm["posted_at"] is None,
        "expiresAt": expires.isoformat(),
        "hashtags": norm["hashtags"],
        "mentions": norm["mentions"],
        "pollVotes": norm["poll_votes"],
        "pollCount": norm["poll_count"],
        "pollQuestions": norm["poll_questions"],
        "linkUrls": norm["link_urls"],
        "music": norm["music"],
        "isPaidPartnership": norm["is_paid_partnership"],
    }


def main() -> int:
    tok = token()
    if not tok:
        print("APIFY_API_TOKEN not set (and not in firebase/functions/.env)")
        return 2

    print(f"Reading the last run of {STORIES_ACTOR} (no new run, no cost)")
    try:
        items = last_dataset_items(STORIES_ACTOR, tok)
    except Exception as e:
        print(f"  ✕ could not read the dataset: {e}")
        return 1
    print(f"  raw items: {len(items)}")

    rows, posts, leaked = [], [], 0
    for i, item in enumerate(items):
        norm = _normalize_item(item)
        if norm is None:
            leaked += 1
            continue
        rows.append(to_row(norm, i))
        posts.append(to_post(norm))
    print(f"  stories after leak filter: {len(rows)}   rejected as non-story: {leaked}")

    if not rows:
        print("  → nothing to preview. Run 60_stories_smoke_test.py first.")
        return 1

    handles = sorted({r["creator_handle"] for r in rows})
    print(f"  from {len(handles)} accounts: {', '.join(handles)}")
    OUT.write_text(json.dumps(rows, indent=1))
    OUT_POSTS.write_text(json.dumps(posts, indent=1))
    polls = sum(p["pollVotes"] for p in posts)
    print(f"\n  wrote {OUT.relative_to(ROOT)} and {OUT_POSTS.relative_to(ROOT)}")
    print(f"  {sum(1 for p in posts if p['mediaType'] == 'video')} video · "
          f"{polls:,} poll votes · {sum(len(p['mentions']) for p in posts)} mentions")
    print("  open http://localhost:5180/stories?preview=stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
