#!/usr/bin/env bash
set -euo pipefail

VERIFY_OUTPUT_FILE="${VERIFY_OUTPUT_FILE:-.omx/review-context/latest-verify-output.txt}"
mkdir -p "$(dirname "$VERIFY_OUTPUT_FILE")"

gate_log() {
  printf '[gate] %s %s\n' "$(date -Is)" "$*"
}

gate_log "running verification; output=${VERIFY_OUTPUT_FILE}"
./scripts/verify.sh 2>&1 | tee "$VERIFY_OUTPUT_FILE"
gate_log "verification complete"

gate_log "running AI reviews..."
set +e
./scripts/run-ai-reviews.sh
review_status=$?
set -e
gate_log "AI reviews finished with exit_code=${review_status}"

if [ "${review_status}" -ne 0 ]; then
  if [ "${review_status}" -eq 2 ]; then
    echo "[gate] external AI review prepared; run the generated external reviewer command, then rerun ./scripts/summarize-ai-reviews.sh"
  fi
  exit "${review_status}"
fi

gate_log "summarizing AI review verdicts..."
if ! ./scripts/summarize-ai-reviews.sh; then
  gate_log "review gate did not proceed"
  exit 1
fi

gate_log "complete"
