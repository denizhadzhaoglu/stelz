"""In-app inbox writer.

Pipeline events that the brand manager should see when they open the app
land here. No Slack/email push — the UI's <InboxBell /> reads this stream.

Events are written to every brand member's /users/{uid}/inbox/{auto-id} doc
so each member has their own read state.
"""
from __future__ import annotations
import logging
from typing import Any

from google.cloud.firestore import SERVER_TIMESTAMP

from . import fs

log = logging.getLogger(__name__)


def _member_uids(brand_id: str) -> list[str]:
    return [m.id for m in fs.members_col(brand_id).stream()]


def publish(brand_id: str, event_type: str, body: str, link: str | None = None, meta: dict[str, Any] | None = None) -> int:
    """Publish an inbox event to every member of the brand.
    Returns count of inboxes written. Idempotency is naive — multiple calls
    will produce multiple events; callers should de-duplicate as needed."""
    uids = _member_uids(brand_id)
    if not uids:
        log.warning(f"[{brand_id}] no members for inbox event '{event_type}'")
        return 0

    payload = {
        "type": event_type,
        "brandId": brand_id,
        "body": body,
        "link": link,
        "meta": meta or {},
        "read": False,
        "createdAt": SERVER_TIMESTAMP,
    }
    db = fs.db()
    for uid in uids:
        try:
            fs.inbox_col(uid).add(payload)
        except Exception as e:
            log.warning(f"inbox add failed for {uid}: {e}")
    return len(uids)
