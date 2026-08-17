#!/usr/bin/env python3
"""Run the NEW detection pipeline on your own images, with no Firebase.

Why this exists: nearly all of the detection work lives in Cloud Functions, so
it is invisible in the dashboard until someone deploys. This runs the exact
same code path locally — the real DETECT_PROMPT_V8, the real _strictness_gate,
the real typo/variant matching from lib/identity.py — against any image you
point it at, and shows you what the tool WOULD say.

What it does NOT do: scrape, write to Firestore, or touch the live project. It
reads an image, calls Gemini, prints the verdict. Costs about $0.002 per image.

    python3 tools/eval/try_detect.py photo.jpg
    python3 tools/eval/try_detect.py https://example.com/post.jpg
    python3 tools/eval/try_detect.py ~/Desktop/stelz/*.jpg
    python3 tools/eval/try_detect.py photo.jpg --explain   # show gate reasoning
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_eval import (  # noqa: E402  (also stubs Firestore so imports work)
    BRAND, FUNCTIONS, load_env, load_references,
)
from lib import gemini  # noqa: E402
from handlers.detect_image import _strictness_gate, _accept_variants  # noqa: E402

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
)

GATE_MEANING = {
    "capped_small_object": (
        "Brand read clearly, but the can was not dominant/large in frame, so "
        "confidence was capped at 0.70. In the dashboard this is HIDDEN by the "
        "default >=85% filter — use the '>= 70% (incl. gated)' chip to see it."
    ),
    "accepted_partial_wordmark": (
        "The wordmark was only partly readable (e.g. 'ST??Z'). Before this "
        "change the gate rejected every partial read, so this detection would "
        "have been thrown away."
    ),
    "rejected_no_brand_text": (
        "No standalone brand wordmark in the transcript. Prompt rule 1: shape, "
        "colour and 'vibes' are never enough."
    ),
    "rejected_fabricated_fine_print": (
        "Claimed to read fine print (calories/ml/ABV) off a label it had "
        "already called unreadable — the fabrication signature."
    ),
}


def load_bytes(src: str) -> bytes:
    if src.startswith(("http://", "https://")):
        import requests
        r = requests.get(src, timeout=30)
        r.raise_for_status()
        return r.content
    return Path(src).expanduser().read_bytes()


def resize(raw: bytes, max_edge: int = 1024) -> bytes:
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    img.load()
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_edge:
        s = max_edge / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", help="image files, globs, or URLs")
    ap.add_argument("--explain", action="store_true", help="show why the gate acted")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--env", default=str(FUNCTIONS / ".env"))
    args = ap.parse_args()

    load_env(Path(args.env))
    if not (os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")):
        print("No GOOGLE_AI_API_KEY / GEMINI_API_KEY found.", file=sys.stderr)
        return 2

    refs = load_references()
    accept = _accept_variants(BRAND)
    print(f"{DIM}model={args.model}  reference photos={len(refs)}  "
          f"accepted spellings={len(accept)}{OFF}")
    print(f"{DIM}accepts: {', '.join(accept)}{OFF}\n")

    hits = 0
    for src in args.images:
        name = Path(src).name if not src.startswith("http") else src[-40:]
        try:
            img = resize(load_bytes(src))
        except Exception as e:
            print(f"  {RED}!{OFF} {name}: {e}")
            continue

        try:
            raw = gemini.detect_image(
                image_url=src, brand_name=BRAND["name"],
                product_lines=BRAND["productLines"],
                reference_image_bytes=refs, model=args.model, image_bytes=img,
            )
        except Exception as e:
            print(f"  {RED}!{OFF} {name}: gemini call failed: {e}")
            continue

        res = _strictness_gate(dict(raw), accept_variants=accept)
        yes = bool(res.get("detected"))
        hits += yes
        conf = float(res.get("confidence") or 0)
        mark = f"{GREEN}STELZ{OFF}" if yes else f"{DIM}no stelz{OFF}"

        print(f"{BOLD}{name}{OFF}")
        print(f"   {mark}   confidence {conf:.2f}"
              + (f"  {DIM}(model said {raw.get('confidence')}){OFF}"
                 if raw.get("confidence") != res.get("confidence") else ""))
        print(f"   read on the can : {(res.get('visible_text') or '—')!r} "
              f"({res.get('text_legibility') or '—'})")
        print(f"   what it sees    : {res.get('context') or '—'}")
        print(f"   surface / size  : {res.get('surface_type') or '—'} / "
              f"{res.get('size_in_frame') or '—'}   product line: "
              f"{res.get('product_line') or '—'}")

        if res.get("matched_variant"):
            mv = res["matched_variant"]
            tag = "" if mv == "stelz" else f"  {YELLOW}<- typo variant{OFF}"
            print(f"   matched spelling: {mv}{tag}")
        if res.get("partialMatch"):
            print(f"   {YELLOW}partial read{OFF}: only "
                  f"{res.get('resolvedChars')} characters were actually legible")

        g = res.get("gate")
        if g:
            print(f"   gate            : {g}")
            if args.explain and g in GATE_MEANING:
                print(f"   {DIM}> {GATE_MEANING[g]}{OFF}")
        if yes and conf < 0.85:
            print(f"   {YELLOW}note{OFF}: below the dashboard's default 0.85 filter — "
                  f"this is the band that was invisible before.")
        print()

    print(f"{BOLD}{hits}/{len(args.images)} flagged as STELZ{OFF}")
    if not args.explain:
        print(f"{DIM}re-run with --explain to see why the gate acted as it did{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
