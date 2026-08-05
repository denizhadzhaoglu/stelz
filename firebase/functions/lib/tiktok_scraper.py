"""Python client for the Node.js Playwright-based TikTok tag scraper.

The scraper itself lives in a sibling Cloud Functions codebase
(`functions-tiktok/`) and is exposed as an HTTPS function. We call it
synchronously from the Python orchestrator and shape its output to look
like what `scan_hashtags` expects (a list of "items"). This lets us keep
the rest of the pipeline (post persist + detect-video fan-out) unchanged.
"""
from __future__ import annotations
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)


def _endpoint() -> str:
    # Override via env when running against emulator / staging.
    url = os.getenv("TIKTOK_SCRAPER_URL")
    if url:
        return url
    # v2 functions expose a run.app URL — hardcode the deployed one. If the
    # project / region changes, set TIKTOK_SCRAPER_URL in .env.
    return "https://scrapetiktoktag-a3q43eo5ja-uc.a.run.app"


def scrape_tag(hashtag: str, limit: int = 200, min_views: int = 0, timeout: int = 90) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Call the JS Playwright scraper and return (items, diag). Items are
    shaped like Apify TikTok items so the rest of the pipeline is unchanged.
    diag includes blockedReason, captchaDetected, itemList count etc — for
    surfacing in scrapeLog when items=0."""
    url = _endpoint()
    diag: dict[str, Any] = {"transportError": None}
    try:
        r = requests.post(
            url,
            json={"hashtag": hashtag, "limit": limit, "minViews": min_views, "maxRetries": 0},
            headers={"content-type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        log.error(f"tiktok scraper request failed: {e}")
        diag["transportError"] = str(e)[:200]
        return [], diag
    if r.status_code != 200:
        log.error(f"tiktok scraper status={r.status_code} body={r.text[:300]}")
        diag["transportError"] = f"http_{r.status_code}: {r.text[:200]}"
        return [], diag
    data = r.json() or {}
    raw_videos = data.get("videos") or []
    if isinstance(data.get("diag"), dict):
        diag.update(data["diag"])

    items: list[dict[str, Any]] = []
    for v in raw_videos:
        handle = v.get("author") or ""
        vid = str(v.get("id") or "")
        if not vid or not handle:
            continue
        items.append({
            "id": vid,
            "webVideoUrl": v.get("url") or f"https://www.tiktok.com/@{handle}/video/{vid}",
            "text": v.get("desc") or "",
            "hashtags": [],  # not extracted by the scraper (cheap; can add later)
            "createTimeISO": None,
            "createTime": v.get("createTime"),
            "diggCount": v.get("diggCount") or 0,
            "commentCount": v.get("commentCount") or 0,
            "playCount": v.get("playCount") or 0,
            "shareCount": v.get("shareCount") or 0,
            "type": "Video",
            "authorMeta": {
                "name": handle,
                "nickName": v.get("authorName") or "",
                "avatar": v.get("avatar") or "",
                "fans": None,
            },
            "videoMeta": {
                "coverUrl": v.get("cover") or "",
                "duration": v.get("duration"),
                # No downloadAddr — Playwright scraper doesn't get one. The
                # detect_video handler falls back to yt-dlp on webVideoUrl.
                "downloadAddr": "",
            },
        })
    log.info(f"[tiktok_scraper] tag=#{hashtag} returned={len(items)} blocked={diag.get('blockedReason')}")
    return items, diag
