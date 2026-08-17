#!/usr/bin/env python3
"""Validate the batched multi-frame Gemini call against the per-frame path.

Two questions, both answered with real API calls and real token counts:

  1. AGREEMENT — does judging N frames in one request produce the same verdicts
     as N separate requests? Batching is only worth having if it does. A cost
     win that quietly changes detections is not a win.
  2. COST — the plan claims ~3.6x. Measured here from usage_metadata rather
     than assumed, because the repo's existing cost constants were already
     wrong by ~11x for Apify and ~23x for Gemini.

The golden images stand in for video frames. That is a fair proxy for the
mechanical question (does the response align, does it cost less) but NOT for
temporal reasoning — real frames from one clip share a scene, and the model may
behave differently when frames genuinely correlate. Called out rather than
glossed: this measures the plumbing, not video quality.

    python3 tools/eval/eval_batch.py               # 6-frame batch, mixed
    python3 tools/eval/eval_batch.py --frames 10
    python3 tools/eval/eval_batch.py --repeat 3    # check stability
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_eval import (  # noqa: E402  (also performs the Firestore stubbing)
    BRAND, FUNCTIONS, load_env, load_golden, load_references, detect,
)
from lib import gemini  # noqa: E402
from handlers.detect_image import _strictness_gate, _accept_variants  # noqa: E402

# lib/usage.py, corrected against the measured invoice in
# projects/spot-the-brand/operating-costs.md.
PRICE_IN = 0.30 / 1_000_000     # $/input token, gemini-2.5-flash
PRICE_OUT = 2.50 / 1_000_000    # $/output token
PRICE_CACHED = 0.075 / 1_000_000


def cost(u: dict) -> float:
    p = u.get("prompt_tokens") or 0
    c = u.get("cached_tokens") or 0
    o = u.get("output_tokens") or 0
    return (p - c) * PRICE_IN + c * PRICE_CACHED + o * PRICE_OUT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--recall", action="store_true",
                    help="batch every known positive and report how many survive")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--env", default=str(FUNCTIONS / ".env"))
    args = ap.parse_args()

    load_env(Path(args.env))
    if not (os.getenv("GOOGLE_AI_API_KEY") or os.getenv("GEMINI_API_KEY")):
        print("No GOOGLE_AI_API_KEY / GEMINI_API_KEY.", file=sys.stderr)
        return 2

    golden = load_golden()
    pos = [r for r in golden if r["truth"]]
    neg = [r for r in golden if not r["truth"]]
    refs_all = load_references()
    accept_all = _accept_variants(BRAND)

    if args.recall:
        # Does batching ever LOSE a genuine can? That decides whether batching
        # can be used as a cheap first-pass screen: a screen may over-flag (a
        # second unbatched call settles it) but it must never under-flag,
        # because a frame it drops is never looked at again.
        print(f"BATCH RECALL — {len(pos)} known positives in batches of {args.frames}\n")
        found = 0
        for start in range(0, len(pos), args.frames):
            chunk = pos[start:start + args.frames]
            fr = [(i, r["path"].read_bytes()) for i, r in enumerate(chunk)]
            u: dict = {}
            raw = gemini.detect_frames_batch(
                fr, BRAND["name"], BRAND["productLines"],
                reference_image_bytes=refs_all, model=args.model, usage_out=u)
            for r, x in zip(chunk, raw):
                g = _strictness_gate(dict(x), accept_variants=accept_all)
                ok = bool(g.get("detected"))
                found += ok
                if not ok:
                    print(f"  LOST {r['file']:24} gate={g.get('gate') or '-':26} "
                          f"visible_text={(x.get('visible_text') or '')[:34]!r}")
        print(f"\n  batched recall {found}/{len(pos)} = {found / len(pos):.3f}   "
              f"(per-frame path is 1.000)")
        return 0
    # Mirror a real video: a couple of frames where the can is visible, the
    # rest where it is not. An all-positive batch would not test whether one
    # frame's wordmark leaks into its neighbours' verdicts — the single most
    # likely way batching could go wrong.
    n_pos = max(1, args.frames // 3)
    picked = pos[:n_pos] + neg[: args.frames - n_pos]
    refs = load_references()
    accept = _accept_variants(BRAND)

    print(f"model={args.model}  frames={len(picked)}  refs={len(refs)}  "
          f"({n_pos} truly positive)\n")

    # ── Per-frame baseline (cached from run_eval; costs nothing to reuse) ──
    single: list[bool] = []
    for r in picked:
        res = _strictness_gate(dict(detect(r, refs, args.model, use_cache=True)), accept_variants=accept)
        single.append(bool(res.get("detected")))

    frames = [(i, r["path"].read_bytes()) for i, r in enumerate(picked)]

    agree_runs, batch_costs = [], []
    for run_i in range(args.repeat):
        u: dict = {}
        try:
            raw = gemini.detect_frames_batch(
                frames, BRAND["name"], BRAND["productLines"],
                reference_image_bytes=refs, model=args.model, usage_out=u,
            )
        except Exception as e:
            print(f"  run {run_i}: BATCH FAILED — {e}")
            print("  (production falls back to per-frame calls on this path)")
            return 1

        batched = [bool(_strictness_gate(dict(x), accept_variants=accept).get("detected"))
                   for x in raw]
        agree = sum(1 for a, b in zip(single, batched) if a == b)
        agree_runs.append(agree)
        batch_costs.append(cost(u))

        print(f"  run {run_i}: agreement {agree}/{len(picked)}   "
              f"tokens in={u.get('prompt_tokens')} cached={u.get('cached_tokens')} "
              f"out={u.get('output_tokens')}   ${cost(u):.5f}")
        if agree != len(picked):
            for k, (r, a, b) in enumerate(zip(picked, single, batched)):
                if a != b:
                    print(f"      DISAGREE frame {k} {r['file']:24} "
                          f"truth={'STELZ' if r['truth'] else 'none':5} "
                          f"single={a} batched={b}")
                    print(f"        batched visible_text="
                          f"{(raw[k].get('visible_text') or '')[:50]!r} "
                          f"conf={raw[k].get('confidence')}")

    # ── Per-frame cost, measured on ONE uncached call ─────────────────────
    probe: dict = {}
    single_raw = gemini.detect_frames_batch(
        frames[:1], BRAND["name"], BRAND["productLines"],
        reference_image_bytes=refs, model=args.model, usage_out=probe,
    )
    _ = single_raw
    per_frame_cost = cost(probe)
    n = len(picked)
    avg_batch = sum(batch_costs) / len(batch_costs)

    print(f"\n{'=' * 64}")
    print(f"AGREEMENT   {sum(agree_runs)}/{n * args.repeat} frame verdicts matched the per-frame path")
    print(f"\nCOST for a {n}-frame video")
    print(f"  per-frame path   {n} x ${per_frame_cost:.5f} = ${per_frame_cost * n:.5f}")
    print(f"  batched path     ${avg_batch:.5f}")
    if avg_batch > 0:
        print(f"  saving           {per_frame_cost * n / avg_batch:.2f}x "
              f"(${per_frame_cost * n - avg_batch:.5f} per video)")
    print(f"\n  marginal cost of one extra frame once batched: "
          f"~${(avg_batch - per_frame_cost) / max(1, n - 1):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
