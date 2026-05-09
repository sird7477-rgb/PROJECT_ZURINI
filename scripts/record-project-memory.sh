#!/usr/bin/env bash
set -euo pipefail

MEMORY_FILE="${OMX_PROJECT_MEMORY_FILE:-.omx/project-memory.json}"
CATEGORY=""
CONTENT=""
SOURCE=""
EXPIRES_AT=""

usage() {
  cat <<'USAGE'
Usage: ./scripts/record-project-memory.sh --category NAME --content TEXT [--source TEXT] [--expires-at ISO8601]

Append a sanitized durable memory item to .omx/project-memory.json.

Do not store secrets, credentials, copied private logs, or speculative ideas
that were not accepted as future guidance.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --category)
      CATEGORY="${2:-}"
      shift
      ;;
    --content)
      CONTENT="${2:-}"
      shift
      ;;
    --source)
      SOURCE="${2:-}"
      shift
      ;;
    --expires-at)
      EXPIRES_AT="${2:-}"
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

if [ -z "$CATEGORY" ] || [ -z "$CONTENT" ]; then
  usage
  exit 2
fi

secret_pattern='(^|[^[:alnum:]_])((password|passwd|pwd|token|secret|authorization|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|private[_ -]?key)[[:space:]]*[:=]|bearer[[:space:]]+|ssh-rsa|ssh-ed25519|begin[[:space:]]+[^[:space:]]*[[:space:]]*private[[:space:]]+key)'
for value in "$CATEGORY" "$CONTENT" "$SOURCE" "$EXPIRES_AT"; do
  if printf '%s' "$value" | grep -Eiq "$secret_pattern"; then
    echo "[memory] refusing to store content that looks secret-bearing"
    exit 2
  fi
done

mkdir -p "$(dirname "$MEMORY_FILE")"

python3 - "$MEMORY_FILE" "$CATEGORY" "$CONTENT" "$SOURCE" "$EXPIRES_AT" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
category = sys.argv[2]
content = sys.argv[3]
source = sys.argv[4]
expires_at = sys.argv[5]

if path.exists():
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[memory] invalid JSON in {path}: {exc}") from exc
else:
    data = {}

notes = data.setdefault("notes", [])
if not isinstance(notes, list):
    raise SystemExit("[memory] expected top-level notes array")

entry = {
    "category": category,
    "content": content,
    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
if source:
    entry["source"] = source
if expires_at:
    entry["expires_at"] = expires_at

notes.append(entry)
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[memory] recorded {category} memory in {path}")
PY
