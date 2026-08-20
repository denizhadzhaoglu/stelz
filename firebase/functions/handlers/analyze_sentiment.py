"""Score post sentiment over hits that don't have it yet.

A batch step, not a per-detection trigger, for two reasons:

  * it backfills. Sentiment is new to this pipeline (the old Supabase-era
    tools/stelz_brand_watch/24_sentiment_analysis.py wrote to a database that
    no longer exists), so on day one every hit in the feed is missing it. A
    trigger would only ever score posts found from now on, and the dashboard
    would sit empty for weeks.
  * it is bounded and interruptible. `limit` caps the spend of any one run and
    the budget guard stops it early, which matters because this runs over the
    whole back catalogue the first time.

Idempotent: only detections without a `sentiment` field are considered, so
re-running picks up where the last run stopped, including after a timeout.
"""
from __future__ import annotations
import logging
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from lib import fs, gemini, sentiment, usage

log = logging.getLogger(__name__)

# Per-run ceiling. A full pass over a back catalogue is fine, but it should
# take several deliberate runs rather than one unbounded one.
DEFAULT_LIMIT = 400

# Firestore has no "field missing" filter, so candidates are streamed and
# filtered in-process. This caps how many docs one run will read looking for
# unscored ones — without it, a fully-scored catalogue would re-read every
# detection on every run to discover there is nothing to do.
SCAN_CEILING = 5000


def _candidates(brand_id: str, limit: int) -> list[tuple[str, dict]]:
    """Detected, not-rejected hits with no sentiment yet, newest first."""
    q = (
        fs.detections_col(brand_id)
        .where("detected", "==", True)
        .order_by("postedAt", direction="DESCENDING")
        .limit(SCAN_CEILING)
    )
    out: list[tuple[str, dict]] = []
    for doc in q.stream():
        d = doc.to_dict() or {}
        if d.get("sentiment"):
            continue
        # Moderator-rejected hits are somebody else's drink; scoring how warmly
        # a post talks about it would be noise in every chart it reaches.
        if d.get("isFalsePositive") is True:
            continue
        out.append((doc.id, d))
        if len(out) >= limit:
            break
    return out


def run(brand_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    brand_snap = fs.brand_doc(brand_id).get()
    if not brand_snap.exists:
        return {"status": "skip", "reason": "no_brand"}
    brand_name = (brand_snap.to_dict() or {}).get("name", brand_id)

    if usage.budget_exhausted(brand_id):
        return {"status": "skip", "reason": "budget_exhausted"}

    todo = _candidates(brand_id, limit)
    if not todo:
        return {"status": "ok", "scored": 0, "failed": 0, "remaining": 0}

    scored = 0
    failed = 0
    counts: dict[str, int] = {}
    for doc_id, d in todo:
        # Re-check per item: a long run can cross the budget line partway.
        if usage.budget_exhausted(brand_id):
            log.info("sentiment run stopped early: budget exhausted")
            break
        summary = sentiment.build_summary(
            caption=d.get("postCaption"),
            hashtags=d.get("postHashtags"),
            creator_handle=d.get("creatorHandle"),
            creator_category=d.get("creatorCategory"),
            context=d.get("context"),
        )
        try:
            verdict = gemini.analyze_sentiment(brand_name, summary)
        except Exception as e:
            log.warning(f"sentiment call failed for {doc_id}: {e}")
            failed += 1
            continue
        finally:
            usage.record(brand_id, gemini_sentiment_calls=1)

        if verdict is None:
            # Unparseable answer. Leave the field unset so the next run retries
            # it rather than freezing a guess into the data.
            failed += 1
            continue

        fs.detections_col(brand_id).document(doc_id).set({
            "sentiment": verdict["sentiment"],
            "sentimentScore": verdict["sentiment_score"],
            "sentimentRationale": verdict.get("sentiment_rationale"),
            "sentimentAt": SERVER_TIMESTAMP,
        }, merge=True)
        scored += 1
        counts[verdict["sentiment"]] = counts.get(verdict["sentiment"], 0) + 1

    return {
        "status": "ok",
        "scored": scored,
        "failed": failed,
        "breakdown": counts,
        # How many of THIS run's batch went unscored. Not a catalogue-wide
        # total: finding that would cost a second full stream.
        "remaining": len(todo) - scored - failed,
    }
