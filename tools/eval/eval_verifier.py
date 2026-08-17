"""Does the second-look verifier actually help? Measure it before deploying it.

Runs the real lib/verifier decision path over the labelled golden set, on top of
the CACHED first-pass responses (tools/eval/.cache), so only the verifier itself
costs anything. Verdicts are cached to .verify-cache/ too — a re-run is free.

The acceptance bar, from the plan:
    no loss on the true positives, and both surviving false positives rejected.

That is a 14-row test. It cannot prove production behaviour. What it CAN do is
catch the failure this feature is most likely to have — a verifier that deletes
genuine cans — before it touches live data. A change that cannot clear 14 rows
will not clear 5,000.

Usage:
    python3 tools/eval/eval_verifier.py            # cached, free
    python3 tools/eval/eval_verifier.py --no-cache # re-bill every call
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "firebase" / "functions"))

# Load the API key the same way the functions runtime does, without echoing it.
_envfile = REPO / "firebase" / "functions" / ".env"
if _envfile.exists():
    for line in _envfile.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import run_eval  # noqa: E402
from lib import gemini, verifier  # noqa: E402
from handlers import detect_image  # noqa: E402

VCACHE = HERE / ".verify-cache"
MODEL = "gemini-2.5-flash"


def first_pass(row, refs, prompt_id, refs_id, variants):
    """Cached first-pass result + gate, or None if not in the cache."""
    img = row["path"].read_bytes()
    key = hashlib.sha256(
        f"{hashlib.sha256(img).hexdigest()}|{MODEL}|{prompt_id}|{refs_id}".encode()
    ).hexdigest()[:24]
    cf = HERE / ".cache" / f"{key}.json"
    if not cf.exists():
        return None
    return detect_image._strictness_gate(json.loads(cf.read_text()), accept_variants=variants)


def verify(row, img_bytes, refs, use_cache: bool, calls: list):
    """One verifier pass over an image, disk-cached by (image, prompt, version)."""
    key = hashlib.sha256(
        f"{hashlib.sha256(img_bytes).hexdigest()}|{MODEL}|v{verifier.VERIFY_VERSION}"
        f"|{hashlib.sha256(verifier.build_prompt('STELZ').encode()).hexdigest()[:8]}".encode()
    ).hexdigest()[:24]
    cf = VCACHE / f"{key}.json"
    if use_cache and cf.exists():
        return json.loads(cf.read_text())
    out = gemini.verify_brand(img_bytes, "STELZ", reference_image_bytes=refs, model=MODEL)
    calls.append(1)
    VCACHE.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    refs = run_eval.load_references()
    rows = run_eval.load_golden(include_extended=True)
    prompt_id = hashlib.sha256(gemini.DETECT_PROMPT_V8.encode()).hexdigest()[:8]
    refs_id = hashlib.sha256(b"".join(refs)).hexdigest()[:8]
    variants = detect_image._accept_variants({"slug": "stelz", "wordmarkAliases": []})

    calls: list[int] = []
    records = []
    for row in rows:
        result = first_pass(row, refs, prompt_id, refs_id, variants)
        if result is None or not result.get("detected"):
            continue  # the verifier only ever sees accepted hits
        rec = {
            "file": row["file"], "truth": row["truth"], "slice": row["slice"],
            "before_detected": True, "before_conf": float(result.get("confidence") or 0),
            "verified": False, "verdict": None, "brand": None,
            "after_detected": True, "after_conf": float(result.get("confidence") or 0),
        }
        if verifier.should_verify(result):
            rec["verified"] = True
            img = row["path"].read_bytes()
            v = verify(row, detect_image._resize(img, verifier.VERIFY_MAX_DIM), refs,
                       not args.no_cache, calls)
            box = v.get("box_2d")
            if verifier.needs_crop(box):
                crop = verifier.crop_to_box(img, box)
                if crop:
                    refined = verify(row, detect_image._resize(crop, verifier.VERIFY_MAX_DIM),
                                     refs, not args.no_cache, calls)
                    if refined.get("brand") not in (None, "", "no_readable_brand"):
                        v = refined
                        rec["from_crop"] = True
            after = verifier.decide(result, v, brand_slug="stelz")
            rec["verdict"] = after.get("verify_verdict")
            rec["brand"] = after.get("verify_brand")
            rec["after_detected"] = bool(after.get("detected"))
            rec["after_conf"] = float(after.get("confidence") or 0)
        records.append(rec)

    def stats(key):
        kept = [r for r in records if r[key]]
        t = sum(r["truth"] for r in kept)
        return len(kept), t, len(kept) - t

    bn, bt, bf = stats("before_detected")
    an, at, af = stats("after_detected")

    print(f"\naccepted by the gate: {bn}  (true={bt} false={bf})")
    print(f"verifier ran on:      {sum(r['verified'] for r in records)}")
    print(f"new Gemini calls:     {len(calls)}  (${len(calls) * 0.0033:.3f})\n")

    def prec(n, t):
        return f"{t}/{n} = {t / n * 100:.0f}%" if n else "n/a"

    print(f"  BEFORE  kept={bn:2}  precision {prec(bn, bt)}")
    print(f"  AFTER   kept={an:2}  precision {prec(an, at)}")

    lost = [r for r in records if r["truth"] and r["before_detected"] and not r["after_detected"]]
    killed = [r for r in records if not r["truth"] and r["before_detected"] and not r["after_detected"]]
    upgraded = [r for r in records if r["verdict"] == "upgraded"]

    print(f"\n  false positives removed: {len(killed)}/{bf}")
    print(f"  true positives LOST:     {len(lost)}/{bt}   <- must be 0")
    print(f"  true positives upgraded out of the review band: "
          f"{sum(1 for r in upgraded if r['truth'])}")

    print("\n--- every verified row ---")
    for r in sorted(records, key=lambda r: (not r["verified"], r["truth"])):
        if not r["verified"]:
            continue
        flag = "  " if r["truth"] == r["after_detected"] else "!!"
        print(f" {flag} {'TRUE ' if r['truth'] else 'FALSE'} {r['file']:22} "
              f"{str(r['verdict']):13} brand={str(r['brand']):18} "
              f"conf {r['before_conf']:.2f}->{r['after_conf']:.2f}"
              f"{'  [crop]' if r.get('from_crop') else ''}")

    ok = not lost and len(killed) == bf
    print(f"\nACCEPTANCE: {'PASS' if ok else 'FAIL'}"
          f"  (no true positives lost, all {bf} false positives removed)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
