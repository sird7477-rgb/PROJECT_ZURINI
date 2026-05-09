#!/usr/bin/env bash
set -euo pipefail

RESULT_DIR="${OMX_REVIEW_RESULTS_DIR:-.omx/review-results}"
ARCHIVE_DIR="${OMX_REVIEW_ARCHIVE_DIR:-${RESULT_DIR}/archive}"
THRESHOLD="${OMX_REVIEW_ARCHIVE_THRESHOLD:-${OMX_ARTIFACT_WARN_COUNT:-200}}"
KEEP_FILES="${OMX_REVIEW_ARCHIVE_KEEP_FILES:-}"
MODE="archive"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage: ./scripts/archive-omx-artifacts.sh [--dry-run] [--delete]

Archive old .omx review artifacts while preserving recent session evidence.

Default behavior:
  - only acts when .omx/review-results exceeds OMX_REVIEW_ARCHIVE_THRESHOLD
  - preserves the newest OMX_REVIEW_ARCHIVE_KEEP_FILES files
  - moves older files to .omx/review-results/archive/YYYYMMDD/
  - never deletes unless --delete is explicitly supplied

Environment:
  OMX_REVIEW_RESULTS_DIR=PATH        review result directory
  OMX_REVIEW_ARCHIVE_DIR=PATH        archive destination directory
  OMX_REVIEW_ARCHIVE_THRESHOLD=N     file-count threshold before cleanup
  OMX_REVIEW_ARCHIVE_KEEP_FILES=N    newest files to keep active
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --delete)
      MODE="delete"
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

for numeric in THRESHOLD KEEP_FILES; do
  if [ "$numeric" = "KEEP_FILES" ] && [ -z "$KEEP_FILES" ]; then
    continue
  fi

  value="${!numeric}"
  case "$value" in
    ''|*[!0-9]*)
      echo "[archive] invalid ${numeric}='${value}'"
      exit 2
      ;;
  esac
done

if [ -z "$KEEP_FILES" ]; then
  KEEP_FILES=120
  if [ "$THRESHOLD" -lt "$KEEP_FILES" ]; then
    KEEP_FILES="$THRESHOLD"
  fi
fi

if [ ! -d "$RESULT_DIR" ]; then
  echo "[archive] review result directory missing: ${RESULT_DIR}"
  exit 0
fi

file_count="$(find "$RESULT_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
if [ "$file_count" -le "$THRESHOLD" ]; then
  echo "[archive] no cleanup needed: ${RESULT_DIR} has ${file_count} files (threshold ${THRESHOLD})"
  exit 0
fi

if [ "$file_count" -le "$KEEP_FILES" ]; then
  echo "[archive] no cleanup needed: ${RESULT_DIR} has ${file_count} files and keep-files is ${KEEP_FILES}"
  exit 0
fi

archive_date="$(date +%Y%m%d)"
archive_target="${ARCHIVE_DIR}/${archive_date}"
move_count=0
PRESERVED_FILES=()

add_preserved_file() {
  local path="$1"

  [ -n "$path" ] || return 0
  [ -f "$path" ] || return 0

  case "$path" in
    "${RESULT_DIR}"/*)
      ;;
    *)
      return 0
      ;;
  esac

  PRESERVED_FILES+=("$path")
}

latest_file() {
  local pattern="$1"

  # Review artifact names are generated without spaces. Use ls -t here to
  # avoid GNU find -printf, which is unavailable on macOS/BSD.
  ls -t "$RESULT_DIR"/$pattern 2>/dev/null | head -1 || true
}

add_referenced_outputs() {
  local source_file="$1"
  local referenced

  [ -f "$source_file" ] || return 0

  while IFS= read -r referenced; do
    add_preserved_file "$referenced"
  done < <(
    sed -n 's/^[[:space:]]*[-*][[:space:]][^:][^:]*:[[:space:]]*\([^[:space:]]*\.md\)[[:space:]]*$/\1/p' "$source_file"
  )
}

add_run_id_outputs() {
  local source_file="$1"
  local run_id
  local candidate

  [ -f "$source_file" ] || return 0

  run_id="$(sed -n 's/^[[:space:]]*[-*][[:space:]]Review run id:[[:space:]]*\([0-9]\{8\}T[0-9]\{6\}\)$/\1/p' "$source_file" | head -1)"
  [ -n "$run_id" ] || return 0

  while IFS= read -r -d '' candidate; do
    add_preserved_file "$candidate"
  done < <(find "$RESULT_DIR" -maxdepth 1 -type f -name "*-${run_id}.md" -print0 2>/dev/null)
}

latest_run="$(latest_file 'review-run-*.md')"
latest_summary="$(latest_file 'review-summary-*.md')"
latest_verdict="$(latest_file 'review-verdict-*.md')"

add_preserved_file "$latest_run"
add_preserved_file "$latest_summary"
add_preserved_file "$latest_verdict"
add_referenced_outputs "$latest_run"
add_referenced_outputs "$latest_summary"
add_run_id_outputs "$latest_run"

is_preserved_file() {
  local path="$1"
  local preserved

  for preserved in "${PRESERVED_FILES[@]}"; do
    if [ "$path" = "$preserved" ]; then
      return 0
    fi
  done

  return 1
}

if [ "$MODE" = "archive" ] && [ "$DRY_RUN" -eq 0 ]; then
  mkdir -p "$archive_target"
fi

unique_target() {
  local target="$1"
  local candidate="$target"
  local index=1

  while [ -e "$candidate" ]; do
    candidate="${target}.${index}"
    index=$((index + 1))
  done

  printf '%s\n' "$candidate"
}

mtime_epoch() {
  local path="$1"

  stat -c %Y "$path" 2>/dev/null || stat -f %m "$path" 2>/dev/null || printf '0\n'
}

is_safe_artifact_name() {
  local base_name="$1"

  case "$base_name" in
    *[!A-Za-z0-9._+-]*|""|.*|*.tmp)
      return 1
      ;;
    *.md)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while IFS= read -r -d '' candidate; do
  base_name="$(basename "$candidate")"
  if ! is_safe_artifact_name "$base_name"; then
    echo "[archive] leaving unsafe artifact filename active: ${candidate}" >&2
  fi
done < <(find "$RESULT_DIR" -maxdepth 1 -type f -print0 2>/dev/null)

while IFS= read -r file_path; do
  [ -n "$file_path" ] || continue
  if is_preserved_file "$file_path"; then
    continue
  fi

  base_name="$(basename "$file_path")"
  if ! is_safe_artifact_name "$base_name"; then
    echo "[archive] leaving unsafe artifact filename active: ${file_path}" >&2
    continue
  fi

  move_count=$((move_count + 1))

  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$MODE" = "delete" ]; then
      echo "[archive] would delete ${file_path}"
    else
      echo "[archive] would move ${file_path} -> ${archive_target}/"
    fi
    continue
  fi

  if [ "$MODE" = "delete" ]; then
    rm -f "$file_path"
  else
    destination="$(unique_target "${archive_target}/${base_name}")"
    mv "$file_path" "$destination"
  fi
done < <(
  while IFS= read -r -d '' candidate; do
    base_name="$(basename "$candidate")"
    if is_safe_artifact_name "$base_name"; then
      printf '%s\t%s\n' "$(mtime_epoch "$candidate")" "$candidate"
    fi
  done < <(find "$RESULT_DIR" -maxdepth 1 -type f -print0 2>/dev/null) \
    | sort -rn \
    | cut -f2- \
    | tail -n +"$((KEEP_FILES + 1))"
)

if [ "$MODE" = "delete" ]; then
  echo "[archive] deleted ${move_count} old review artifact files; kept newest ${KEEP_FILES}"
else
  echo "[archive] archived ${move_count} old review artifact files to ${archive_target}; kept newest ${KEEP_FILES}"
fi
