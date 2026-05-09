#!/usr/bin/env bash
set -euo pipefail

FEEDBACK_FILE="${OMX_FEEDBACK_QUEUE_FILE:-.omx/feedback/queue.jsonl}"
TYPE="failure_pattern"
REPEAT_KEY=""
SUMMARY=""
RESOLUTION=""
SEVERITY="medium"
SURFACE=""
SOURCE=""

usage() {
  cat <<'USAGE'
Usage: ./scripts/record-feedback.sh --repeat-key KEY --summary TEXT [options]

Append a sanitized feedback item to .omx/feedback/queue.jsonl.

Options:
  --type NAME          failure_pattern or improvement (default: failure_pattern)
  --repeat-key KEY    stable grouping key, for example git:index-lock-permission
  --summary TEXT      short sanitized symptom or idea
  --resolution TEXT   safe resolution or proposed follow-up
  --severity LEVEL    low, medium, high, or critical (default: medium)
  --surface NAME      area such as verify, review, git, onboarding, deploy
  --source TEXT       optional command, review file, or user request reference

Do not store secrets, credentials, customer data, copied private logs, or raw
stack traces when a short summary is enough.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --type)
      TYPE="${2:-}"
      shift
      ;;
    --repeat-key)
      REPEAT_KEY="${2:-}"
      shift
      ;;
    --summary)
      SUMMARY="${2:-}"
      shift
      ;;
    --resolution)
      RESOLUTION="${2:-}"
      shift
      ;;
    --severity)
      SEVERITY="${2:-}"
      shift
      ;;
    --surface)
      SURFACE="${2:-}"
      shift
      ;;
    --source)
      SOURCE="${2:-}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo
      usage
      exit 2
      ;;
  esac
  shift
done

if [ -z "$REPEAT_KEY" ] || [ -z "$SUMMARY" ]; then
  usage
  exit 2
fi

case "$TYPE" in
  failure_pattern|improvement) ;;
  *)
    echo "[feedback] unsupported type: ${TYPE}"
    exit 2
    ;;
esac

case "$SEVERITY" in
  low|medium|high|critical) ;;
  *)
    echo "[feedback] unsupported severity: ${SEVERITY}"
    exit 2
    ;;
esac

secret_pattern='(^|[^[:alnum:]_])((password|passwd|pwd|token|secret|authorization|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|private[_ -]?key)[[:space:]]*[:=]|bearer[[:space:]]+|ssh-rsa|ssh-ed25519|begin[[:space:]]+[^[:space:]]*[[:space:]]*private[[:space:]]+key)'
for value in "$REPEAT_KEY" "$SUMMARY" "$RESOLUTION" "$SURFACE" "$SOURCE"; do
  if printf '%s' "$value" | grep -Eiq "$secret_pattern"; then
    echo "[feedback] refusing to store content that looks secret-bearing"
    exit 2
  fi
done

mkdir -p "$(dirname "$FEEDBACK_FILE")"

python3 - "$FEEDBACK_FILE" "$TYPE" "$REPEAT_KEY" "$SUMMARY" "$RESOLUTION" "$SEVERITY" "$SURFACE" "$SOURCE" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
entry = {
    "type": sys.argv[2],
    "repeat_key": sys.argv[3],
    "summary": sys.argv[4],
    "severity": sys.argv[6],
    "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}

if sys.argv[5]:
    entry["resolution"] = sys.argv[5]
if sys.argv[7]:
    entry["surface"] = sys.argv[7]
if sys.argv[8]:
    entry["source"] = sys.argv[8]

path.open("a", encoding="utf-8").write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
print(f"[feedback] recorded {entry['type']}:{entry['repeat_key']} in {path}")
PY
