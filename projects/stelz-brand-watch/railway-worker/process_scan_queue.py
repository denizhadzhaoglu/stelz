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
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PA_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PA_ROOT / ".env")

# Sentry — silent no-op if SENTRY_DSN isn't set.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _observability import init_sentry
    init_sentry("queue-worker")
except Exception:
    pass


def get_counts(sb, brand_id: str) -> dict:
    return {
        "creators": sb.table("creators").select("id", count="exact", head=True).eq("brand_id", brand_id).execute().count,
        "content_items": sb.table("content_items").select("id", count="exact", head=True).eq("brand_id", brand_id).execute().count,
        "detections": sb.table("detections").select("id", count="exact", head=True).eq("brand_id", brand_id).eq("detected", True).execute().count,
    }


def build_steps(scope: str, brand_slug: str = "stelz"):
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
                     "--apify-concurrency", "6",
                     "--brand-slug", brand_slug]},
            {"key": "tiktok_scan", "label": "TikTok hashtag harvest",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/15_tiktok_harvest.py"),
                     "--per-tag", "150"]},
            {"key": "detect_pending", "label": "Flash detection on un-detected images (incl. TikTok thumbs)",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/33_detect_pending.py"),
                     "--concurrency", "20", "--brand-slug", brand_slug]},
            {"key": "pro_verify", "label": "Pro verification of new hits",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/17_verify_with_pro.py"),
                     "--concurrency", "8", "--brand-slug", brand_slug]},
        ]
    if scope == "backfill":
        # Premium first-run historical sweep. Goes wider on tag discovery and
        # pulls a much deeper post history per creator. Designed to be run
        # once when a brand activates a paid plan.
        return [
            {"key": "auto_add",   "label": "Backfill: discovering historical creators",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/19_auto_add.py"), "--per-tag", "500"]},
            {"key": "daily_scan", "label": "Backfill: 60 posts/creator + Flash detection",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/18_daily_scan.py"),
                     "--skip-recent-hours", "0",
                     "--posts-per-creator", "60",
                     "--apify-concurrency", "6",
                     "--brand-slug", brand_slug]},
            {"key": "tiktok_scan", "label": "Backfill: TikTok hashtag history",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/15_tiktok_harvest.py"),
                     "--per-tag", "300"]},
            {"key": "detect_pending", "label": "Flash detection on un-detected images",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/33_detect_pending.py"),
                     "--concurrency", "20", "--brand-slug", brand_slug]},
            {"key": "pro_verify", "label": "Pro verification of backfill hits",
             "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/17_verify_with_pro.py"),
                     "--concurrency", "8", "--brand-slug", brand_slug]},
        ]
    # default: standard scan
    return [
        {"key": "auto_add",   "label": "Adding new creators from hashtags",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/19_auto_add.py"), "--per-tag", "150"]},
        {"key": "daily_scan", "label": "Scraping latest posts + Flash detection",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/18_daily_scan.py")]},
        {"key": "pro_verify", "label": "Pro verification of new hits",
         "cmd": ["python3", str(PA_ROOT / "tools/stelz_brand_watch/17_verify_with_pro.py"), "--concurrency", "6", "--brand-slug", brand_slug]},
    ]


# Backwards compat: some callers still reference STEPS directly.
STEPS = build_steps("standard")


def update_progress(sb, scan_id: str, progress: dict):
    """Write live progress to scan_requests so the dashboard can render it."""
    sb.table("scan_requests").update({"progress": progress}).eq("id", scan_id).execute()


def run_scan_chain(sb, scan_id: str, brand_id: str, scope: str = "standard") -> tuple[bool, str]:
    """Run pipeline and persist step-level progress to scan_requests.progress."""
    # Resolve brand slug so child scripts can load brand-specific refs.
    brand_row = sb.table("brands").select("slug").eq("id", brand_id).maybe_single().execute().data
    brand_slug = (brand_row or {}).get("slug", "stelz")
    steps = build_steps(scope, brand_slug=brand_slug)
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
        # Refresh denormalized creator stats so posts_seen / hits_seen /
        # last_hit_at reflect the new data. Cheap, idempotent SQL function.
        try:
            sb.rpc("refresh_creator_stats", {"p_brand_id": req["brand_id"]}).execute()
        except Exception as e:
            print(f"  stats refresh err: {e}", file=sys.stderr)
        # If this was a backfill scan, mark the subscription so the backfill
        # worker doesn't re-enqueue it on the next tick.
        if scope == "backfill":
            try:
                sb.table("subscriptions").update({
                    "backfill_completed_at": "now()",
                }).eq("brand_id", req["brand_id"]).eq("backfill_scan_id", req["id"]).execute()
            except Exception as e:
                print(f"  backfill completion mark err: {e}", file=sys.stderr)
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
        last_aux = 0
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
                # Run auxiliary workers every 5 min: backfill enqueue,
                # tier1 alerts, invite email send. All are quick no-ops
                # when there's nothing to do.
                if time.time() - last_aux > 300:
                    # Refresh creator stats every aux-cycle. RPC call, ~1s.
                    try:
                        sb.rpc("refresh_creator_stats", {"p_brand_id": None}).execute()
                    except Exception as e:
                        print(f"aux stats refresh err: {e}", file=sys.stderr)
                    # Recompute adaptive scheduling cadence every 24h at 02:00 NL.
                    # Cheap (~2s for 2k creators) but no need more frequent than
                    # daily because posting rates are stable on 28d windows.
                    try:
                        h = datetime.now().hour
                        if h == 2 and (time.time() - last_aux) < 360:
                            sb.rpc("update_creator_cadence", {"p_brand_id": None}).execute()
                            print("cadence: recomputed adaptive scheduling for all creators", file=sys.stderr)
                    except Exception as e:
                        print(f"cadence refresh err: {e}", file=sys.stderr)
                    aux_scripts = [
                        ("38_backfill_worker.py", [], 120),
                        ("37_alert_tier1_hits.py", [], 120),
                        ("39_send_invite_emails.py", [], 120),
                        ("41_creator_graph_expand.py", [], 120),
                        ("43_budget_alerts.py", [], 120),
                        ("45_link_creator_identities.py", [], 120),
                        # CRITICAL (added 19 May 2026): detect_pending was only
                        # running as part of scan_chain — meaning hashtag/stories/
                        # tiktok harvests dumped images that never got detected
                        # until a user-triggered scan_request came in. Caused
                        # dashboard to show 0 hits this week even while scraping
                        # 117 fresh posts. Now drains every aux cycle (5 min)
                        # with a 100-image cap; no-op when queue is empty.
                        ("33_detect_pending.py", ["--limit", "100", "--concurrency", "15"], 900),
                    ]
                    # MONITORING REBALANCE (added 17 May 2026):
                    #
                    # The pipeline was eating scan budget on subculture
                    # exploration while known hit-producing creators were
                    # only being touched every 9-15h. For a monitoring
                    # tool, top creators must be refreshed in near-real-
                    # time. Schedule below:
                    #
                    #   every 2h  → priority sweep: top hit-producers,
                    #               max 60 creators per run. Catches new
                    #               posts from known fans within ~2h.
                    #   every 4h  → broad sweep: 400 oldest creators.
                    #               Rotates through the full base every
                    #               ~10h. Combined with --skip-recent-hours
                    #               4 to not waste calls on fresh ones.
                    #   every 6h  → hashtag harvest: refreshes #stelz and
                    #               related tags. Historically 55.6% hit
                    #               rate, our best source.
                    #   every 4h  → stories harvest (kept, ephemeral)
                    #   every 24h → perplexity scout (kept, web intel)
                    #
                    # Tick math: 5-min cycle = 300s; tick = time // 300.
                    aux_tick = int(time.time() // 300)
                    if aux_tick % 24 == 0:    # every 120 min = 2 hours
                        aux_scripts.append((
                            "18_daily_scan.py",
                            ["--prioritize-hits", "--max-creators", "60",
                             "--skip-recent-hours", "2", "--posts-per-creator", "8"],
                            1500,  # 25 min timeout
                        ))
                    if aux_tick % 48 == 0:    # every 240 min = 4 hours
                        aux_scripts.append((
                            "18_daily_scan.py",
                            ["--max-creators", "400",
                             "--skip-recent-hours", "4", "--posts-per-creator", "8"],
                            1500,
                        ))
                        aux_scripts.append(("44_stories_harvest.py", [], 600))
                    if aux_tick % 72 == 0:    # every 360 min = 6 hours
                        # Brand-aware: loops over every active brand's
                        # `brand_hashtag_pools` rows. Previously stelz-only.
                        aux_scripts.append((
                            "12_full_stelz_harvest.py",
                            ["--all-brands", "--per-tag", "300"],
                            1800,
                        ))
                    if aux_tick % 96 == 0:    # every 480 min = 8 hours
                        # TikTok hashtag harvest (brand-aware, all active brands)
                        aux_scripts.append((
                            "15_tiktok_harvest.py",
                            ["--all-brands", "--per-tag", "100"],
                            1500,
                        ))
                    if aux_tick % 144 == 0:   # every 720 min = 12 hours
                        # TikTok profile scan for known hit-producing creators.
                        # Caps at 40 creators/brand to bound Apify cost.
                        aux_scripts.append((
                            "48_tiktok_profile_scan.py",
                            ["--all-brands", "--max-creators", "40", "--posts-per-creator", "10"],
                            1500,
                        ))
                        # Cross-platform identity link is cheap — pair IG+TikTok
                        # creators so tier-1 status propagates and reach is
                        # combined for outreach reports.
                        aux_scripts.append((
                            "45_link_creator_identities.py",
                            [],
                            300,
                        ))
                    if aux_tick % 288 == 0:   # every 1440 min = 24 hours
                        aux_scripts.append(("22_perplexity_scout.py", [], 300))
                    # Daily system-health check at 03:00 NL. Writes alerts to
                    # public.system_health_alerts so operators see drift before
                    # users do.
                    try:
                        if datetime.now().hour == 3 and (time.time() - last_aux) < 360:
                            aux_scripts.append(("50_system_health_check.py", [], 180))
                    except Exception as e:
                        print(f"health check schedule err: {e}", file=sys.stderr)
                    for script, extra_args, t_out in aux_scripts:
                        try:
                            subprocess.run(
                                ["python3", str(PA_ROOT / "tools/stelz_brand_watch" / script)] + extra_args,
                                capture_output=True, text=True, timeout=t_out,
                            )
                        except Exception as e:
                            print(f"aux {script} err: {e}", file=sys.stderr)
                    last_aux = time.time()
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
