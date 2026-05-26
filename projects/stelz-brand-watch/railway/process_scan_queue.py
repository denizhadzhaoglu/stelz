#!/usr/bin/env python3
"""Process pending manual-scan requests from the dashboard.

Workflow:
1. Picks the oldest 'pending' scan_request for STELZ (or any brand).
2. Marks it 'running'.
3. Captures pre-scan counters (creators, content_items, detections).
4. Runs the daily pipeline: auto_add -> daily_scan -> pro_verify.
5. Computes diff vs pre-scan counters -> stores in scan_requests.results.
6. Marks 'completed' (or 'failed' with error message).

Designed to run via cron every minute (or on-demand). The dashboard polls
scan_requests.status and surfaces the result to the user automatically.

Local usage:
    python3 tools/stelz_brand_watch/32_process_scan_queue.py            # process one pending
    python3 tools/stelz_brand_watch/32_process_scan_queue.py --loop     # poll forever
    python3 tools/stelz_brand_watch/32_process_scan_queue.py --max 5    # process up to 5
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")


def get_counts(sb, brand_id: str) -> dict:
    return {
        "creators": sb.table("creators").select("id", count="exact", head=True).eq("brand_id", brand_id).execute().count,
        "content_items": sb.table("content_items").select("id", count="exact", head=True).eq("brand_id", brand_id).execute().count,
        "detections": sb.table("detections").select("id", count="exact", head=True).eq("brand_id", brand_id).eq("detected", True).execute().count,
    }


def build_steps(scope: str):
    """Pipeline definition per scan scope.

    standard (25 cr):
      - auto_add (hashtag discovery, 150 posts per brand tag)
      - daily_scan (6h skip, 8 posts per creator, 5 parallel Apify batches)
      - pro_verify (verify any new Flash hits)

    deep (100 cr): bigger sweep, ignores recent-scrape skip, more posts per
      creator, also harvests TikTok hashtags. Used for catching up or
      re-baselining a brand.
    """
    if scope == "deep":
        return [
            {"key": "auto_add",   "label": "Discovering new creators (deep hashtag pass)",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/19_auto_add.py"), "--per-tag", "300"]},
            {"key": "daily_scan", "label": "Full IG sweep (no skip, 25 posts/creator)",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/18_daily_scan.py"),
                     "--skip-recent-hours", "0",
                     "--posts-per-creator", "25",
                     "--apify-concurrency", "6"]},
            {"key": "tiktok_scan", "label": "TikTok hashtag harvest",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/15_tiktok_harvest.py"),
                     "--per-tag", "150"]},
            {"key": "detect_pending", "label": "Flash detection on un-detected images (incl. TikTok thumbs)",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/33_detect_pending.py"),
                     "--concurrency", "20"]},
            {"key": "pro_verify", "label": "Pro verification of new hits",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/17_verify_with_pro.py"),
                     "--concurrency", "8"]},
        ]
    # default: standard scan
    return [
        {"key": "auto_add",   "label": "Adding new creators from hashtags",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/19_auto_add.py"), "--per-tag", "150"]},
        {"key": "daily_scan", "label": "Scraping latest posts + Flash detection",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/18_daily_scan.py")]},
        {"key": "pro_verify", "label": "Pro verification of new hits",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/17_verify_with_pro.py"), "--concurrency", "6"]},
    ]


# Backwards compat: some callers still reference STEPS directly.
STEPS = build_steps("standard")


def update_progress(sb, scan_id: str, progress: dict):
    """Write live progress to scan_requests so the dashboard can render it."""
    sb.table("scan_requests").update({"progress": progress}).eq("id", scan_id).execute()


def run_scan_chain(sb, scan_id: str, brand_id: str, scope: str = "standard") -> tuple[bool, str]:
    """Run pipeline and persist step-level progress to scan_requests.progress."""
    steps = build_steps(scope)
    steps_state = [
        {"key": s["key"], "label": s["label"], "status": "pending",
         "started_at": None, "completed_at": None, "log": None}
        for s in steps
    ]
    update_progress(sb, scan_id, {"current_step": None, "steps": steps_state})

    for idx, step in enumerate(steps):
        print(f"  --- {step['key']}", file=sys.stderr)
        steps_state[idx]["status"] = "running"
        steps_state[idx]["started_at"] = time.time()
        update_progress(sb, scan_id, {"current_step": step["key"], "steps": steps_state})

        # Capture pre-step counts so we can show "added during this step"
        pre = get_counts(sb, brand_id)
        steps_state[idx]["counts_before"] = pre

        # Run the step. 25-min timeout per step gives daily_scan room to
        # breathe even on bad-luck Apify days; with the parallel optimization
        # it normally finishes in 2-5 min.
        try:
            r = subprocess.run(step["cmd"], capture_output=True, text=True, timeout=25*60)
            if r.returncode != 0:
                steps_state[idx]["status"] = "failed"
                steps_state[idx]["log"] = (r.stderr or "")[-600:]
                update_progress(sb, scan_id, {"current_step": step["key"], "steps": steps_state})
                return False, f"{step['key']} failed: {(r.stderr or '')[-400:]}"
            # Grab the last few stderr lines as a tail-log
            tail = "\n".join((r.stderr or "").strip().splitlines()[-6:])
            steps_state[idx]["log"] = tail
        except subprocess.TimeoutExpired:
            steps_state[idx]["status"] = "failed"
            steps_state[idx]["log"] = "timeout after 20min"
            update_progress(sb, scan_id, {"current_step": step["key"], "steps": steps_state})
            return False, f"{step['key']} timeout"
        except Exception as e:
            steps_state[idx]["status"] = "failed"
            steps_state[idx]["log"] = f"crashed: {e}"
            update_progress(sb, scan_id, {"current_step": step["key"], "steps": steps_state})
            return False, f"{step['key']} crashed: {e}"

        post = get_counts(sb, brand_id)
        steps_state[idx]["counts_after"] = post
        steps_state[idx]["delta"] = {
            "creators":      post["creators"]      - pre["creators"],
            "content_items": post["content_items"] - pre["content_items"],
            "detections":    post["detections"]    - pre["detections"],
        }
        steps_state[idx]["status"] = "completed"
        steps_state[idx]["completed_at"] = time.time()
        update_progress(sb, scan_id, {"current_step": step["key"], "steps": steps_state})

    update_progress(sb, scan_id, {"current_step": None, "steps": steps_state})
    return True, ""


def process_expansion(sb) -> bool:
    """Pick and process one queued subculture expansion."""
    res = sb.rpc("claim_next_expansion", {}).execute()
    req = res.data
    if isinstance(req, list):
        req = req[0] if req else None
    if not req or not req.get("id"):
        return False
    exp_id = req["id"]
    print(f"\n=== Processing expansion {exp_id} ===", file=sys.stderr)
    cmd = ["python3", str(PA_ROOT / "tools/stelz_brand_watch/31_expand_subculture.py"),
           "--expansion-id", exp_id]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25*60)
        if r.returncode != 0:
            err = (r.stderr or "")[-400:]
            sb.table("subculture_expansions").update({
                "status": "failed",
                "completed_at": "now()",
                "notes": f"failed: {err}",
            }).eq("id", exp_id).execute()
            # refund
            try:
                cost = req.get("cost_credits") or 0
                if cost:
                    cb = sb.table("credit_balances").select("balance").eq("brand_id", req["brand_id"]).maybe_single().execute().data
                    new_bal = (cb["balance"] if cb else 0) + cost
                    sb.table("credit_balances").update({"balance": new_bal}).eq("brand_id", req["brand_id"]).execute()
                    sb.table("credit_transactions").insert({
                        "brand_id": req["brand_id"],
                        "amount": cost,
                        "balance_after": new_bal,
                        "action": "refund", "type": "refund",
                        "ref_table": "subculture_expansions",
                        "ref_id": exp_id, "related_id": exp_id,
                        "description": "Refund for failed expansion",
                        "metadata": {"reason": "expansion_failed"},
                    }).execute()
            except Exception as e:
                print(f"  refund failed: {e}", file=sys.stderr)
            print(f"  ✗ expansion failed: {err}", file=sys.stderr)
            return True
        # Success status was already set by the script via subculture_expansions update
        print("  ✓ expansion completed", file=sys.stderr)
        return True
    except subprocess.TimeoutExpired:
        sb.table("subculture_expansions").update({
            "status": "failed", "completed_at": "now()",
            "notes": "timeout after 25min",
        }).eq("id", exp_id).execute()
        return True


def process_one(sb) -> bool:
    """Pick and process exactly one pending scan OR expansion. Returns True if work was done.

    Tries scans first, then expansions. Uses FOR UPDATE SKIP LOCKED RPCs so
    multiple queue workers are safe.
    """
    res = sb.rpc("claim_next_scan", {}).execute()
    req = res.data
    if isinstance(req, list):
        req = req[0] if req else None
    if not req or not req.get("id"):
        # No scan; try an expansion
        return process_expansion(sb)
    print(f"\n=== Processing scan {req['id']} (brand {req['brand_id'][:8]}) ===", file=sys.stderr)

    before = get_counts(sb, req["brand_id"])
    scope = (req.get("scope") or "standard").lower()
    ok, err = run_scan_chain(sb, req["id"], req["brand_id"], scope=scope)
    after  = get_counts(sb, req["brand_id"])
    diff = {
        "new_creators":   after["creators"]      - before["creators"],
        "new_posts":      after["content_items"] - before["content_items"],
        "new_detections": after["detections"]    - before["detections"],
        "before": before, "after": after,
    }

    if ok:
        sb.table("scan_requests").update({
            "status": "completed",
            "completed_at": "now()",
            "results": diff,
        }).eq("id", req["id"]).execute()
        print(f"  ✓ done: +{diff['new_posts']} posts, +{diff['new_detections']} detections, +{diff['new_creators']} creators", file=sys.stderr)
    else:
        sb.table("scan_requests").update({
            "status": "failed",
            "completed_at": "now()",
            "error": err,
        }).eq("id", req["id"]).execute()
        # Refund credits. The credit_transactions table has legacy NOT NULL
        # columns (`type`, `description`) so we populate both old and new field
        # names for backward compat.
        try:
            cost = req.get("credits_charged") or 0
            if cost > 0:
                cb = sb.table("credit_balances").select("balance").eq("brand_id", req["brand_id"]).maybe_single().execute().data
                new_bal = (cb["balance"] if cb else 0) + cost
                sb.table("credit_balances").update({"balance": new_bal}).eq("brand_id", req["brand_id"]).execute()
                sb.table("credit_transactions").insert({
                    "brand_id": req["brand_id"],
                    "amount": cost,
                    "balance_after": new_bal,
                    "action": "refund", "type": "refund",
                    "ref_table": "scan_requests",
                    "ref_id": req["id"], "related_id": req["id"],
                    "description": "Refund for failed scan",
                    "metadata": {"reason": "scan_failed", "error": err[:200]},
                }).execute()
                print(f"  refunded {cost} credits (balance now {new_bal})", file=sys.stderr)
        except Exception as e:
            print(f"  refund failed: {e}", file=sys.stderr)
        print(f"  ✗ failed: {err}", file=sys.stderr)
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--loop", action="store_true", help="Poll forever every 30s")
    p.add_argument("--max", type=int, default=1, help="Max scans per run (when not --loop)")
    args = p.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SECRET_KEY"))

    if args.loop:
        print("Polling scan_requests every 30s. Ctrl-C to stop.", file=sys.stderr)
        last_reap = 0
        while True:
            try:
                # Periodically reap stale running rows. Critical for the
                # case where the worker restarts mid-scan: the orphaned
                # 'running' row would otherwise block the brand forever
                # because claim_next_scan only picks up 'pending' rows.
                if time.time() - last_reap > 120:
                    try:
                        r1 = sb.rpc("reap_stale_scans", {}).execute()
                        r2 = sb.rpc("reap_stale_expansions", {}).execute()
                        n1 = r1.data if isinstance(r1.data, int) else 0
                        n2 = r2.data if isinstance(r2.data, int) else 0
                        if n1 or n2:
                            print(f"reaped: {n1} stale scans + {n2} stale expansions", file=sys.stderr)
                    except Exception as e:
                        print(f"reap err: {e}", file=sys.stderr)
                    last_reap = time.time()
                did = process_one(sb)
                if not did:
                    time.sleep(30)
            except KeyboardInterrupt:
                print("\nstopped", file=sys.stderr)
                break
            except Exception as e:
                print(f"loop err: {e}", file=sys.stderr)
                time.sleep(30)
    else:
        for _ in range(args.max):
            if not process_one(sb):
                print("No pending scans.", file=sys.stderr)
                break


if __name__ == "__main__":
    main()
