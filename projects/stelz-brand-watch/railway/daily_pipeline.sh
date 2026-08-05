#!/bin/sh
# Full daily pipeline: refresh seed list, auto-add new creators, AI score,
# prune irrelevant, compute SRS resonance. Logs each step. Exits non-zero on
# any failure for required steps; SRS steps are non-fatal during rollout.
set -e
echo "=== daily_pipeline starting $(date -u +%FT%TZ) ==="

echo "--- 1. auto_add (hashtag discovery)"
python tools/stelz_brand_watch/auto_add.py --per-tag 300

echo "--- 2. daily_scan (refresh seed list creators)"
python tools/stelz_brand_watch/daily_scan.py

echo "--- 2b. pro_verify (vision-first: Pro re-checks every new flash hit)"
python tools/stelz_brand_watch/pro_verify.py --concurrency 6 || echo "pro_verify failed, continuing"

echo "--- 3. ai_score (score any unscored creators)"
python tools/stelz_brand_watch/ai_score_creators.py --concurrency 15

echo "--- 4. auto_prune (demote/archive based on metrics)"
python tools/stelz_brand_watch/auto_prune.py

echo "--- 5. train_from_moderator (refresh few-shot training set)"
python tools/stelz_brand_watch/train_from_moderator.py --pos 12 --neg 12 || echo "train step failed, continuing"

# ── SRS / Resonance scoring (non-fatal during rollout) ─────────────────
echo "--- 6a. build_edges (refresh creator network: mention/comment/subculture)"
python tools/stelz_brand_watch/51_build_edges.py || echo "build_edges failed, continuing"

echo "--- 6b. mine_comments (light pass on recent hit-posts for comment edges)"
python tools/stelz_brand_watch/52_mine_comments.py --max-posts 20 || echo "mine_comments failed, continuing"

echo "--- 6c. compute_resonance (6-layer SRS, bootstrap-aware)"
python tools/stelz_brand_watch/53_compute_resonance.py || echo "compute_resonance failed, continuing"

echo "--- 6d. visual_centroid (refresh tier-1 brand visual centroid)"
python tools/stelz_brand_watch/54_visual_centroid.py || echo "visual_centroid failed, continuing"

echo "--- 6e. score_visual (apply visual layer to high-SRS candidates)"
python tools/stelz_brand_watch/55_score_visual.py || echo "score_visual failed, continuing"

# ── Reporting + billing ────────────────────────────────────────────────
echo "--- 7. daily_email_report (send recap to every active brand)"
python tools/stelz_brand_watch/daily_email_report.py || echo "email step failed, continuing"

echo "--- 8. credit_lifecycle (monthly renewal + grant expiry)"
python tools/stelz_brand_watch/credit_lifecycle.py || echo "credit step failed, continuing"

echo "=== daily_pipeline done $(date -u +%FT%TZ) ==="
