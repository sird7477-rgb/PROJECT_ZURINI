#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib-review-verdict.sh
. "${SCRIPT_DIR}/lib-review-verdict.sh"

TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_ROOT}"
}

trap cleanup EXIT

assert_usable() {
  local name="$1"
  local expected="$2"
  local file="${TMP_ROOT}/${name}.md"
  shift 2
  printf '%s\n' "$@" > "${file}"

  local status=0
  has_usable_verdict "${file}" || status=$?

  if [ "${expected}" = "yes" ] && [ "${status}" -ne 0 ]; then
    echo "[run-ai-review-test] ${name}: expected usable verdict"
    cat "${file}"
    exit 1
  fi
  if [ "${expected}" = "no" ] && [ "${status}" -eq 0 ]; then
    echo "[run-ai-review-test] ${name}: expected unusable verdict"
    cat "${file}"
    exit 1
  fi
  echo "[run-ai-review-test] ${name}: pass"
}

assert_usable "bare_verdict" "yes" \
  "# Review" \
  "" \
  "## Verdict" \
  "" \
  "approve_with_notes"

assert_usable "single_bullet_verdict" "yes" \
  "# Review" \
  "" \
  "## Verdict" \
  "" \
  "- approve_with_notes"

assert_usable "prompt_echo_choices" "no" \
  "# Review" \
  "" \
  "## Verdict" \
  "" \
  "Choose one:" \
  "" \
  "- approve" \
  "- approve_with_notes" \
  "- request_changes"

assert_usable "prompt_echo_then_bare_verdict" "yes" \
  "# Review" \
  "" \
  "## Verdict" \
  "" \
  "Choose one:" \
  "" \
  "- approve" \
  "- approve_with_notes" \
  "- request_changes" \
  "" \
  "request_changes"

echo "[run-ai-review-test] success"
