"""Scan progress — what the UI subscribes to while a scan runs.

The progress plumbing already existed and worked (a `scan` map on the brand
doc, onSnapshot in the client, Increment counters, a finally-guaranteed bump).
It modelled a ONE-step scan while Run scan actually runs seven, so the pill
said "done" the moment the last hashtag worker returned and the remaining five
steps ran invisibly — and when one of them failed, nothing anywhere recorded
it.

This module adds a per-step map beside the existing flat fields. The flat
fields are kept verbatim: the current pill reads them, and a frontend that
predates the steps map must keep working against a backend that has it.

Every function swallows its own exceptions. Progress reporting is decoration;
it must never be the reason a scan fails.
"""
from __future__ import annotations

import logging
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP, Increment

from lib import fs

log = logging.getLogger(__name__)

# Every step Run scan can execute, in the order the UI lists them.
STEPS = ("hashtags", "creators", "stories", "profiles", "subcultures", "srs", "sentiment")


def _sanitize_counts(d: dict[str, Any] | None) -> dict[str, Any]:
    """Handler return dicts go straight to the client, so keep them to
    primitives — a stray object would fail the Firestore write and take the
    step's completion with it."""
    out: dict[str, Any] = {}
    for k, v in (d or {}).items():
        if isinstance(v, (str, int, float, bool)) and not isinstance(v, bytes):
            out[str(k)[:60]] = v
    return out


def step_started(brand_id: str, step: str) -> None:
    try:
        # update() with a dotted path REPLACES the whole step map, which is what
        # clears a previous run's counts and error. set(merge=True) would leave
        # last week's failure sitting under a green step.
        fs.brand_doc(brand_id).update({
            f"scan.steps.{step}": {
                "state": "running",
                "startedAt": SERVER_TIMESTAMP,
                "finishedAt": None,
                "error": None,
                "counts": {},
            },
            "scan.lastActivityAt": SERVER_TIMESTAMP,
        })
    except Exception:
        log.exception(f"[{brand_id}] step_started({step}) failed")


def step_finished(brand_id: str, step: str, counts: dict[str, Any] | None = None) -> None:
    try:
        fs.brand_doc(brand_id).update({
            f"scan.steps.{step}.state": "done",
            f"scan.steps.{step}.finishedAt": SERVER_TIMESTAMP,
            f"scan.steps.{step}.counts": _sanitize_counts(counts),
            "scan.lastActivityAt": SERVER_TIMESTAMP,
        })
    except Exception:
        log.exception(f"[{brand_id}] step_finished({step}) failed")


def step_failed(brand_id: str, step: str, error: str) -> None:
    try:
        fs.brand_doc(brand_id).update({
            f"scan.steps.{step}.state": "error",
            f"scan.steps.{step}.error": str(error)[:300],
            f"scan.steps.{step}.finishedAt": SERVER_TIMESTAMP,
            "scan.lastActivityAt": SERVER_TIMESTAMP,
        })
    except Exception:
        log.exception(f"[{brand_id}] step_failed({step}) failed")


def bump_detect_progress(brand_id: str, hit: bool, skipped: bool = False) -> None:
    """One detect message processed. Called from a finally on EVERY terminal
    path, including the expected ones (an expired Instagram CDN URL is a normal
    outcome, not an anomaly) — previously only the write-a-detection path
    bumped, so the "analysing" bar could never reach 100% on any scan that had
    a single stale URL in it.

    lastActivityAt rides the same write: without it the client's 5-minute stall
    detector saw a frozen heartbeat all through a healthy detect phase and
    reported a working scan as dead.
    """
    try:
        fs.brand_doc(brand_id).set({
            "scan": {
                "detectionsCompleted": Increment(1),
                "detectionsHit": Increment(1 if hit else 0),
                "skippedCount": Increment(1 if skipped else 0),
                "lastActivityAt": SERVER_TIMESTAMP,
            }
        }, merge=True)
    except Exception:
        log.exception(f"[{brand_id}] bump_detect_progress failed")
