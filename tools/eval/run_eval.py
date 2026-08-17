#!/usr/bin/env python3
"""Offline evaluation harness for the Stelz visual detector.

Runs the REAL detection path — lib/gemini.DETECT_PROMPT_V8 plus
detect_image._strictness_gate — against a labelled golden set, and reports
precision / recall / F1 with a per-slice breakdown.

Why this exists: before it, there was no way to tell whether a prompt or gate
change helped or hurt. The repo's only ground truth (24 moderator-labelled
images) was sitting unused on disk.

The set is now those 24 plus hard negatives fetched by fetch_golden.py — run
that first, since the images are gitignored.

    export $(grep -v '^#' ../../firebase/functions/.env | xargs)   # or use --env
    python3 tools/eval/run_eval.py                    # full set, cached
    python3 tools/eval/run_eval.py --no-extended      # original 24 only
    python3 tools/eval/run_eval.py --slice party_scene
    python3 tools/eval/run_eval.py --no-cache         # force re-call
    python3 tools/eval/run_eval.py --limit 4          # smoke test

Responses are cached on disk keyed by (image sha256, model, prompt hash), so
sweeping thresholds after the first run costs nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FUNCTIONS = REPO / "firebase" / "functions"
REFS_DIR = REPO / "projects" / "stelz-brand-watch" / "reference-images"
TRAINING = REFS_DIR / "training"
HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / ".cache"
GOLDEN_DIR = HERE / "golden"
GOLDEN_SOURCES = HERE / "golden_sources.json"

sys.path.insert(0, str(FUNCTIONS))


# Import the REAL google namespace package (and google.genai) before stubbing
# anything under it. Creating a fake `google` module first would shadow the
# real namespace package and make `from google import genai` fail.
import google  # noqa: E402,F401  (import is load-bearing: populates sys.modules)
from google import genai as _real_genai  # noqa: E402,F401


# ── Stub the Firestore layer so we can import the real detection code ────────
def _stub(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if "." in name:
        parent, _, child = name.rpartition(".")
        setattr(_stub(parent), child, mod)
    return mod


for _n in (
    "cv2", "yt_dlp",
    "firebase_admin", "firebase_admin.firestore", "firebase_admin.storage",
    "google.cloud", "google.cloud.firestore", "google.cloud.pubsub_v1",
):
    _stub(_n)
_stub("firebase_admin").initialize_app = lambda *a, **k: None
_stub("firebase_admin").get_app = lambda *a, **k: None
_stub("firebase_admin").credentials = types.SimpleNamespace(ApplicationDefault=lambda: None)
_stub("google.cloud.firestore").SERVER_TIMESTAMP = object()
_stub("google.cloud.firestore").Increment = lambda *a, **k: None
_stub("google.cloud.firestore").ArrayUnion = lambda *a, **k: None

from lib import gemini  # noqa: E402
from handlers.detect_image import _strictness_gate, _accept_variants  # noqa: E402

# Mirrors firebase/seed_brand.py for the Stelz tenant.
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


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_references(max_count: int = 8) -> list[bytes]:
    """Product packshots only — never the training/ few-shot images, which are
    the eval set. Mirrors lib/refs.py: newest-first, resized to 512px."""
    from PIL import Image
    import io

    exts = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    files = [
        p for p in sorted(REFS_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in exts
    ]
    # Prefer explicit product shots over lifestyle/press images.
    files.sort(key=lambda p: (0 if p.name.startswith(("web_", "stelz")) else 1, p.name))

    out: list[bytes] = []
    for p in files[: max_count * 2]:
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
            print(f"  ! skipped reference {p.name}: {e}", file=sys.stderr)
    return out


def load_golden(include_extended: bool = True) -> list[dict]:
    """The labelled evaluation set, in two parts.

    `moderator_*` — the 24 images shipped in reference-images/training/, labelled
    by a human moderator against real production output. The only source of
    POSITIVES, so recall is measured entirely on these.

    `<class>` — hard negatives fetched by fetch_golden.py from openly-licensed
    stock (competitor seltzers, generic cans, party scenes, can-shaped
    non-products). Negative by construction; see that script's docstring.

    Since the extended slice is negatives-only, it can move precision but never
    recall. Run with --no-extended to reproduce the original 24-image numbers.
    """
    manifest = json.loads((TRAINING / "manifest.json").read_text())
    rows = []
    for label, key in (("positive", True), ("negative", False)):
        for e in manifest.get(label, []):
            p = TRAINING / e["file"]
            if p.exists():
                rows.append({
                    "file": e["file"],
                    "path": p,
                    "truth": key,
                    "slice": "moderator_pos" if key else "moderator_neg",
                    "note": e.get("moderator_verdict", ""),
                    "creator": e.get("creator"),
                    "high_signal": e.get("high_signal", False),
                    "prior_model_conf": (e.get("model_said") or {}).get("confidence"),
                    "verdict": e.get("moderator_verdict", ""),
                })

    if include_extended and GOLDEN_SOURCES.exists():
        for e in json.loads(GOLDEN_SOURCES.read_text()).get("items", []):
            if not e.get("keep"):
                continue
            p = GOLDEN_DIR / e["file"]
            if not p.exists():
                continue          # gitignored; run fetch_golden.py to rebuild
            rows.append({
                "file": e["file"],
                "path": p,
                "truth": bool(e.get("truth")),
                "slice": e["cls"],
                "note": e.get("note", ""),
                "creator": None,
                "high_signal": False,
                "prior_model_conf": None,
                "verdict": e.get("note", ""),
            })
    return rows


def detect(row: dict, refs: list[bytes], model: str, use_cache: bool) -> dict:
    img = row["path"].read_bytes()
    prompt_id = hashlib.sha256(gemini.DETECT_PROMPT_V8.encode()).hexdigest()[:8]
    refs_id = hashlib.sha256(b"".join(refs)).hexdigest()[:8]
    key = hashlib.sha256(
        f"{hashlib.sha256(img).hexdigest()}|{model}|{prompt_id}|{refs_id}".encode()
    ).hexdigest()[:24]
    cf = CACHE_DIR / f"{key}.json"

    if use_cache and cf.exists():
        res = json.loads(cf.read_text())
        res["_cached"] = True
        return res

    try:
        res = gemini.detect_image(
            image_url="",
            brand_name=BRAND["name"],
            product_lines=BRAND["productLines"],
            reference_image_bytes=refs,
            model=model,
            image_bytes=img,
        )
    except Exception as e:
        return {"detected": False, "confidence": 0.0, "context": f"error: {e}", "_error": True}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(res))
    res["_cached"] = False
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-gate", action="store_true", help="report raw model output, gate off")
    ap.add_argument("--no-extended", action="store_true",
                    help="original 24 moderator-labelled images only")
    ap.add_argument("--slice", default="", help="restrict to one slice, e.g. party_scene")
    ap.add_argument("--env", default=str(FUNCTIONS / ".env"))
    args = ap.parse_args()

    load_env(Path(args.env))
    if not (os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")):
        print("No GOOGLE_AI_API_KEY / GEMINI_API_KEY. Pass --env or export one.", file=sys.stderr)
        return 2

    golden = load_golden(include_extended=not args.no_extended)
    if args.slice:
        golden = [r for r in golden if r["slice"] == args.slice]
        if not golden:
            print(f"No images in slice {args.slice!r}.", file=sys.stderr)
            return 2
    if args.limit:
        # Keep the class balance when smoke-testing.
        pos = [r for r in golden if r["truth"]][: max(1, args.limit // 2)]
        neg = [r for r in golden if not r["truth"]][: max(1, args.limit // 2)]
        golden = pos + neg

    refs = load_references()
    accept = _accept_variants(BRAND)
    npos = sum(1 for r in golden if r["truth"])
    print(f"model={args.model}  golden={len(golden)} ({npos} pos / {len(golden) - npos} neg)  "
          f"refs={len(refs)}  gate={'off' if args.no_gate else 'on'}")
    print(f"accept variants ({len(accept)}): {', '.join(accept)}\n")

    rows = []
    for i, r in enumerate(golden, 1):
        res = detect(r, refs, args.model, use_cache=not args.no_cache)
        if not args.no_gate:
            res = _strictness_gate(dict(res), accept_variants=accept)
        pred = bool(res.get("detected"))
        rows.append({**r, "pred": pred, "res": res})
        mark = "ok " if pred == r["truth"] else "MISS" if r["truth"] else "FP  "
        cached = "·" if res.get("_cached") else " "
        print(f"  [{i:2}/{len(golden)}]{cached} {mark} {r['file']:22} "
              f"truth={'STELZ' if r['truth'] else 'none ':5} "
              f"pred={'STELZ' if pred else 'none ':5} "
              f"conf={res.get('confidence') or 0:.2f} gate={res.get('gate') or '-'}")

    tp = sum(1 for r in rows if r["truth"] and r["pred"])
    fn = sum(1 for r in rows if r["truth"] and not r["pred"])
    fp = sum(1 for r in rows if not r["truth"] and r["pred"])
    tn = sum(1 for r in rows if not r["truth"] and not r["pred"])
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    print(f"\n{'='*64}\nCONFUSION   TP={tp}  FN={fn}  FP={fp}  TN={tn}")
    print(f"PRECISION   {prec:.3f}   (of what we surface, how much is real)")
    print(f"RECALL      {rec:.3f}   (of real Stelz, how much we find)")
    print(f"F1          {f1:.3f}")

    if fn:
        print(f"\nMISSED {fn} genuine Stelz (recall loss — the client's complaint):")
        for r in rows:
            if r["truth"] and not r["pred"]:
                g = r["res"].get("gate") or "model said no"
                vt = (r["res"].get("visible_text") or "")[:40]
                print(f"  - {r['file']:22} gate={g:32} visible_text={vt!r}")
    if fp:
        print(f"\nFALSE POSITIVES {fp} (precision loss — junk in the feed):")
        for r in rows:
            if not r["truth"] and r["pred"]:
                res = r["res"]
                # model_* fields are the pre-gate values. Printing the post-gate
                # risk would be misleading: every capped hit reads "high" because
                # the gate stamps it, not because the model said so.
                print(f"  - {r['file']:26} [{r['slice']}] conf={res.get('confidence')} "
                      f"(model {res.get('model_confidence')}) "
                      f"risk={res.get('model_false_positive_risk')} gate={res.get('gate') or '-'}")
                print(f"      visible_text={(res.get('visible_text') or '')[:60]!r}")
                print(f"      context={(res.get('context') or '')[:90]!r}")

    # Per-slice breakdown. Overall precision says a number moved; this says
    # which failure mode moved it, which is the part you can act on.
    slices: dict[str, dict] = {}
    for r in rows:
        s = slices.setdefault(r["slice"], {"n": 0, "pred": 0, "truth": r["truth"], "conf": []})
        s["n"] += 1
        s["pred"] += 1 if r["pred"] else 0
        s["conf"].append(float(r["res"].get("confidence") or 0))
    print("\nPER-SLICE:")
    print(f"  {'slice':22} {'n':>3} {'truth':>6} {'said STELZ':>11} {'rate':>7}  {'max conf':>8}")
    for name, s in sorted(slices.items(), key=lambda x: (not x[1]["truth"], x[0])):
        rate = s["pred"] / s["n"] if s["n"] else 0.0
        good = "recall" if s["truth"] else "FP rate"
        print(f"  {name:22} {s['n']:>3} {'STELZ' if s['truth'] else 'none':>6} "
              f"{s['pred']:>11} {rate:>6.1%} {max(s['conf']):>9.2f}   ({good})")

    gates: dict[str, int] = {}
    for r in rows:
        g = r["res"].get("gate")
        if g:
            gates[g] = gates.get(g, 0) + 1
    if gates:
        print("\nGATE ACTIONS:")
        for g, n in sorted(gates.items(), key=lambda x: -x[1]):
            print(f"  {g:34} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
