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


def scrape_profiles_ig(usernames: list[str]) -> list[dict]:
    """Profile-level rows: followersCount, biography, profilePicUrlHD, verified.

    This is the ONLY way we get a follower count for Instagram. Post rows carry
    none — see the comment in scrape_profile_ig — so without this call the
    dashboard has nothing to show, which is why it used to print "0 followers"
    for every Instagram creator.

    One result per username, and Apify bills per result, so refreshing 500
    creators costs about $1.15. Cheap enough to run on every scan.

    Fields are returned best-effort: a verified live run came back with the full
    set for one profile and only biography/fullName/verified for another. Every
    caller must treat each field as optional.
    """
    names = [u.lstrip("@").strip() for u in usernames if u and u.strip()]
    if not names:
        return []
    return run_sync(
        "apify/instagram-profile-scraper",
        {"usernames": names},
        timeout=180,
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
            # MEASURED, not assumed: setting this to True adds nothing here.
            # A live run against apify/instagram-scraper returned exactly the
            # same fields either way — ownerUsername, ownerFullName, ownerId and
            # no more. There is no followersCount, no biography and no profile
            # picture on a post row, with or without it.
            #
            # That matters because "just turn on addParentData" is the obvious
            # guess for why follower counts are missing, and it is wrong. The
            # follower count comes from a DIFFERENT actor entirely —
            # scrape_profiles_ig() below, which is what refresh_profiles uses.
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
