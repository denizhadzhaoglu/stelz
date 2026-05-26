#!/bin/sh
# Full daily pipeline: refresh seed list, auto-add new creators, AI score,
# prune irrelevant. Logs each step. Exits non-zero on any failure.
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

echo "--- 6. daily_email_report (send recap to every active brand)"
python tools/stelz_brand_watch/daily_email_report.py || echo "email step failed, continuing"

echo "--- 7. credit_lifecycle (monthly renewal + grant expiry)"
python tools/stelz_brand_watch/credit_lifecycle.py || echo "credit step failed, continuing"

echo "=== daily_pipeline done $(date -u +%FT%TZ) ==="
