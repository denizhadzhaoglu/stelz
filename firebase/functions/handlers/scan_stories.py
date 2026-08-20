"""Instagram Stories capture.

Stories are where most in-the-moment brand mentions live, and they are gone in
24 hours. Two earlier prototypes (tools/stelz_brand_watch/44 and /49) never
produced a story in production, and the research explains why: the official
`apify/instagram-scraper` has NO stories support at all — its resultsType
accepts posts/reels/comments/mentions/details, so `resultsType: "stories"` was
never going to return one. The prototypes blamed the missing session cookie.

Active stories ARE login-gated at Instagram's own API. The way out is not to
supply a cookie — a session cookie is a live account credential that expires,
needs manual re-harvesting, and puts a real person's account at risk of a
permanent ban. Instead this uses an actor that runs its own session pool: the
account risk sits with the vendor, and nothing here holds a credential.

Cadence: a story lives 24h, so ANY polling interval <= 24h captures every one
of them. The scheduler runs this every 6h — 4x redundancy, so a story survives
three consecutive failed runs and is still caught. Polling more often buys no
extra coverage, only cost.

An empty result is the NORMAL case: most creators have no active story at any
given moment. It is reported as zero stories with status ok, never as an error.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from google.cloud import pubsub_v1
from google.cloud.firestore import SERVER_TIMESTAMP

from lib import apify, fs, usage

log = logging.getLogger(__name__)

PROJECT_ID = "brand-audit-4b2cc"
DETECT_IMAGE_TOPIC = "detect-image"
DETECT_VIDEO_TOPIC = "detect-video"

# No-login actor: it maintains its own Instagram sessions, so we hold no
# credential and no account of ours can be banned for this.
# $0.099 per run + $3/1k usernames — batch every handle into ONE run.
STORIES_ACTOR = "datavoyantlab/advanced-instagram-stories-scraper"

STORY_TTL_HOURS = 24
DEFAULT_MAX_HANDLES = 60


def _actor_payload(handles: list[str]) -> dict[str, Any]:
    """Actor input. Swap point 1 — changing vendor means changing this and
    _normalize_item, nothing else."""
    return {"usernames": handles}


def _normalize_item(item: dict) -> dict | None:
    """Actor output -> our shape, or None when the item is not a story.

    Swap point 2. The leak filter is carried over verbatim from the 49_
    prototype: stories endpoints leak reels and feed posts into their output,
    and a reel silently filed as a story corrupts the "caught before it
    disappeared" claim the feature is sold on.
    """
    # A real story has NO shortCode (posts/reels do) and a numeric id.
    if item.get("shortCode") or item.get("type") in ("Sidecar",) \
            or item.get("productType") in ("clips", "feed"):
        return None
    story_id = item.get("id") or item.get("storyId") or item.get("mediaId")
    if not story_id or not str(story_id).isdigit():
        return None

    handle = (
        item.get("ownerUsername") or item.get("username") or item.get("owner_username") or ""
    ).strip().lower().lstrip("@")

    posted_at: dt.datetime | None = None
    ts = item.get("takenAt") or item.get("takenAtTimestamp") or item.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 1e9:
        posted_at = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    elif isinstance(ts, str) and ts.strip():
        try:
            posted_at = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            posted_at = None

    return {
        "story_id": str(story_id),
        "handle": handle,
        "posted_at": posted_at,
        "video_url": item.get("videoUrl") or item.get("video_url"),
        "image_url": (
            item.get("displayUrl") or item.get("imageUrl")
            or item.get("thumbnailUrl") or item.get("videoCoverUrl")
        ),
    }


def _mark_run(brand_id: str, *, found: int, checked: int, skipped: str | None = None) -> None:
    """Stamp the brand doc with the outcome of this sweep.

    Separate from `scan.steps.stories` on purpose. That map belongs to a scan
    SESSION and is cleared when the next one starts, while three quarters of
    these runs come from the 6-hourly scheduler, which has no session at all.
    Without this the stories panel could never answer the first question anyone
    asks it — "when did this last look?" — and an empty strip would be
    indistinguishable from a scheduler that silently stopped firing.

    Never raises: reporting must not be able to fail a sweep that succeeded.
    """
    try:
        fs.brand_doc(brand_id).set({"stories": {
            "lastRunAt": SERVER_TIMESTAMP,
            "lastFound": found,
            "lastChecked": checked,
            "lastSkipped": skipped,
        }}, merge=True)
    except Exception:
        log.exception(f"[{brand_id}] could not stamp stories run")


def run(brand_id: str, max_handles: int = DEFAULT_MAX_HANDLES, dry_run: bool = False) -> dict[str, Any]:
    brand = fs.brand_doc(brand_id).get()
    if not brand.exists:
        raise ValueError(f"brand not found: {brand_id}")

    zero = {"accountsChecked": 0, "storiesFound": 0, "imagesEnqueued": 0,
            "videosEnqueued": 0, "skippedNonStory": 0}
    if usage.budget_exhausted(brand_id):
        _mark_run(brand_id, found=0, checked=0, skipped="budget_exhausted")
        return {**zero, "skipped": "budget_exhausted"}
    if not usage.scraping_allowed(brand_id):
        _mark_run(brand_id, found=0, checked=0, skipped="budget")
        return {**zero, "skipped": "budget"}

    # Tracked creators only. Stories cost more per call than feed posts, and a
    # tier_3 creator is by definition one nobody asked us to follow closely.
    # Project members (the Lowlands roster) are tier_2, so they are included.
    due = list(
        fs.creators_col(brand_id)
        .where("platform", "==", "instagram")
        .where("tier", "in", ["tier_1", "tier_2"])
        .limit(max_handles)
        .stream()
    )
    by_handle: dict[str, Any] = {}
    for c in due:
        cd = c.to_dict() or {}
        h = (cd.get("handle") or "").strip().lower()
        if h:
            by_handle[h] = (c.reference, cd)
    handles = list(by_handle)
    if not handles:
        _mark_run(brand_id, found=0, checked=0, skipped="no_creators")
        return {**zero, "skipped": "no_creators"}

    items: list[dict] = []
    try:
        # ONE run for every handle: the actor charges a per-run fee that dwarfs
        # the per-username price, so 28 separate runs cost ~16x one batched run.
        items = apify.run_sync(STORIES_ACTOR, _actor_payload(handles), timeout=300, memory=1024)
    except Exception as e:
        log.error(f"[{brand_id}] stories actor failed: {e}")
    finally:
        # Recorded even when the run threw: the actor start is billed whether or
        # not we got items back, and a budget guard that under-reports is the
        # bug this codebase already had once.
        usage.record(brand_id, apify_story_runs=1, apify_story_usernames=len(handles))

    posts_col = fs.posts_col(brand_id)
    publisher = None if dry_run else pubsub_v1.PublisherClient()
    image_topic = None if publisher is None else publisher.topic_path(PROJECT_ID, DETECT_IMAGE_TOPIC)
    video_topic = None if publisher is None else publisher.topic_path(PROJECT_ID, DETECT_VIDEO_TOPIC)

    new_items: list[tuple[str, str, str]] = []
    stories_found = 0
    skipped_non_story = 0
    now = dt.datetime.now(dt.timezone.utc)

    for item in items:
        norm = _normalize_item(item)
        if norm is None:
            skipped_non_story += 1
            continue
        handle = norm["handle"]
        if handle not in by_handle:
            # Vendor returned an account we never asked about.
            skipped_non_story += 1
            continue
        creator_ref, cd = by_handle[handle]

        posted_at = norm["posted_at"] or now
        story_id = norm["story_id"]
        # No separator inside the second segment. The frontend collapses frames
        # and carousel slots into one row per post by taking the first two
        # underscore-separated parts of the post id (lib/types.parentPostKey), so
        # "instagram_story_123" reads as post "story" and EVERY story in the feed
        # would dedupe down to a single row.
        post_id = fs.composite_id("instagram", f"story{story_id}")

        doc: dict[str, Any] = {
            "creatorRef": creator_ref.path,
            "creatorHandle": handle,
            "creatorTier": cd.get("tier"),
            "platform": "instagram",
            "externalId": f"story_{story_id}",
            # A story permalink, not the raw CDN image: "open original" on a
            # story should look like a story, not like a stray JPEG.
            "url": f"https://www.instagram.com/stories/{handle}/{story_id}/",
            "caption": "",
            "hashtags": [],
            "mentions": [],
            "postedAt": posted_at,
            # Computed here — both prototypes promised this field in their
            # header and neither one ever wrote it.
            "expiresAt": posted_at + dt.timedelta(hours=STORY_TTL_HOURS),
            "contentType": "story",
            "videoUrl": norm["video_url"],
            "coverUrl": norm["image_url"],
            "likesCount": 0,
            "commentsCount": 0,
            "viewsCount": 0,
            "ingestedAt": SERVER_TIMESTAMP,
            "ingestedBy": "scan_stories",
        }
        if norm["posted_at"] is None:
            doc["postedAtEstimated"] = True
        posts_col.document(post_id).set(doc, merge=True)
        stories_found += 1

        if norm["image_url"]:
            img_id = fs.composite_id(post_id, "0")
            posts_col.document(post_id).collection("images").document(img_id).set({
                "url": norm["image_url"],
                "sequenceIdx": 0,
                "ingestedAt": SERVER_TIMESTAMP,
            }, merge=True)
        if norm["video_url"]:
            new_items.append((post_id, "video", norm["video_url"]))
        # The cover is analysed even for video stories: story video URLs are
        # short-lived signed CDN links that routinely expire while queued, and
        # the cover is the pass that reliably succeeds (same reasoning as
        # scan_creators._persist_post).
        if norm["image_url"]:
            new_items.append((post_id, "image", norm["image_url"]))

    images_enqueued = 0
    videos_enqueued = 0
    if not dry_run and publisher:
        futures = []
        for post_id, kind, url in new_items:
            payload = {"brandId": brand_id, "postId": post_id}
            if kind == "video":
                payload["videoUrl"] = url
                futures.append(publisher.publish(video_topic, json.dumps(payload).encode()))
                videos_enqueued += 1
            else:
                payload["imageUrl"] = url
                futures.append(publisher.publish(image_topic, json.dumps(payload).encode()))
                images_enqueued += 1
        if futures:
            from concurrent.futures import wait as _fwait
            _fwait(futures, timeout=30)
    else:
        videos_enqueued = sum(1 for _, k, _ in new_items if k == "video")
        images_enqueued = sum(1 for _, k, _ in new_items if k == "image")

    stats = {
        "accountsChecked": len(handles),
        "storiesFound": stories_found,
        "imagesEnqueued": images_enqueued,
        "videosEnqueued": videos_enqueued,
        "skippedNonStory": skipped_non_story,
    }
    _mark_run(brand_id, found=stories_found, checked=len(handles))
    fs.scan_runs_col(brand_id).add({
        "type": "scan_stories",
        "startedAt": SERVER_TIMESTAMP,
        "finishedAt": SERVER_TIMESTAMP,
        "stats": stats,
        "status": "ok",
    })
    log.info(f"[{brand_id}] stories: {stats}")
    return stats
