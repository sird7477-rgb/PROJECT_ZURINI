#!/usr/bin/env bash
set -euo pipefail

FEEDBACK_FILE="${OMX_FEEDBACK_QUEUE_FILE:-.omx/feedback/queue.jsonl}"
LOCK_TIMEOUT_SECONDS="${OMX_FEEDBACK_QUEUE_LOCK_TIMEOUT_SECONDS:-10}"
REPEAT_KEY=""
STATUS="resolved"
NOTE=""
SOURCE=""
ALL_MATCHES=0

usage() {
  cat <<'USAGE'
Usage: ./scripts/resolve-feedback.sh --repeat-key KEY [options]

Mark sanitized feedback queue items in .omx/feedback/queue.jsonl.
Missing status on older items is treated as open.

Options:
  --repeat-key KEY  stable feedback grouping key to update
  --status STATUS   open, resolved, ignored, or deferred (default: resolved)
  --note TEXT       short sanitized handling note
  --source TEXT     optional command, review file, or user request reference
  --all             update all non-terminal items with the repeat key

Do not store secrets, credentials, customer data, copied private logs, or raw
stack traces when a short note is enough.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repeat-key)
      REPEAT_KEY="${2:-}"
      shift
      ;;
    --status)
      STATUS="${2:-}"
      shift
      ;;
    --note)
      NOTE="${2:-}"
      shift
      ;;
    --source)
      SOURCE="${2:-}"
      shift
      ;;
    --all)
      ALL_MATCHES=1
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

if [ -z "$REPEAT_KEY" ]; then
  usage
  exit 2
fi

case "$STATUS" in
  open|resolved|ignored|deferred) ;;
  *)
    echo "[feedback] unsupported status: ${STATUS}"
    exit 2
    ;;
esac

secret_pattern='(^|[^[:alnum:]_])((password|passwd|pwd|token|secret|authorization|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|private[_ -]?key)[[:space:]]*[:=]|bearer[[:space:]]+|ssh-rsa|ssh-ed25519|begin[[:space:]]+[^[:space:]]*[[:space:]]*private[[:space:]]+key)'
for value in "$REPEAT_KEY" "$STATUS" "$NOTE" "$SOURCE"; do
  if printf '%s' "$value" | grep -Eiq "$secret_pattern"; then
    echo "[feedback] refusing to store content that looks secret-bearing"
    exit 2
  fi
done

if [ ! -f "$FEEDBACK_FILE" ]; then
  echo "[feedback] queue not found: ${FEEDBACK_FILE}"
  exit 1
fi

lock_file="${FEEDBACK_FILE}.lockfile"
lock_dir="${FEEDBACK_FILE}.lock"
lock_acquired=0

if command -v flock >/dev/null 2>&1; then
  exec 9>"$lock_file"
  if flock -w "$LOCK_TIMEOUT_SECONDS" 9; then
    lock_acquired=1
    trap 'flock -u 9 2>/dev/null || true' EXIT
  fi
else
  lock_deadline=$(( $(date +%s) + LOCK_TIMEOUT_SECONDS ))
  while [ "$(date +%s)" -le "$lock_deadline" ]; do
    if mkdir "$lock_dir" 2>/dev/null; then
      lock_acquired=1
      trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
      break
    fi
    sleep 0.2
  done
fi

if [ "$lock_acquired" -ne 1 ]; then
  echo "[feedback] could not lock feedback queue: ${FEEDBACK_FILE}"
  if command -v flock >/dev/null 2>&1; then
    echo "[feedback] lock path: ${lock_file}"
  else
    echo "[feedback] lock path: ${lock_dir}"
    echo "[feedback] automatic stale lock removal is disabled without flock."
    echo "[feedback] if no resolver is running, remove the lock directory and retry."
  fi
  echo "[feedback] waited: ${LOCK_TIMEOUT_SECONDS}s"
  exit 1
fi

python3 - "$FEEDBACK_FILE" "$REPEAT_KEY" "$STATUS" "$NOTE" "$SOURCE" "$ALL_MATCHES" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
repeat_key = sys.argv[2]
status = sys.argv[3]
note = sys.argv[4]
source = sys.argv[5]
all_matches = sys.argv[6] == "1"
terminal_statuses = {"resolved", "ignored"}

items = []
for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
    if not line.strip():
        continue
    try:
        item = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[feedback] invalid JSON on line {lineno}: {exc}") from exc
    if not isinstance(item, dict):
        raise SystemExit(f"[feedback] expected object on line {lineno}")
    items.append(item)

candidate_indexes = [
    index
    for index, item in enumerate(items)
    if item.get("repeat_key") == repeat_key
    and item.get("status", "open") not in terminal_statuses
]

if not candidate_indexes:
    raise SystemExit(f"[feedback] no open feedback item found for repeat_key: {repeat_key}")

target_indexes = candidate_indexes if all_matches else [candidate_indexes[-1]]
updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

for index in target_indexes:
    item = items[index]
    item["status"] = status
    item["status_updated_at"] = updated_at
    if status in terminal_statuses:
        item[f"{status}_at"] = updated_at
    if note:
        item["status_note"] = note
    if source:
        item["status_source"] = source

tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
tmp_path.write_text(
    "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items),
    encoding="utf-8",
)
tmp_path.replace(path)
print(f"[feedback] marked {len(target_indexes)} item(s) {status} for {repeat_key} in {path}")
PY
