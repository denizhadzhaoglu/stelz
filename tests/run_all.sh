#!/bin/bash
# Run every QA test in sequence. Exits 0 only if everything passes.
# Prefers python3.13 (has google.genai installed); falls back to python3.
set -u
cd "$(dirname "$0")/.."

if command -v python3.13 >/dev/null 2>&1; then
  PY=python3.13
else
  PY=python3
fi

OK=0
FAIL=0
TESTS=(
  "DB invariants"        "tests/test_db_invariants.py"
  "Schema drift"         "tests/test_schema_drift.py"
  "Edge functions"       "tests/test_edge_functions.py"
  "Spot API"             "tests/test_spot_api.py"
  "Pipeline freshness"   "tests/test_pipeline_freshness.py"
)

for ((i=0; i<${#TESTS[@]}; i+=2)); do
  name="${TESTS[i]}"
  path="${TESTS[i+1]}"
  echo ""
  echo "========================================"
  echo "  $name  ($path)"
  echo "========================================"
  if $PY "$path"; then
    OK=$((OK+1))
  else
    FAIL=$((FAIL+1))
  fi
done

echo ""
echo "========================================"
echo "  FINAL: $OK suites passed, $FAIL failed"
echo "========================================"

[ $FAIL -eq 0 ] && exit 0 || exit 1
