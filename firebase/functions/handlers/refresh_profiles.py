"""Refresh creator profiles: follower count, bio, avatar.

WHY THIS IS A SEPARATE SCRAPE
-----------------------------
Instagram post rows carry no owner data beyond a username and a display name.
This was verified against the live actor rather than assumed: apify/instagram-
scraper returns the same fields with `addParentData` on or off, and neither
includes followersCount, biography or a profile picture. The obvious guess —
"turn on addParentData" — is wrong, and the comment in lib/apify.py says so, so
nobody spends another afternoon on it.

Follower counts therefore require apify/instagram-profile-scraper, one result
per username. That is what this handler runs. It is cheap (about $1.15 per 500
creators, billed per result) and it is what turns "0 followers everywhere" —
the single most-reported thing wrong with the dashboard — into real numbers.

WHAT IT UNBLOCKS BEYOND THE NUMBER
----------------------------------
  * avatars for Instagram creators, who had none at all (TikTok posts carry one,
    Instagram posts do not, which is why half the leaderboard showed monograms)
  * biographies, which are the richest per-person signal we have for the
    audience profiles — including the only place anyone tells us their own age
  * the SRS geo layer, which reads is_dutch_speaker off the creator record

TikTok needs none of this: its post rows already carry authorMeta.fans and a
signature, so this handler only touches Instagram creators.
"""
from __future__ import annotations
import logging
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from lib import apify, fs, usage

log = logging.getLogger(__name__)

# Apify takes the whole list, but a huge single call risks the function timeout.
BATCH = 50
# Ceiling per run, so one invocation can never surprise the budget.
DEFAULT_LIMIT = 500


def run(brand_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    if not fs.brand_doc(brand_id).get().exists:
        return {"status": "skip", "reason": "no_brand"}
    if not usage.scraping_allowed(brand_id):
        return {"status": "skip", "reason": "budget"}

    # Instagram creators only — TikTok already has what this would fetch.
    handles: list[str] = []
    refs: dict[str, Any] = {}
    for doc in fs.creators_col(brand_id).where("platform", "==", "instagram").limit(limit).stream():
        d = doc.to_dict() or {}
        h = (d.get("handle") or "").strip().lower()
        if not h:
            continue
        handles.append(h)
        refs[h] = doc.reference

    if not handles:
        return {"status": "ok", "scanned": 0, "updated": 0}

    updated = 0
    missing_followers = 0
    for i in range(0, len(handles), BATCH):
        chunk = handles[i:i + BATCH]
        try:
            items = apify.scrape_profiles_ig(chunk)
        except Exception as e:
            log.warning(f"[{brand_id}] profile batch failed ({chunk[:3]}…): {e}")
            continue
        usage.record(brand_id, apify_ig_results=len(items))

        for it in items:
            handle = (it.get("username") or "").strip().lower()
            ref = refs.get(handle)
            if not ref:
                continue
            # Every field is optional: a verified live run returned the full set
            # for one profile and only part of it for another. Write what came
            # back and leave the rest untouched rather than clearing it.
            patch: dict[str, Any] = {"profileRefreshedAt": SERVER_TIMESTAMP}
            if it.get("followersCount"):
                patch["followerCount"] = int(it["followersCount"])
            else:
                missing_followers += 1
            if it.get("biography"):
                patch["bio"] = str(it["biography"])[:500]
            if it.get("profilePicUrlHD") or it.get("profilePicUrl"):
                patch["avatarUrl"] = it.get("profilePicUrlHD") or it.get("profilePicUrl")
            if it.get("fullName"):
                patch["fullName"] = it["fullName"]
            if it.get("verified") is not None:
                patch["platformVerified"] = bool(it["verified"])
            if it.get("postsCount"):
                patch["postsCount"] = int(it["postsCount"])
            ref.set(patch, merge=True)
            updated += 1

    return {
        "status": "ok",
        "scanned": len(handles),
        "updated": updated,
        # Reported rather than hidden: Instagram does not always return a count,
        # and a caller seeing "updated 400" would otherwise assume 400 numbers.
        "without_follower_count": missing_followers,
    }
