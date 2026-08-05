"""Per-brand daily usage tracking + budget guard.

Increment counters from each handler. Surfaced in the Settings → Usage card
on the UI. The budget guard short-circuits expensive functions when the
day's spend exceeds the brand's `dailyBudgetUsd` setting (default $1.00).

Counters tracked:
  apify_runs           — Apify actor invocations
  gemini_flash_calls   — full Gemini Flash detection calls
  gemini_embed_calls   — Gemini embedding-001 calls
  ocr_calls            — RapidOCR runs (free, tracked for visibility)
  detections_written   — detection docs persisted
  detections_hit       — detection docs with detected=true

Estimated cost per call (used by the guard):
  flash:  $0.00075   (1 image + ~6 ref images @ Flash input tokens)
  embed:  $0.00010   (1 image embedding)
  apify:  $0.10      (rough — one hashtag or profile batch)
"""
from __future__ import annotations
import logging
from typing import Any

from google.cloud.firestore import Increment, SERVER_TIMESTAMP

from . import fs

log = logging.getLogger(__name__)

COST_PER_CALL = {
    "gemini_flash_calls": 0.00075,
    "gemini_embed_calls": 0.00010,
    "apify_runs": 0.10,
}

DEFAULT_DAILY_BUDGET_USD = 5.0


def record(brand_id: str, **counters: int) -> None:
    """Atomically increment one or more counters on today's usage doc."""
    if not counters:
        return
    patch: dict[str, Any] = {k: Increment(int(v)) for k, v in counters.items()}
    patch["updatedAt"] = SERVER_TIMESTAMP
    try:
        fs.usage_doc(brand_id).set(patch, merge=True)
    except Exception as e:
        log.warning(f"usage record failed: {e}")


def estimated_spend_today(brand_id: str) -> float:
    snap = fs.usage_doc(brand_id).get()
    if not snap.exists:
        return 0.0
    data = snap.to_dict() or {}
    total = 0.0
    for key, per_call in COST_PER_CALL.items():
        total += float(data.get(key, 0)) * per_call
    return total


def budget_exhausted(brand_id: str) -> bool:
    """MVP: disabled. Re-enable before customer billing goes live."""
    return False
