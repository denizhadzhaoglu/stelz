"""Firebase Cloud Functions entry points (Python 3.11).

Architecture:
  Scheduled (Cloud Scheduler):
    daily_pipeline        07:00 UTC  → hashtags → creators → srs (one function, chained)

  Pub/Sub triggered:
    on_detect_image       topic: detect-image  → OCR → embedding → Gemini → detections
    on_detect_video       topic: detect-video  → frame sample → detect each → detections

  HTTP (UI triggered):
    api_bootstrap_brand          create brand + add caller as owner-member
    api_step_hashtags            manual hashtag discovery
    api_step_creators            manual creator scrape (fans out detect-image/video)
    api_step_srs                 recompute resonance scores
    api_rate_detection           moderator approve / reject
    api_brand_settings_update    edit brand profile (hashtags, identity, threshold)

Auth: HTTP functions require Firebase Auth ID token (verified inline).
"""
from __future__ import annotations
import base64
import json
import logging
import os

# Load .env from this directory (functions/) before anything else imports it.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

import firebase_admin
from firebase_functions import https_fn, options, pubsub_fn
from firebase_admin import auth as fb_auth

# Initialize Admin SDK at module load — required for fb_auth + Firestore.
if not firebase_admin._apps:
    firebase_admin.initialize_app(
        options={"storageBucket": os.getenv("STORAGE_BUCKET", "brand-audit-4b2cc.firebasestorage.app")}
    )

from handlers import (
    bootstrap_brand,
    scan_hashtags,
    scan_creators,
    detect_image,
    detect_video,
    compute_resonance,
)
from lib import fs  # noqa: ensure init

log = logging.getLogger(__name__)
options.set_global_options(region="europe-west1", memory=options.MemoryOption.MB_512)


# ─────────────────── SCHEDULED ───────────────────
# All scheduled functions removed (daily_pipeline + scan_watchdog): scans run
# only when the Run scan button is pressed. The UI already detects stalled
# sessions (5-min activity heartbeat), so the watchdog isn't needed either.


# ─────────────────── PUB/SUB ───────────────────

def _decode_pubsub(event) -> dict:
    raw = event.data.message.data
    if not raw:
        return {}
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:
        return json.loads(raw)


@pubsub_fn.on_message_published(
    topic="detect-image",
    memory=options.MemoryOption.GB_1,
    timeout_sec=180,
    # Gen2 default concurrency is 80 → one container juggling 80 images
    # shares (and corrupts) the global Gemini client across threads and
    # blows the memory limit. One message per container.
    concurrency=1,
    max_instances=50,
)
def on_detect_image(event: pubsub_fn.CloudEvent[pubsub_fn.MessagePublishedData]) -> None:
    msg = _decode_pubsub(event)
    brand_id, post_id, image_url = msg.get("brandId"), msg.get("postId"), msg.get("imageUrl")
    if not (brand_id and post_id and image_url):
        log.error(f"bad detect-image message: {msg}")
        return
    detect_image.run(brand_id, post_id, image_url)


@pubsub_fn.on_message_published(
    topic="detect-video",
    memory=options.MemoryOption.GB_2,  # video bytes + cv2 frames + OCR model held in RAM
    timeout_sec=300,
    # One video per container. Gen2's default concurrency (80) packed dozens
    # of videos into a single instance: guaranteed OOM at any memory limit,
    # plus cross-thread corruption of the shared Gemini client ("client has
    # been closed", SSL bad record mac).
    concurrency=1,
    max_instances=25,
)
def on_detect_video(event: pubsub_fn.CloudEvent[pubsub_fn.MessagePublishedData]) -> None:
    msg = _decode_pubsub(event)
    brand_id, post_id, video_url = msg.get("brandId"), msg.get("postId"), msg.get("videoUrl")
    if not (brand_id and post_id and video_url):
        log.error(f"bad detect-video message: {msg}")
        return
    detect_video.run(brand_id, post_id, video_url)


# ─────────────────── HTTP (UI) ───────────────────

def _require_auth(req: https_fn.Request) -> str:
    """Return uid, or raise 401."""
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode.UNAUTHENTICATED, "Missing token")
    token = auth_header.split(" ", 1)[1]
    try:
        decoded = fb_auth.verify_id_token(token)
    except Exception:
        raise https_fn.HttpsError(https_fn.FunctionsErrorCode.UNAUTHENTICATED, "Invalid token")
    return decoded["uid"]


def _require_brand_member(uid: str, brand_id: str) -> None:
    # MVP: any signed-in user can act on any brand. Restore membership gate
    # (below) before onboarding real customers.
    return
    # member = fs.brand_doc(brand_id).collection("members").document(uid).get()
    # if not member.exists:
    #     raise https_fn.HttpsError(https_fn.FunctionsErrorCode.PERMISSION_DENIED, "Not a brand member")


@https_fn.on_request(cors=options.CorsOptions(cors_origins=["*"], cors_methods=["POST", "OPTIONS"]))
def api_bootstrap_brand(req: https_fn.Request) -> https_fn.Response:
    """First-run brand creation. Any authenticated user can create a brand
    and become its owner. Idempotent."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)
    try:
        # Manual auth check so we can grab email too
        auth_header = req.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return https_fn.Response(json.dumps({"error": "Missing token"}), status=401, mimetype="application/json")
        decoded = fb_auth.verify_id_token(auth_header.split(" ", 1)[1])
        uid = decoded["uid"]
        email = decoded.get("email")

        body = req.get_json(silent=True) or {}
        brand_id = body.get("brandId") or "stelz"
        brand_name = body.get("brandName") or "Stelz"

        stats = bootstrap_brand.run(brand_id, brand_name, uid, email)
        return https_fn.Response(json.dumps(stats), status=200, mimetype="application/json")
    except Exception as e:
        log.exception("bootstrap_brand failed")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


def _run_step(req: https_fn.Request, runner_factory) -> https_fn.Response:
    """Shared boilerplate: auth check + brand membership + run one step."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)
    try:
        uid = _require_auth(req)
        body = req.get_json(silent=True) or {}
        brand_id = body.get("brandId")
        if not brand_id:
            return https_fn.Response(json.dumps({"error": "brandId required"}), status=400, mimetype="application/json")
        _require_brand_member(uid, brand_id)
        result = runner_factory(brand_id, body)
        return https_fn.Response(json.dumps(result), status=200, mimetype="application/json")
    except https_fn.HttpsError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=400, mimetype="application/json")
    except Exception as e:
        log.exception("step failed")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


CORS_POST = options.CorsOptions(cors_origins=["*"], cors_methods=["POST", "OPTIONS"])


@https_fn.on_request(cors=CORS_POST, memory=options.MemoryOption.MB_512, timeout_sec=60)
def api_step_hashtags(req: https_fn.Request) -> https_fn.Response:
    """Step 1/3 — Fans out one Pub/Sub message per active hashtag onto the
    scrape-tag topic. Returns immediately (~3s). Each tag worker (on_scrape_tag
    below) does the actual scrape + persist + detect-fanout with its own 540s
    budget. Look at scrapeLog / scanRuns in the Debug tab for progress."""
    return _run_step(req, lambda brand_id, body: scan_hashtags.publish_tags(
        brand_id,
        per_tag=int(body.get("perTag") or 500),
        max_tags=int(body.get("maxTags") or 50),
    ))


@pubsub_fn.on_message_published(
    topic="scrape-tag",
    memory=options.MemoryOption.GB_1,
    timeout_sec=540,
    region="europe-west1",
)
def on_scrape_tag(event: pubsub_fn.CloudEvent[pubsub_fn.MessagePublishedData]) -> None:
    """One hashtag scrape, end-to-end. Fired by api_step_hashtags fan-out."""
    try:
        raw = event.data.message.data
        decoded = base64.b64decode(raw).decode("utf-8") if raw else "{}"
        payload = json.loads(decoded or "{}")
    except Exception as e:
        log.error(f"on_scrape_tag bad payload: {e}")
        return
    brand_id = payload.get("brandId")
    tag = payload.get("tag")
    platform = payload.get("platform") or "instagram"
    per_tag = int(payload.get("perTag") or 100)
    if not brand_id or not tag:
        log.error(f"on_scrape_tag missing fields: {payload}")
        return
    try:
        scan_hashtags.process_one_tag(brand_id, tag, platform, per_tag=per_tag)
    except Exception:
        log.exception(f"on_scrape_tag #{tag} failed")


@https_fn.on_request(cors=CORS_POST, memory=options.MemoryOption.GB_1, timeout_sec=540)
def api_step_creators(req: https_fn.Request) -> https_fn.Response:
    """Step 2/3 — Apify profile scrape → posts + images + fan-out detect-image/video."""
    return _run_step(req, lambda brand_id, body: scan_creators.run(
        brand_id,
        max_creators=int(body.get("maxCreators") or 80),
        posts_per=int(body.get("postsPer") or 6),
    ))


@https_fn.on_request(cors=CORS_POST, memory=options.MemoryOption.GB_1, timeout_sec=300)
def api_step_srs(req: https_fn.Request) -> https_fn.Response:
    """Step 3/3 — Compute SRS over all candidates."""
    return _run_step(req, lambda brand_id, body: compute_resonance.run(brand_id))


@https_fn.on_request(cors=options.CorsOptions(cors_origins=["*"], cors_methods=["POST", "OPTIONS"]))
def api_rate_detection(req: https_fn.Request) -> https_fn.Response:
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)
    try:
        uid = _require_auth(req)
        body = req.get_json(silent=True) or {}
        brand_id = body.get("brandId")
        detection_id = body.get("detectionId")
        verdict = body.get("verdict")  # 'confirmed' | 'plausible' | 'rejected'
        if not (brand_id and detection_id and verdict):
            return https_fn.Response(json.dumps({"error": "brandId, detectionId, verdict required"}), status=400, mimetype="application/json")
        _require_brand_member(uid, brand_id)
        from google.cloud.firestore import SERVER_TIMESTAMP
        fs.detections_col(brand_id).document(detection_id).set({
            "verified": verdict == "confirmed",
            "isFalsePositive": verdict == "rejected",
            "moderationLabel": verdict,
            "verifiedBy": uid,
            "verifiedAt": SERVER_TIMESTAMP,
        }, merge=True)
        return https_fn.Response(json.dumps({"ok": True}), status=200, mimetype="application/json")
    except https_fn.HttpsError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=400, mimetype="application/json")
    except Exception as e:
        log.exception("rate_detection failed")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


# Allowed editable brand fields. Whitelist prevents UI from sneaking in
# server-only fields like visualCentroid, hashtagYield, etc.
_BRAND_EDITABLE_FIELDS = {
    "name", "slug", "website",
    "visualIdentity",      # multiline prompt fragment Gemini sees
    "wordmarkAliases",     # list[str] for OCR shortcut
    "productLines",        # dict[key, label]
    "confidenceMin",       # float, hides feed entries below this
    "embeddingThreshold",  # float, embedding pre-filter cosine
    "dailyBudgetUsd",      # float, budget guard ceiling
}


@https_fn.on_request(cors=CORS_POST)
def api_brand_settings_update(req: https_fn.Request) -> https_fn.Response:
    """Settings page write endpoint. Whitelisted brand fields only."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)
    try:
        uid = _require_auth(req)
        body = req.get_json(silent=True) or {}
        brand_id = body.get("brandId")
        patch = body.get("patch") or {}
        if not brand_id or not isinstance(patch, dict):
            return https_fn.Response(json.dumps({"error": "brandId + patch required"}), status=400, mimetype="application/json")
        _require_brand_member(uid, brand_id)

        safe = {k: v for k, v in patch.items() if k in _BRAND_EDITABLE_FIELDS}
        if not safe:
            return https_fn.Response(json.dumps({"error": "no editable fields in patch"}), status=400, mimetype="application/json")

        # Hashtag pool edits go to a subcollection — caller passes a separate
        # `hashtagPool: [{tag, platform, priority, active}]` payload if needed.
        from google.cloud.firestore import SERVER_TIMESTAMP
        safe["updatedAt"] = SERVER_TIMESTAMP
        safe["updatedBy"] = uid
        fs.brand_doc(brand_id).set(safe, merge=True)

        # Optional hashtag pool patch
        pool = body.get("hashtagPool")
        if isinstance(pool, list):
            existing = {d.id: d for d in fs.hashtag_pool_col(brand_id).stream()}
            seen = set()
            for h in pool:
                tag = (h.get("tag") or "").strip().lower().lstrip("#")
                platform = h.get("platform") or "instagram"
                if not tag:
                    continue
                doc_id = f"{platform}_{tag}"
                seen.add(doc_id)
                fs.hashtag_pool_col(brand_id).document(doc_id).set({
                    "tag": tag,
                    "platform": platform,
                    "priority": int(h.get("priority", 5)),
                    "active": bool(h.get("active", True)),
                }, merge=True)
            # Optionally remove tags the client says are gone (body.replaceHashtags)
            if body.get("replaceHashtags") is True:
                for doc_id, doc in existing.items():
                    if doc_id not in seen:
                        doc.reference.delete()

        return https_fn.Response(json.dumps({"ok": True, "patched": list(safe.keys())}), status=200, mimetype="application/json")
    except https_fn.HttpsError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=400, mimetype="application/json")
    except Exception as e:
        log.exception("brand_settings_update failed")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


@https_fn.on_request(cors=CORS_POST, memory=options.MemoryOption.MB_512, timeout_sec=120)
def api_recompute_centroid(req: https_fn.Request) -> https_fn.Response:
    """Recompute the brand visual centroid from current reference images.
    Called after the user uploads/removes a reference image."""
    if req.method == "OPTIONS":
        return https_fn.Response("", status=204)
    if req.method != "POST":
        return https_fn.Response("Method not allowed", status=405)
    try:
        uid = _require_auth(req)
        body = req.get_json(silent=True) or {}
        brand_id = body.get("brandId")
        if not brand_id:
            return https_fn.Response(json.dumps({"error": "brandId required"}), status=400, mimetype="application/json")
        _require_brand_member(uid, brand_id)
        from lib import embedding
        centroid, diag = embedding.compute_centroid(brand_id)
        return https_fn.Response(
            json.dumps({
                "ok": True,
                "computed": centroid is not None,
                "dims": len(centroid) if centroid else 0,
                "refsFound": diag.get("refsFound", 0),
                "refsUsed": diag.get("refsUsed", 0),
                "fetchErrors": diag.get("fetchErrors", []),
                "embedErrors": diag.get("embedErrors", 0),
            }),
            status=200, mimetype="application/json",
        )
    except https_fn.HttpsError as e:
        return https_fn.Response(json.dumps({"error": str(e)}), status=400, mimetype="application/json")
    except Exception as e:
        log.exception("recompute_centroid failed")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")
