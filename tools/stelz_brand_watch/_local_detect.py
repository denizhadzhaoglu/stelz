"""The Stëlz detection, run locally over an archive, the way production runs it.

Imported by 64_stories_analyse.py, 70_tiktok_archive.py's analyser and
71_ig_posts_archive.py's, so there is ONE local opinion about what counts as a
Stëlz sighting instead of three that drift apart.

WHY THIS FILE EXISTS AT ALL. The first version of the local analyser inlined
its own video path and got it wrong in a way that produced silent misses:

    verdicts = gemini.detect_frames_batch(frames, ...)   # <- taken as final

That call is not a verdict in production. handlers/detect_video.py uses it as a
deliberately GENEROUS screen (`screen_flags_frame`, whose own docstring says
"over-flagging costs one extra Gemini call, while under-flagging drops a frame
nothing ever looks at again") and then runs a FULL detect_image on every frame
the screen flags, at full resolution, against the references. Judging a video
on the screen alone is the cheap half of a two-stage decision, and it is
exactly the half that misses a can that is small in one frame of twelve.

So: everything here is imported from the handlers rather than reimplemented.
Where this file has its own code it is because the local environment genuinely
differs — the reference images come from a directory instead of Firestore, and
moderator rejections come from a manifest instead of a ✕ button.

THE SAME MISTAKE, TWICE MORE. "Import the handler" is not the same as "call it
the way the handler is called", and both gaps produced wrong answers:

  * the first pass ran at up to 4096px because gemini.detect_image does not
    resize and detect_image.run does it at the CALL SITE. Local numbers
    flattered a deploy, and the verifier's "4x the pixel area" premise inverted;
  * the crop verdict overwrote the full-frame one unconditionally, so a box the
    model got wrong sent the second call at a patch of sky and its "nothing
    here" deleted the detection. Production had half of that guard; this file
    had none.

ONE REMAINING DIFFERENCE FROM PRODUCTION, stated rather than hidden: there is
no imageHashCache, so every run bills Gemini afresh.
"""
from __future__ import annotations

import io
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ROOT / "firebase" / "functions"
REFS_DIR = ROOT / "projects" / "stelz-brand-watch" / "web" / "public" / "refs"


def _stub_if_missing(name: str) -> types.ModuleType:
    """Stub ONLY what cannot be imported. cv2 and PIL are real here and must
    stay real — the eval harness stubs cv2 unconditionally, which would leave
    every video unanalysed while reporting success."""
    try:
        return __import__(name)
    except Exception:
        pass
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if "." in name:
        parent, _, child = name.rpartition(".")
        setattr(_stub_if_missing(parent), child, mod)
    return mod


def _bootstrap() -> None:
    """Make firebase/functions importable without a Firebase project."""
    if str(FUNCTIONS) not in sys.path:
        sys.path.insert(0, str(FUNCTIONS))
    for n in ("firebase_admin", "firebase_admin.firestore", "firebase_admin.storage",
              "google.cloud", "google.cloud.firestore", "google.cloud.pubsub_v1"):
        _stub_if_missing(n)
    fb = sys.modules["firebase_admin"]
    if not hasattr(fb, "initialize_app"):
        fb.initialize_app = lambda *a, **k: None
        fb.get_app = lambda *a, **k: None
        fb.credentials = types.SimpleNamespace(ApplicationDefault=lambda: None)
    fs_mod = sys.modules["google.cloud.firestore"]
    for attr, val in (("SERVER_TIMESTAMP", object()), ("Increment", lambda *a, **k: None),
                      ("ArrayUnion", lambda v: v), ("ArrayRemove", lambda v: v)):
        if not hasattr(fs_mod, attr):
            setattr(fs_mod, attr, val)


_bootstrap()

from lib import gemini, verifier                                    # noqa: E402
from handlers.detect_image import (                                   # noqa: E402
    _accept_variants, _strictness_gate, _resize, MAX_IMAGE_DIM,
)
from handlers.detect_video import _extract_frames, screen_flags_frame          # noqa: E402

# Re-exported so the analyser can select rows a verifier change can move without
# hard-coding the gate name a second time.
REOPENABLE_GATE = verifier.REOPENABLE_GATE

# Mirrors firebase/seed_brand.py, same as tools/eval/run_eval.py.
BRAND: dict[str, Any] = {
    "name": "STELZ",
    "slug": "stelz",
    "wordmarkAliases": ["stelz", "stélz", "stëlz"],
    "productLines": {
        "hard_lemonade": "Hard Lemonade",
        "hard_seltzer": "Hard Seltzer",
        "hard_iced_tea": "Hard Iced Tea",
        "mixed_classics": "Mixed Classics",
        "logo_only": "Logo / branding only",
        "zero_zero": "0.0 non-alcoholic",
    },
}

# From lib/usage.COST_PER_UNIT — used only to report the bill afterwards.
COST_IMAGE = 0.00175
COST_VIDEO = 0.00288
COST_VERIFY = 0.00330


def new_stats() -> dict[str, int]:
    return {"image_calls": 0, "video_calls": 0, "verify_calls": 0,
            "frames_extracted": 0, "frames_flagged": 0, "frames_analysed": 0}


def spend(stats: dict[str, int]) -> float:
    return (stats["image_calls"] * COST_IMAGE
            + stats["video_calls"] * COST_VIDEO
            + stats["verify_calls"] * COST_VERIFY)


def load_env() -> None:
    env = FUNCTIONS / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def have_key() -> bool:
    return bool(os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY"))


def warm() -> None:
    """Build the Gemini client on the main thread, before any worker starts.

    gemini.client() is now locked, so this is belt and braces rather than the
    fix — but it also means the first API error (a bad key, no network) is
    raised once, here, instead of separately inside every worker.
    """
    gemini.client()


# ─────────────────────────── references ───────────────────────────

# Hand-ordered, because the local directory carries no productLine metadata and
# alphabetical order is actively wrong here.
#
# lib/refs._select_reference_docs stratifies BY PRODUCT LINE first, precisely so
# the model is never shown eight cans of one flavour and left guessing at the
# rest. The local loader had no such rule: it sorted by filename and cut at 8,
# which put `web_stelz_logo.png` — the wordmark the detector is supposed to
# match on — at position 9, i.e. never sent. The model was being asked to
# recognise a brand while being shown everything except its logo.
#
# Names, not globs: a new file dropped into refs/ should not silently displace
# the logo again. Anything not listed fills the remaining slots alphabetically.
REF_PRIORITY = [
    "web_stelz_logo.png",     # the wordmark itself — never not first
    "web_group_13.png",       # Hard Iced Tea: lemon / mango / peach
    "web_group_132.png",
    "web_group_133.png",
    "web_hardlemonade.png",   # Hard Lemonade
    "stelz-nieuwe-smaak.jpg",
    "stelz-smaak-tobias.jpg",
    "web_lifestyle.png",      # in-hand, in-context — last, they teach the least
    "web_lifestyle2.png",
]
_REF_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def reference_files(max_count: int = 8) -> list[Path]:
    """Which reference photos the model gets, in order. Separate from the byte
    loading so a caller (and a test) can see the choice without paying for it."""
    if not REFS_DIR.is_dir():
        return []
    present = {p.name: p for p in REFS_DIR.iterdir()
               if p.is_file() and p.suffix.lower() in _REF_EXTS}
    ordered = [present[n] for n in REF_PRIORITY if n in present]
    ordered += [p for n, p in sorted(present.items()) if n not in REF_PRIORITY]
    return ordered[:max_count]


def _downscale(blob: bytes, max_dim: int = 512) -> bytes:
    """JPEG at most max_dim on the long edge. Returns the input unchanged if it
    cannot be decoded — a caller is sending this to Gemini either way, and a
    resize failure is not a reason to drop the image."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(blob))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_dim:
            s = max_dim / max(w, h)
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return blob


def load_references(max_count: int = 8) -> list[bytes]:
    """Reference packshots at 512px, matching lib/refs._MAX_DIM."""
    out: list[bytes] = []
    for p in reference_files(max_count):
        try:
            out.append(_downscale(p.read_bytes(), 512))
        except Exception as e:
            print(f"    ref skipped ({p.name}): {str(e)[:60]}")
    return out


# ──────────────────── confirmed false positives ────────────────────
#
# Production closes this loop through Firestore: a moderator clicks ✕, and
# refs.load_negative_exemplars feeds that image back into the verify prompt as a
# LABELLED negative. Locally there is no moderator UI, so the same loop runs off
# a manifest — negatives.json is committed, the images are not (they are other
# people's photos; same rule as tools/eval/golden_sources.json).
#
# Every entry here is an image checked by eye at native resolution and confirmed
# to contain no Stelz.

NEGATIVES_MANIFEST = Path(__file__).with_name("negatives.json")
NEGATIVES_DIR = ROOT / ".tmp" / "negatives"


def load_negatives(limit: int = 4) -> list[tuple[str, bytes]]:
    """Labelled counter-examples for the verify prompt, or [] if unavailable.

    Returns (label, bytes) PAIRS via verifier.build_negative_exemplars — never
    bare bytes. That signature is load-bearing: the legacy stack emitted these
    same images as unlabelled "Reference {i}:" parts and so taught the detector
    that twelve confirmed false positives WERE the brand.
    """
    import json as _json

    if not NEGATIVES_MANIFEST.exists():
        return []
    try:
        entries = _json.loads(NEGATIVES_MANIFEST.read_text()).get("rejected", [])
    except Exception as e:
        print(f"    negatives manifest unreadable ({str(e)[:60]}) — running without")
        return []
    rows: list[dict] = []
    for e in entries:
        p = NEGATIVES_DIR / (e.get("file") or "")
        if not p.exists():
            continue
        # 512px, matching the thumbnails production pulls from Firestore. A
        # counter-example only has to be recognisable as the same object; at
        # native resolution one of these is a megabyte of prompt per call.
        rows.append({
            "imageBytes": _downscale(p.read_bytes(), 512),
            "visibleText": e.get("hallucinatedText"),
            "highSignal": bool(e.get("highSignal")),
        })
    return verifier.build_negative_exemplars(rows, BRAND["name"], limit=limit)


# ─────────────────────────── one image ───────────────────────────

def _verify(result: dict, image_bytes: bytes, refs: list[bytes], stats: dict) -> dict:
    """Second look at a demoted hit, mirroring detect_image._verify_pass.

    A failure degrades to the original verdict, never to a deletion: the
    verifier can only act on evidence it actually obtained.
    """
    if not verifier.should_verify(result):
        return result
    try:
        negatives = load_negatives()
        verdict = gemini.verify_brand(
            _resize(image_bytes, verifier.VERIFY_MAX_DIM),
            BRAND["name"],
            reference_image_bytes=refs,
            negative_exemplars=negatives,
            model="gemini-2.5-flash",
        )
        stats["verify_calls"] += 1
        box = verdict.get("box_2d")
        if verifier.needs_crop(box):
            crop = verifier.crop_to_box(image_bytes, box)
            if crop:
                refined = gemini.verify_brand(
                    crop, BRAND["name"], reference_image_bytes=refs,
                    negative_exemplars=negatives, model="gemini-2.5-flash",
                )
                stats["verify_calls"] += 1
                # Same guard as detect_image._verify_pass, and it was missing
                # here entirely: the crop replaced the full-frame verdict
                # unconditionally, so a box that landed on sky deleted a
                # detection the full frame had read correctly.
                if verifier.crop_supersedes(refined):
                    verdict = refined
        return verifier.decide(result, verdict, brand_slug=BRAND["slug"])
    except Exception as e:
        print(f"    verifier failed, keeping first verdict: {str(e)[:70]}")
        return result


# What the FIRST pass sees, on the long edge. PROD is what the deployed function
# uses (handlers.detect_image.MAX_IMAGE_DIM); 0 means "send it as archived".
#
# This is a real lever, not a knob. Measured on the Lowlands TikTok archive,
# re-judging every finding at PROD instead of native resolution lost three
# sightings that are plainly Stelz to the eye: @niekroozen's poolside sign read
# "STELZ" at 0.95 and became nothing, @booijagency's frame 7 read "STELZ HARD
# SELTZER ALCOHOL INFUSED SPARKLING" and became nothing, @eloisevoranje's
# parasol likewise. Video frames arrive at the clip's own resolution — cv2
# encodes them straight out of the decoder — so a 1080x1920 frame loses about
# 93% of its pixels on the way in, and a wordmark that was 40px wide becomes 19.
#
# Not changed in production here: MAX_IMAGE_DIM applies to every image the
# pipeline has ever seen, and raising it is a cost decision for the account
# owner, not a detail of this archive. It is recorded in each verdict instead,
# so a number can always be traced to the resolution that produced it.
PROD_MAX_DIM = MAX_IMAGE_DIM
_max_dim = PROD_MAX_DIM


def set_max_dim(value: int) -> None:
    """Set the first-pass resolution for this process. 0 disables downscaling."""
    global _max_dim
    _max_dim = int(value)


def current_max_dim() -> int:
    return _max_dim


def _first_pass_bytes(image_bytes: bytes) -> bytes:
    return image_bytes if _max_dim <= 0 else _resize(image_bytes, _max_dim)


def judge_image(image_bytes: bytes, refs: list[bytes], stats: dict,
                source: str = "cover") -> dict:
    """One image through the full production cascade: model → gate → verifier.

    The returned dict carries `raw_detected` alongside the final answer. That
    is what makes a near miss visible: a frame the model called a hit and the
    gate or verifier overturned is NOT the same thing as a frame with nothing
    in it, and the UI has no way to tell them apart unless it is recorded here.
    """
    # 512px, because that is what production sends. gemini.detect_image does
    # NOT resize — detect_image.run does it at the call site — so passing the
    # archived bytes straight through was quietly running the first pass at up
    # to 4096px. Two problems with that: the local numbers would flatter what
    # the deployed function will actually see, and the verifier's whole premise
    # ("this pass looks at 4x the pixel area of the first") stops being true.
    #
    # It also failed outright. One 3072x4096 progressive JPEG came back as an
    # empty object every single time at full size and parsed cleanly at 512.
    res = gemini.detect_image(
        image_url="", image_bytes=_first_pass_bytes(image_bytes),
        brand_name=BRAND["name"], product_lines=BRAND["productLines"],
        reference_image_bytes=refs,
    )
    stats["image_calls"] += 1
    raw_detected = bool(res.get("detected"))
    res = _strictness_gate(res, accept_variants=_accept_variants(BRAND))
    res = _verify(res, image_bytes, refs, stats)
    res["raw_detected"] = raw_detected
    res["source"] = source
    return res


# ─────────────────────────── one video ───────────────────────────

def judge_video(video_bytes: bytes, refs: list[bytes], stats: dict,
                on_note: Callable[[str], None] = print) -> list[dict]:
    """Every sampled frame of one video, the two-stage way production does it.

    Stage 1 — one batched call over all frames. Stage 2 — a FULL detect_image on
    each frame `screen_flags_frame` flags, at full resolution. Skipping stage 2
    is what made the first version of this analyser under-report; the screen is
    tuned to let ~21% through precisely so a real look can follow.

    Frames the screen clears are returned as misses WITHOUT a second call, which
    is also what production does — that is where the saving comes from.
    """
    frames, info = _extract_frames(video_bytes)
    if not frames:
        if info.get("open_failed") or info.get("cv2_error"):
            on_note(f"    video unreadable: {info}")
        return []
    stats["frames_extracted"] += len(frames)

    try:
        screened = gemini.detect_frames_batch(
            frames, brand_name=BRAND["name"],
            product_lines=BRAND["productLines"], reference_image_bytes=refs,
        )
        stats["video_calls"] += 1
        variants = _accept_variants(BRAND)
        flags = [screen_flags_frame(v, variants) for v in screened]
    except Exception as e:
        # Same failure policy as detect_video: analyse EVERY frame rather than
        # lose one. The screen can only ever save work, never lose evidence.
        on_note(f"    frame screen failed, analysing all frames: {str(e)[:70]}")
        screened = [{} for _ in frames]
        flags = [True] * len(frames)

    out: list[dict] = []
    for (idx, jpeg), flagged, screen_res in zip(frames, flags, screened):
        if not flagged:
            out.append({
                "detected": False, "confidence": 0.0,
                "context": screen_res.get("context"),
                "raw_detected": False, "source": f"frame{idx}", "screened_out": True,
            })
            continue
        stats["frames_flagged"] += 1
        try:
            res = judge_image(jpeg, refs, stats, source=f"frame{idx}")
            stats["frames_analysed"] += 1
            out.append(res)
        except Exception as e:
            on_note(f"    frame {idx} failed: {str(e)[:70]}")
    return out


# ─────────────────────────── the verdict ───────────────────────────

def strongest(results: list[dict]) -> dict:
    """Same rule the UI uses: a hit anywhere beats a miss everywhere, and among
    hits the most confident one represents the item.

    A NEAR MISS outranks a plain miss. Otherwise the one frame where the model
    saw a can and the verifier said no would be represented by an empty frame of
    grass, and the whole reason to keep near misses would be lost on the way to
    the screen.
    """
    if not results:
        return {}
    hits = [r for r in results if r.get("detected")]
    if hits:
        return max(hits, key=lambda r: r.get("confidence") or 0)
    near = [r for r in results if r.get("raw_detected")]
    pool = near or results
    return max(pool, key=lambda r: r.get("confidence") or 0)


def verdict_record(item_id: str, handle: str, results: list[dict],
                   frames_extracted: int = 0, duration_s: float | None = None) -> dict:
    """The row written to verdicts.jsonl, in the shape the fixture reads."""
    best = strongest(results)
    detected = bool(best.get("detected"))
    # Raw hit anywhere, final hit nowhere. The reason is whatever overturned it:
    # the verifier if it spoke, otherwise the strictness gate.
    near = (not detected) and any(r.get("raw_detected") for r in results)
    return {
        "item_id": item_id,
        "story_id": item_id,   # back-compat: 61/72 key verdicts by story id
        "handle": handle,
        "detected": detected,
        "near_miss": near,
        "near_miss_reason": (best.get("verify_reason") or best.get("gate")) if near else None,
        "confidence": best.get("confidence"),
        "product_line": best.get("product_line"),
        "size_in_frame": best.get("size_in_frame"),
        "is_primary_subject": best.get("is_primary_subject"),
        "surface_type": best.get("surface_type"),
        "visible_text": best.get("visible_text"),
        "context": best.get("context"),
        "gate": best.get("gate"),
        "verify_verdict": best.get("verify_verdict"),
        "verify_brand": best.get("verify_brand"),
        "verify_reason": best.get("verify_reason"),
        # Where the wordmark was, when it was not on a can: signage, merchandise,
        # clothing. A branded bar front is a placement a brand paid for, and the
        # screen should say which kind it was rather than flatten it into "hit".
        "verify_placement": best.get("verify_placement"),
        "false_positive_risk": best.get("false_positive_risk"),
        "people_count": best.get("people_count"),
        "setting": best.get("setting"),
        "activity": best.get("activity"),
        "judged_from": best.get("source"),
        "frames_judged": len(results),
        # How many of those got a real look rather than only the screen. Without
        # it "13 beelden bekeken" overstates what happened by about five times.
        "frames_analysed": sum(1 for r in results if not r.get("screened_out")),
        "frames_extracted": frames_extracted or len(results),
        "video_seconds": duration_s,
        # The resolution the first pass actually saw. Without it a hit count
        # cannot be compared with another run, and the gap between local and
        # deployed results has no visible cause.
        "max_dim": current_max_dim(),
    }
