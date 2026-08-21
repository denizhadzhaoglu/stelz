#!/usr/bin/env bash
# Keep sweeping Instagram stories while an event runs.
#
# WHY THIS IS A LOOP AND NOT A ONE-OFF. handlers/scan_stories.STORY_TTL_HOURS is
# 24: a story is gone a day after it is posted and the CDN link behind it dies
# sooner than that. There is no backfill, no archive, no "fetch last week" — an
# hour not swept is an hour that never existed. Day one of Lowlands produced 96
# stories in a single sweep, roughly four per festival hour.
#
# Each sweep costs about $0.18 at Apify ($0.099 per run + $0.003 per handle) and
# is idempotent: stories already archived are skipped by id, and an image that
# downloaded once is never re-fetched. Running it too often wastes money;
# running it every three hours cannot miss a story, because nothing expires
# faster than 24h.
#
#   tools/stelz_brand_watch/sweep_stories.sh lowlands-2026 2026-08-24
#
# The second argument is the last day to sweep, inclusive — normally the day
# after the event ends, so the final evening's stories are caught before they
# expire. The loop exits by itself after that.
#
# To run it unattended, put it in crontab instead (every three hours):
#   0 */3 * * * cd "/path/to/Stelz tool" && tools/stelz_brand_watch/sweep_stories.sh lowlands-2026 2026-08-24 >> /tmp/stelz-sweep.log 2>&1
# In crontab the loop is pointless — pass ONCE=1 to do a single sweep and exit:
#   0 */3 * * * ... ONCE=1 tools/stelz_brand_watch/sweep_stories.sh lowlands-2026 2026-08-24
set -uo pipefail

EVENT="${1:-lowlands-2026}"
UNTIL="${2:?geef een einddatum: JJJJ-MM-DD}"
EVERY="${EVERY:-10800}"          # 3 hours
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/firebase/functions/venv/bin/python"

[ -x "$PY" ] || { echo "geen venv op $PY"; exit 2; }

while :; do
  today="$(date +%F)"
  if [[ "$today" > "$UNTIL" ]]; then
    echo "[$(date +%FT%T)] $today ligt na $UNTIL — klaar."
    exit 0
  fi
  echo "[$(date +%FT%T)] sweep $EVENT"
  # Never abort the loop on a failed sweep. Apify times out, the network drops,
  # a token expires — and the next window is still worth trying, because the
  # alternative is silently stopping and losing every hour after the failure.
  "$PY" "$ROOT/tools/stelz_brand_watch/62_stories_archive.py" --event "$EVENT" \
    || echo "[$(date +%FT%T)] sweep faalde — volgende poging over $((EVERY / 60))m"
  [ -n "${ONCE:-}" ] && exit 0
  sleep "$EVERY"
done
