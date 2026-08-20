#!/usr/bin/env python3
"""Merge the three archives into one campaign fixture for the dev server.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/72_campaign_fixture.py

Reads .tmp/{stories,ig-posts,tiktok}-archive — index + verdicts — and writes
two files next to them:

    preview-campaign.json             CampaignItem[]   (lib/campaign.ts)
    preview-campaign-detections.json  DetectionRow[]   (lib/types.ts)

TWO FILES, NOT ONE JOINED LIST. Production reads posts and detections from two
Firestore collections and joins them in the browser; emitting a pre-joined list
here would exercise a code path that does not exist in production and would
hide the join bug class entirely — which is exactly the bug that shipped once
already (the page passed an empty detection array and every analysed item read
as "nog niet geanalyseerd").

Written to .tmp/, never to web/public: everything in public/ is copied into
dist/ and published by `firebase deploy --only hosting`, and these files hold
scraped content and signed CDN URLs. The dev server reaches them through the
serve-only middleware in web/vite.config.ts.

Media is served from the archives at /preview-media/<archive>/<file>, so the
page shows the exact bytes the analysis read rather than a re-fetched CDN copy
that may already have expired.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp"
OUT_ITEMS = TMP / "preview-campaign.json"
OUT_DETS = TMP / "preview-campaign-detections.json"

# (archive dir, id field, surface, platform)
SOURCES = [
    ("stories-archive", "story_id", "story", "instagram"),
    ("ig-posts-archive", "item_id", "post", "instagram"),
    ("tiktok-archive", "video_id", "tiktok", "tiktok"),
]


SEED = ROOT / "projects" / "stelz-brand-watch" / "web" / "src" / "data" / "lowlandsSeed.ts"


def identity_map() -> dict[str, str]:
    """TikTok handle -> the person's Instagram handle.

    Rein van Duivenboden is @rvdofficial on Instagram and @rinnavandoffoe on
    TikTok. Keyed on the raw handle, the campaign table shows him twice and
    reports 42 creators for a roster of 28 — which makes "wie leverde er niets"
    unanswerable, and that column is the reason the page exists.

    The Instagram handle wins because that is what creator ids and project
    rosters are already built from (splitCreatorId in lib/projects.ts).
    """
    if not SEED.exists():
        return {}
    tsv = SEED.read_text().split("`", 1)[1].rsplit("`", 1)[0]
    out: dict[str, str] = {}
    for line in tsv.strip().splitlines()[1:]:
        cols = [c.strip().lstrip("@").lower() for c in line.split("\t")]
        if len(cols) > 2 and cols[1] and cols[2] and cols[2] != "geen":
            out[cols[2]] = cols[1]
    return out


def read_jsonl(path: Path, key: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                row = json.loads(line)
            except Exception:
                continue
            k = row.get(key) or row.get("item_id") or row.get("story_id")
            if k:
                out[str(k)] = row
    return out


def media_url(archive: str, filename: str | None) -> str | None:
    return f"/preview-media/{archive}/{filename}" if filename else None


def item_id(surface: str, raw_id: str) -> str:
    """The id the frontend joins on.

    No extra underscore-separated segment: lib/types.parentPostKey groups by the
    first TWO segments of a post id, so "instagram_story_123" parses as post
    "story" and every story collapses into one row. That bug shipped once; the
    shape is load-bearing, not cosmetic.
    """
    return {"story": f"instagram_story{raw_id}",
            "post": f"instagram_post{raw_id}",
            "tiktok": f"tiktok_video{raw_id}"}[surface]


def to_item(e: dict, v: dict | None, archive: str, surface: str, platform: str,
            ids: dict[str, str]) -> dict:
    raw_id = str(e.get("story_id") or e.get("item_id") or e.get("video_id"))
    is_video = bool(e.get("video_file")) or e.get("media_type") == "video"
    return {
        "itemId": item_id(surface, raw_id),
        "platform": platform,
        "surface": surface,
        # The PERSON, not the account. See identity_map.
        "creatorHandle": ids.get((e.get("handle") or "").lower(),
                                 (e.get("handle") or "").lower()),
        "platformHandle": (e.get("handle") or "").lower(),
        "url": e.get("url") or (
            f"https://www.instagram.com/stories/{e.get('handle')}/{raw_id}/"
            if surface == "story" else None),
        "coverUrl": media_url(archive, e.get("image_file")),
        "videoUrl": media_url(archive, e.get("video_file")),
        "mediaType": "video" if is_video else "image",
        "postedAt": e.get("posted_at"),
        "caption": e.get("caption") or None,
        "hashtags": e.get("hashtags") or [],
        "mentions": e.get("mentions") or [],
        "videoDuration": e.get("duration"),
        # None, not 0, where the surface publishes no such figure. A story has
        # no view count in existence; a photo post has no play count. Zero would
        # read as "nobody watched", which is a claim, not a blank.
        "views": e.get("play_count") if surface == "tiktok" else e.get("views_count"),
        "likes": e.get("digg_count") if surface == "tiktok" else e.get("likes_count"),
        "comments": e.get("comment_count") if surface == "tiktok" else e.get("comments_count"),
        "shares": e.get("share_count") if surface == "tiktok" else None,
        "pollVotes": e.get("poll_votes") if surface == "story" else None,
        "isPaidPartnership": bool(e.get("is_ad") or e.get("is_sponsored")
                                  or e.get("is_paid_partnership")),
    }


def to_detection(e: dict, v: dict, archive: str, surface: str, platform: str,
                 ids: dict[str, str]) -> dict:
    raw_id = str(e.get("story_id") or e.get("item_id") or e.get("video_id"))
    return {
        "detection_id": f"preview_{surface}_{raw_id}",
        "creator_id": None,
        "creator_handle": ids.get((e.get("handle") or "").lower(),
                                  (e.get("handle") or "").lower()),
        "creator_category": None,
        "platform": platform,
        "product_line": v.get("product_line"),
        "confidence": v.get("confidence"),
        "size_in_frame": v.get("size_in_frame"),
        "is_primary_subject": v.get("is_primary_subject"),
        "image_url": media_url(archive, e.get("image_file")),
        "stored_path": None,
        "post_url": e.get("url"),
        "post_caption": e.get("caption") or None,
        "posted_at": e.get("posted_at"),
        "likes_count": None, "comments_count": None, "views_count": None,
        "follower_count": e.get("follower_count"),
        "creator_tier": "tier_2",
        "verified": e.get("verified"),
        "context": v.get("context"),
        "post_hashtags": e.get("hashtags") or [],
        "post_mentions": e.get("mentions") or [],
        "music": None,
        "extras": None,
        "content_type": "story" if surface == "story" else "video",
        "expires_at": e.get("expires_at"),
        "frame_idx": None,
        "frames_judged": v.get("frames_judged"),
        "near_miss": bool(v.get("near_miss")),
        "near_miss_reason": v.get("near_miss_reason"),
        "cover_only": bool(v.get("cover_only")),
        "post_id": item_id(surface, raw_id),
        "surface_type": v.get("surface_type"),
        "visible_text": v.get("visible_text"),
        "false_positive_risk": v.get("false_positive_risk"),
        "people_count": v.get("people_count"),
        "setting": v.get("setting"),
        "activity": v.get("activity"),
        "gate": v.get("gate"),
        "verify_verdict": v.get("verify_verdict"),
        "verify_brand": v.get("verify_brand"),
        "verify_reason": v.get("verify_reason"),
        # Signage / merchandise / clothing, when the wordmark was not on a can.
        "verify_placement": v.get("verify_placement"),
        # The resolution this verdict was reached at, and whether the DEPLOYED
        # function — which downscales every image to 512px — still finds it.
        # False here means the dashboard is showing a sighting the live backend
        # would currently miss, which is a fact about the deploy, not about the
        # photo, and belongs on screen rather than in a note somewhere.
        "max_dim": v.get("max_dim"),
        "found_at_prod_res": v.get("found_at_prod_res"),
        "sentiment": None, "sentiment_score": None, "sentiment_rationale": None,
        "brand_id": "stelz",
        "detected": bool(v.get("detected")),
        "is_false_positive": None,
    }


def main() -> int:
    items: list[dict] = []
    dets: list[dict] = []
    report: list[str] = []
    ids = identity_map()

    for archive, id_field, surface, platform in SOURCES:
        base = TMP / archive
        index = read_jsonl(base / "index.jsonl", id_field)
        verdicts = read_jsonl(base / "verdicts.jsonl", "item_id")
        hits = near = 0
        for raw_id, e in index.items():
            v = verdicts.get(raw_id)
            items.append(to_item(e, v, archive, surface, platform, ids))
            # Only judged items get a detection row. An absent row is what makes
            # the UI say "nog niet geanalyseerd" instead of inventing a miss.
            if v is not None:
                dets.append(to_detection(e, v, archive, surface, platform, ids))
                hits += bool(v.get("detected"))
                near += bool(v.get("near_miss"))
        report.append(f"  {surface:<7} {len(index):>4} items · {len(verdicts):>4} judged · "
                      f"{hits} with Stëlz · {near} near")

    if not items:
        print("No archives found under .tmp/ — harvest first "
              "(62_stories_archive.py, 70_tiktok_archive.py, 71_ig_posts_archive.py)")
        return 1

    OUT_ITEMS.write_text(json.dumps(items, indent=1))
    OUT_DETS.write_text(json.dumps(dets, indent=1))

    print("\n".join(report))
    handles = sorted({i["creatorHandle"] for i in items if i["creatorHandle"]})
    tt_views = sum(i["views"] or 0 for i in items if i["surface"] == "tiktok")
    accounts = sorted({i["platformHandle"] for i in items if i["platformHandle"]})
    print(f"\n  {len(items)} items · {len(dets)} judged · {len(handles)} people "
          f"across {len(accounts)} accounts")
    print(f"  TikTok views: {tt_views:,}  (the only published viewing figure here)")
    print(f"  wrote {OUT_ITEMS.relative_to(ROOT)}")
    print(f"        {OUT_DETS.relative_to(ROOT)}")
    print("\n  open http://localhost:5180/campagne?preview=campaign")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
