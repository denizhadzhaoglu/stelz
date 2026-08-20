"""Creator projects — named groups of creators a brand actively tracks.

The client ask ("creators in project gooien en dan tracken") has two halves and
the second is the one with teeth. Grouping is a Firestore array. TRACKING means
the project's creators are scanned on the fast cadence: adding a creator patches
their doc to the project's trackingTier, and the existing cadence map in
scan_creators ({tier_1: 6h, tier_2: 12h, tier_3: 48h}) does the rest. That
finally gives the tier system its first real writer — until now nothing ever
set anything but tier_3, and the DetectionDrawer's "Promote to tier 1" button
had no onClick.

THE CAP IS NOT OPTIONAL. tier_1 means an 8x scrape cadence per creator
(48h -> 6h). One enthusiastic project with 200 members would silently multiply
the brand's Apify spend and starve the hashtag scans out of the shared $5/day
budget ladder. So the number of DISTINCT tracked creators across all live
projects is capped, server-side, and the error says why. The plan named the cap
for tier_1; it is enforced for every tracked tier because tier_2 is still a 4x
cadence — cost is cost.

Kept as a handler (main.py wraps it in the HTTP endpoint) so it is testable the
same way bootstrap_brand is: against an in-memory Firestore double, no emulator.
"""
from __future__ import annotations

import logging
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP, ArrayRemove, ArrayUnion

from lib import fs

log = logging.getLogger(__name__)

# Distinct creators across all non-archived projects, any tracking tier.
TRACKED_CREATOR_CAP = 25

# What a project may track. tier_3 deliberately absent: it is the default
# cadence, so "tracking at tier_3" would be a no-op sold as a feature.
ALLOWED_TIERS = ("tier_1", "tier_2")

MAX_NAME_LEN = 80
MAX_NOTE_LEN = 500
MAX_CREATORS_PER_CALL = 50


class ProjectError(Exception):
    """Validation / business-rule failure with an HTTP status. main.py maps it."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _serialize(doc_id: str, d: dict) -> dict:
    created = d.get("createdAt")
    updated = d.get("updatedAt")
    return {
        "id": doc_id,
        "name": d.get("name"),
        "note": d.get("note"),
        "trackingTier": d.get("trackingTier"),
        "creatorIds": list(d.get("creatorIds") or []),
        "archived": bool(d.get("archived")),
        "createdBy": d.get("createdBy"),
        "createdAt": created.isoformat() if hasattr(created, "isoformat") else None,
        "updatedAt": updated.isoformat() if hasattr(updated, "isoformat") else None,
    }


def _live_projects(brand_id: str) -> list[tuple[str, dict]]:
    out = []
    for doc in fs.projects_col(brand_id).stream():
        d = doc.to_dict() or {}
        if not d.get("archived"):
            out.append((doc.id, d))
    return out


def _tracked_union(projects: list[tuple[str, dict]], exclude_id: str | None = None) -> set[str]:
    """Distinct creator ids across live projects (optionally excluding one)."""
    union: set[str] = set()
    for pid, d in projects:
        if pid == exclude_id:
            continue
        union.update(d.get("creatorIds") or [])
    return union


def _effective_tier(live: list[tuple[str, dict]], cid: str) -> str | None:
    """The tier a creator SHOULD carry: the fastest cadence among the live
    projects that claim them, or None when no project does.

    This exists because a per-project stamp is wrong in both directions
    (review-confirmed): adding a tier_1-tracked creator to a tier_2 project
    silently downgraded them to 12h, and removing them from the tier_1 project
    while a tier_2 project remained left the 6h cadence running forever — a 2x
    cost leak with nothing that would ever correct it. Every membership change
    now recomputes from the projects that actually claim the creator.
    """
    tiers = [
        d.get("trackingTier") or "tier_1"
        for _, d in live
        if cid in (d.get("creatorIds") or [])
    ]
    if not tiers:
        return None
    return "tier_1" if "tier_1" in tiers else "tier_2"


def _restamp(brand_id: str, creator_ids: list[str], live: list[tuple[str, dict]]) -> int:
    """Reconcile creator docs with the projects that claim them.

    Untracked creators go back to tier_3. Only the tier is patched — nextScanAt
    is left alone, so an in-flight fast scan completes and the next cycle simply
    schedules at the new cadence. Returns how many reverted to tier_3.
    """
    reverted = 0
    for cid in creator_ids:
        tier = _effective_tier(live, cid)
        if tier is None:
            fs.creators_col(brand_id).document(cid).set({"tier": "tier_3"}, merge=True)
            reverted += 1
        else:
            fs.creators_col(brand_id).document(cid).set({"tier": tier}, merge=True)
    return reverted


def run(brand_id: str, uid: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    col = fs.projects_col(brand_id)

    if action == "create":
        name = (body.get("name") or "").strip()
        if not name:
            raise ProjectError("name required")
        if len(name) > MAX_NAME_LEN:
            raise ProjectError(f"name too long (max {MAX_NAME_LEN})")
        tier = body.get("trackingTier") or "tier_1"
        if tier not in ALLOWED_TIERS:
            raise ProjectError(f"trackingTier must be one of {ALLOWED_TIERS}")
        doc_id = fs.composite_id(name)[:60] or "project"
        if col.document(doc_id).get().exists:
            raise ProjectError(f'A project named "{name}" already exists', status=409)
        col.document(doc_id).set({
            "name": name,
            "note": (body.get("note") or "")[:MAX_NOTE_LEN],
            "trackingTier": tier,
            "creatorIds": [],
            "archived": False,
            "createdBy": uid,
            "createdAt": SERVER_TIMESTAMP,
            "updatedAt": SERVER_TIMESTAMP,
        })
        return {"ok": True, "project": _serialize(doc_id, col.document(doc_id).get().to_dict() or {})}

    # Every other action addresses an existing project.
    project_id = body.get("projectId")
    if not project_id:
        raise ProjectError("projectId required")
    snap = col.document(project_id).get()
    if not snap.exists:
        raise ProjectError("project not found", status=404)
    project = snap.to_dict() or {}

    if action == "rename":
        patch: dict[str, Any] = {}
        if "name" in body:
            name = (body.get("name") or "").strip()
            if not name:
                raise ProjectError("name cannot be empty")
            if len(name) > MAX_NAME_LEN:
                raise ProjectError(f"name too long (max {MAX_NAME_LEN})")
            patch["name"] = name
        if "note" in body:
            patch["note"] = (body.get("note") or "")[:MAX_NOTE_LEN]
        if not patch:
            raise ProjectError("nothing to rename — pass name and/or note")
        patch["updatedAt"] = SERVER_TIMESTAMP
        col.document(project_id).set(patch, merge=True)
        return {"ok": True, "project": _serialize(project_id, col.document(project_id).get().to_dict() or {})}

    if action == "addCreators":
        ids = body.get("creatorIds")
        if not isinstance(ids, list) or not ids:
            raise ProjectError("creatorIds (non-empty list) required")
        if len(ids) > MAX_CREATORS_PER_CALL:
            raise ProjectError(f"max {MAX_CREATORS_PER_CALL} creators per call")
        ids = [str(c).strip().lower() for c in ids if str(c).strip()]
        if project.get("archived"):
            raise ProjectError("project is archived — unarchive it first", status=409)
        bad = [c for c in ids if "_" not in c]
        if bad:
            raise ProjectError(f"creatorIds must be platform_handle composites, got: {', '.join(bad[:3])}")

        # THE COST CAP, fast path. This check races (two concurrent adds can
        # both pass — no transactions here), so it is re-checked AFTER the write
        # below; this pre-check just avoids a pointless write in the common case.
        live = _live_projects(brand_id)
        union = _tracked_union(live)
        union.update(ids)
        cap_msg = (
            f"Tracking cap reached: {TRACKED_CREATOR_CAP} creators across all projects. "
            f"Tracked creators are scanned up to 8x as often, and this cap is what keeps "
            f"that from consuming the daily scan budget. Remove creators from a project "
            f"(or archive one) to free slots."
        )
        if len(union) > TRACKED_CREATOR_CAP:
            raise ProjectError(cap_msg, status=409)

        # Creators the pipeline has seen but never promoted get a tracking stub
        # HERE rather than a 404. This matters because the drawer's "Track in
        # project" is used on FEED detections, and most feed creators were never
        # promoted (promotion needs 2 distinct generic tags) — a 404 would make
        # the button fail for exactly the "found someone great, follow them"
        # moment the feature exists for. status "discovered" puts the stub on
        # the same path scan_creators already selects.
        for cid in ids:
            if not fs.creators_col(brand_id).document(cid).get().exists:
                platform, _, handle = cid.partition("_")
                fs.creators_col(brand_id).document(cid).set({
                    "handle": handle,
                    "platform": platform,
                    "status": "discovered",
                    "tier": "tier_3",  # real tier stamped below via _restamp
                    "addedVia": "project",
                    "createdAt": SERVER_TIMESTAMP,
                }, merge=True)

        # ArrayUnion, not read-modify-write: two teammates adding simultaneously
        # must both land. The merge=True-replaces-arrays trap is documented at
        # scan_hashtags.py:58-64 — same lesson.
        col.document(project_id).set({
            "creatorIds": ArrayUnion(ids),
            "updatedAt": SERVER_TIMESTAMP,
        }, merge=True)

        # Post-write re-check (review-confirmed TOCTOU): re-read the union and
        # ROLL BACK this addition if a concurrent add pushed it past the cap.
        # Not bulletproof — two racers can both roll back — but it converts
        # "cap silently breached forever" into "briefly exceeded, then repaired,
        # caller gets the honest error".
        live = _live_projects(brand_id)
        if len(_tracked_union(live)) > TRACKED_CREATOR_CAP:
            col.document(project_id).set({"creatorIds": ArrayRemove(ids)}, merge=True)
            live = _live_projects(brand_id)
            _restamp(brand_id, ids, live)
            raise ProjectError(cap_msg, status=409)

        # Tier via _effective_tier, not a blind stamp of THIS project's tier —
        # a creator also tracked by a faster project must keep the fast cadence.
        _restamp(brand_id, ids, live)
        for cid in ids:
            # nextScanAt now → eligible on the very next creator-scan run,
            # which is what "start tracking" should mean.
            fs.creators_col(brand_id).document(cid).set({"nextScanAt": SERVER_TIMESTAMP}, merge=True)
        tier = project.get("trackingTier") or "tier_1"
        log.info(f"[{brand_id}] project {project_id}: +{len(ids)} creators at {tier} (by {uid})")
        return {"ok": True, "project": _serialize(project_id, col.document(project_id).get().to_dict() or {})}

    if action == "removeCreators":
        ids = body.get("creatorIds")
        if not isinstance(ids, list) or not ids:
            raise ProjectError("creatorIds (non-empty list) required")
        ids = [str(c).strip().lower() for c in ids if str(c).strip()]
        # ArrayRemove, NOT a filtered-array overwrite. The overwrite variant
        # (review-confirmed HIGH) clobbered a concurrent teammate's ArrayUnion
        # add: their creator vanished from the project while keeping tier_1 on
        # the creator doc — scanned at 8x cost forever, claimed by nothing,
        # repaired by nothing.
        col.document(project_id).set({
            "creatorIds": ArrayRemove(ids),
            "updatedAt": SERVER_TIMESTAMP,
        }, merge=True)
        reverted = _restamp(brand_id, ids, _live_projects(brand_id))
        return {
            "ok": True, "reverted": reverted,
            "project": _serialize(project_id, col.document(project_id).get().to_dict() or {}),
        }

    if action == "archive":
        col.document(project_id).set({
            "archived": True,
            "updatedAt": SERVER_TIMESTAMP,
        }, merge=True)
        # Everything this project tracked reconciles against the remaining live
        # projects: unclaimed creators revert, creators a slower project still
        # claims drop to that project's cadence.
        reverted = _restamp(brand_id, list(project.get("creatorIds") or []), _live_projects(brand_id))
        return {
            "ok": True, "reverted": reverted,
            "project": _serialize(project_id, col.document(project_id).get().to_dict() or {}),
        }

    if action == "unarchive":
        # The addCreators error says "unarchive it first", so the action has to
        # exist (review finding: it didn't). Reviving a project re-claims its
        # members' fast cadence, so it must pass the same cap the add path does.
        if not project.get("archived"):
            raise ProjectError("project is not archived")
        live = _live_projects(brand_id)
        union = _tracked_union(live)
        union.update(project.get("creatorIds") or [])
        if len(union) > TRACKED_CREATOR_CAP:
            raise ProjectError(
                f"Unarchiving would put {len(union)} creators on tracked cadence — the cap is "
                f"{TRACKED_CREATOR_CAP}. Free slots first (remove creators or archive another project).",
                status=409,
            )
        col.document(project_id).set({
            "archived": False,
            "updatedAt": SERVER_TIMESTAMP,
        }, merge=True)
        _restamp(brand_id, list(project.get("creatorIds") or []), _live_projects(brand_id))
        return {"ok": True, "project": _serialize(project_id, col.document(project_id).get().to_dict() or {})}

    raise ProjectError(f"unknown action {action}")
