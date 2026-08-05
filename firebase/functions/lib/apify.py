"""Apify wrapper — thin layer over run-sync-get-dataset-items."""
from __future__ import annotations
import os
import requests
from typing import Any

APIFY_BASE = "https://api.apify.com/v2/acts"


class ApifyError(Exception):
    pass


def _token() -> str:
    t = os.getenv("APIFY_API_TOKEN")
    if not t:
        raise ApifyError("APIFY_API_TOKEN not set")
    return t


def run_sync(actor_id: str, payload: dict[str, Any], timeout: int = 240, memory: int = 1024) -> list[dict]:
    """Run an Apify actor synchronously and return dataset items."""
    url = f"{APIFY_BASE}/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    r = requests.post(
        url,
        json=payload,
        params={"token": _token(), "timeout": timeout, "memory": memory},
        timeout=timeout + 30,
    )
    if r.status_code == 404:
        raise ApifyError(f"actor not found: {actor_id}")
    r.raise_for_status()
    return r.json()


# ─── Common actor wrappers ──────────────────────────────────

def scrape_hashtag_ig(hashtag: str, results_limit: int = 200) -> list[dict]:
    return run_sync(
        "apify/instagram-hashtag-scraper",
        {"hashtags": [hashtag], "resultsLimit": results_limit},
    )


def scrape_profile_ig(usernames: list[str], posts_per: int = 15) -> list[dict]:
    """Scrape posts (incl. Reels) from IG profiles.

    Uses `apify/instagram-scraper` (URL-based, post-level output) NOT
    `instagram-profile-scraper` which ignores resultsType=posts and only ever
    returns profile-level rows. Each output row is a post with the fields we
    care about: id, shortCode, type, videoUrl, displayUrl, caption, hashtags,
    likesCount, etc.

    Pass small batches (≤10 handles) from the caller — large batches hit the
    Cloud Functions 540s wall.
    """
    direct_urls = [f"https://www.instagram.com/{u.lstrip('@').strip()}/" for u in usernames if u]
    return run_sync(
        "apify/instagram-scraper",
        {
            "directUrls": direct_urls,
            "resultsType": "posts",
            "resultsLimit": posts_per,
            "addParentData": False,
            "searchType": "user",
            "searchLimit": 1,
        },
        timeout=180,
    )


def scrape_hashtag_tiktok(hashtag: str, results_per_page: int = 100) -> list[dict]:
    # Try free actor first, fall back to paid one.
    try:
        return run_sync(
            "clockworks/free-tiktok-scraper",
            {
                "hashtags": [hashtag],
                "resultsPerPage": results_per_page,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            },
            timeout=300,
        )
    except (requests.HTTPError, ApifyError):
        return run_sync(
            "clockworks/tiktok-scraper",
            {"hashtags": [hashtag], "resultsPerPage": results_per_page, "shouldDownloadVideos": False},
            timeout=300,
        )
