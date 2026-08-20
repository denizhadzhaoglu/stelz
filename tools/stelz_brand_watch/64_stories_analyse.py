#!/usr/bin/env python3
"""Run the real Stëlz detection over the archived stories, without a deploy.

The detection normally runs in a Cloud Function this machine cannot deploy to.
It does not have to: gemini.detect_image() takes image bytes directly (the path
the eval harness already uses), the reference photos live in the repo, and the
archive holds the images. So the same prompt, the same references and the same
_strictness_gate that run in production run here, over .tmp/stories-archive.

    ./firebase/functions/venv/bin/python \\
        tools/stelz_brand_watch/64_stories_analyse.py            # analyse all
        ... --limit 5                                            # try a few first
        ... --covers-only                                        # skip video frames

Resumable and idempotent: verdicts land in .tmp/stories-archive/verdicts.jsonl
and an already-judged story is never paid for twice. Then run
61_stories_preview_fixture.py to see the verdicts on /stories.

WHAT THIS IS NOT: production. Two deliberate differences, both stated in the
output rather than hidden —
  * no imageHashCache, so every run bills Gemini afresh (~$0.23 for 69);
  * no negative exemplars in the verifier pass, because the moderator's
    rejections live in Firestore. The verifier still runs, with a smaller
    evidence base than it would have in production.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ROOT / "firebase" / "functions"
sys.path.insert(0, str(FUNCTIONS))


def _stub_if_missing(name: str) -> types.ModuleType:
    """Stub ONLY what cannot be imported. cv2 and PIL are real here and must
    stay real — the eval harness stubs cv2 unconditionally, which would leave
    every video story unanalysed."""
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


for _n in ("firebase_admin", "firebase_admin.firestore", "firebase_admin.storage",
           "google.cloud", "google.cloud.firestore", "google.cloud.pubsub_v1"):
    _stub_if_missing(_n)
_fb = sys.modules["firebase_admin"]
if not hasattr(_fb, "initialize_app"):
    _fb.initialize_app = lambda *a, **k: None
    _fb.get_app = lambda *a, **k: None
    _fb.credentials = types.SimpleNamespace(ApplicationDefault=lambda: None)
_fs = sys.modules["google.cloud.firestore"]
for _attr, _val in (("SERVER_TIMESTAMP", object()), ("Increment", lambda *a, **k: None),
                    ("ArrayUnion", lambda v: v), ("ArrayRemove", lambda v: v)):
    if not hasattr(_fs, _attr):
        setattr(_fs, _attr, _val)

from lib import gemini, verifier  # noqa: E402
from handlers.detect_image import _accept_variants, _strictness_gate, _resize  # noqa: E402
from handlers.detect_video import _extract_frames  # noqa: E402

ARCHIVE = ROOT / ".tmp" / "stories-archive"
INDEX = ARCHIVE / "index.jsonl"
MEDIA = ARCHIVE / "media"
VERDICTS = ARCHIVE / "verdicts.jsonl"
REFS_DIR = ROOT / "projects" / "stelz-brand-watch" / "web" / "public" / "refs"

# Mirrors firebase/seed_brand.py, same as tools/eval/run_eval.py.
BRAND = {
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

# From lib/usage.COST_PER_UNIT — kept here only to report the bill afterwards.
COST_IMAGE = 0.00175
COST_VIDEO = 0.00288
COST_VERIFY = 0.00330


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


def load_references(max_count: int = 8) -> list[bytes]:
    """Product packshots, newest-first, 512px — mirrors lib/refs.py so the model
    sees the same evidence it sees in production."""
    from PIL import Image
    import io

    exts = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    files = [p for p in sorted(REFS_DIR.iterdir()) if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: (0 if p.name.startswith(("web_", "stelz")) else 1, p.name))

    out: list[bytes] = []
    for p in files:
        if len(out) >= max_count:
            break
        try:
            img = Image.open(io.BytesIO(p.read_bytes()))
            if img.mode != "RGB":
                img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > 512:
                s = 512 / max(w, h)
                img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            out.append(buf.getvalue())
        except Exception as e:
            print(f"    ref skipped ({p.name}): {str(e)[:60]}")
    return out


def verify(result: dict, image_bytes: bytes, refs: list[bytes], stats: dict) -> dict:
    """Second look at a demoted hit, mirroring detect_image._verify_pass.

    Without the moderator's rejected examples (they live in Firestore), so the
    verifier works from a thinner evidence base than production. It can still
    only ever act on what it actually obtained: a failure degrades to the
    original verdict, never to a deletion.
    """
    if not verifier.should_verify(result):
        return result
    try:
        verdict = gemini.verify_brand(
            _resize(image_bytes, verifier.VERIFY_MAX_DIM),
            BRAND["name"],
            reference_image_bytes=refs,
            negative_exemplars=[],
            model="gemini-2.5-flash",
        )
        stats["verify_calls"] += 1
        box = verdict.get("box_2d")
        if verifier.needs_crop(box):
            crop = verifier.crop_to_box(image_bytes, box)
            if crop:
                verdict = gemini.verify_brand(
                    crop, BRAND["name"], reference_image_bytes=refs,
                    negative_exemplars=[], model="gemini-2.5-flash",
                )
                stats["verify_calls"] += 1
        return verifier.decide(result, verdict, brand_slug=BRAND["slug"])
    except Exception as e:
        print(f"    verifier failed, keeping first verdict: {str(e)[:70]}")
        return result


def strongest(results: list[dict]) -> dict:
    """Same rule the UI uses: a hit anywhere beats a miss everywhere, and among
    hits the most confident one represents the story."""
    if not results:
        return {}
    hits = [r for r in results if r.get("detected")]
    pool = hits or results
    return max(pool, key=lambda r: r.get("confidence") or 0)


def analyse(entry: dict, refs: list[bytes], covers_only: bool, stats: dict) -> dict:
    variants = _accept_variants(BRAND)
    results: list[dict] = []

    img_file = entry.get("image_file")
    if img_file and (MEDIA / img_file).exists():
        img = (MEDIA / img_file).read_bytes()
        res = gemini.detect_image(
            image_url="", image_bytes=img,
            brand_name=BRAND["name"], product_lines=BRAND["productLines"],
            reference_image_bytes=refs,
        )
        stats["image_calls"] += 1
        res = _strictness_gate(res, accept_variants=variants)
        res = verify(res, img, refs, stats)
        res["source"] = "cover"
        results.append(res)

    vid_file = entry.get("video_file")
    if vid_file and not covers_only and (MEDIA / vid_file).exists():
        frames, info = _extract_frames((MEDIA / vid_file).read_bytes())
        if frames:
            try:
                # ONE call for the whole video: the references are the expensive
                # part of the payload and batching sends them once.
                batch = gemini.detect_frames_batch(
                    frames, brand_name=BRAND["name"],
                    product_lines=BRAND["productLines"], reference_image_bytes=refs,
                )
                stats["video_calls"] += 1
                for (idx, fb), r in zip(frames, batch):
                    r = _strictness_gate(r, accept_variants=variants)
                    if r.get("detected"):
                        r = verify(r, fb, refs, stats)
                    r["source"] = f"frame{idx}"
                    results.append(r)
            except Exception as e:
                print(f"    video batch failed: {str(e)[:70]}")
        elif info.get("open_failed") or info.get("cv2_error"):
            print(f"    video unreadable: {info}")

    best = strongest(results)
    return {
        "story_id": entry["story_id"],
        "handle": entry["handle"],
        "detected": bool(best.get("detected")),
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
        "false_positive_risk": best.get("false_positive_risk"),
        "people_count": best.get("people_count"),
        "setting": best.get("setting"),
        "activity": best.get("activity"),
        "judged_from": best.get("source"),
        "frames_judged": len(results),
    }


def done_ids() -> set[str]:
    if not VERDICTS.exists():
        return set()
    out = set()
    for line in VERDICTS.read_text().splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["story_id"])
            except Exception:
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="analyse at most N new stories")
    ap.add_argument("--covers-only", action="store_true", help="skip video frames")
    args = ap.parse_args()

    load_env()
    if not (os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")):
        print("No Gemini key (GOOGLE_AI_API_KEY / GEMINI_API_KEY)")
        return 2
    if not INDEX.exists():
        print(f"No archive at {ARCHIVE.relative_to(ROOT)} — run 62_stories_archive.py first")
        return 2

    entries = [json.loads(l) for l in INDEX.read_text().splitlines() if l.strip()]
    already = done_ids()
    todo = [e for e in entries if e["story_id"] not in already]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(entries)} archived · {len(already)} already judged · {len(todo)} to analyse")
    if not todo:
        print("Nothing to do. Run 61_stories_preview_fixture.py to see the verdicts.")
        return 0

    refs = load_references()
    print(f"{len(refs)} reference images loaded from {REFS_DIR.relative_to(ROOT)}")
    est = len(todo) * COST_IMAGE + sum(
        COST_VIDEO for e in todo if e.get("video_file") and not args.covers_only)
    print(f"Estimated Gemini spend: ~${est:.2f} (plus verifier passes on demoted hits)\n")

    stats = {"image_calls": 0, "video_calls": 0, "verify_calls": 0}
    hits = 0
    with VERDICTS.open("a") as out:
        for i, e in enumerate(todo, 1):
            kind = "video" if (e.get("video_file") and not args.covers_only) else "photo"
            print(f"[{i}/{len(todo)}] @{e['handle']} {kind}", end=" ", flush=True)
            try:
                v = analyse(e, refs, args.covers_only, stats)
            except Exception as exc:
                # Never write a verdict we did not obtain: an unanalysed story is
                # honest, a fabricated miss is not. Left out of verdicts.jsonl so
                # the next run retries it.
                print(f"→ FAILED ({str(exc)[:60]})")
                continue
            out.write(json.dumps(v) + "\n")
            out.flush()
            if v["detected"]:
                hits += 1
                print(f"→ STËLZ {int((v['confidence'] or 0) * 100)}% "
                      f"({v.get('size_in_frame') or '?'}, {v.get('judged_from')})")
            else:
                print("→ no")

    spend = (stats["image_calls"] * COST_IMAGE + stats["video_calls"] * COST_VIDEO
             + stats["verify_calls"] * COST_VERIFY)
    print(f"\n{hits} of {len(todo)} contained Stëlz")
    print(f"Gemini: {stats['image_calls']} image · {stats['video_calls']} video · "
          f"{stats['verify_calls']} verify  =  ~${spend:.2f}")
    print("\nNow run 61_stories_preview_fixture.py and open")
    print("http://localhost:5180/stories?preview=stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
