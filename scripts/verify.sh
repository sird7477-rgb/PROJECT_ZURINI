#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "[verify] fail: $1" >&2
  exit 1
}

require_file() {
  local path="$1"
  [ -f "$path" ] || fail "missing required file: ${path}"
  echo "[verify] file ok: ${path}"
}

require_text() {
  local path="$1"
  local pattern="$2"
  if ! grep -Fq "$pattern" "$path"; then
    fail "missing expected text in ${path}: ${pattern}"
  fi
  echo "[verify] anchor ok: ${path} :: ${pattern}"
}

require_executable_script() {
  local path="$1"
  local index_mode

  [ -x "$path" ] || fail "script is not executable in working tree: ${path}"

  index_mode="$(git ls-files --stage -- "$path" | cut -d ' ' -f 1 | head -n 1)"
  if [ -n "$index_mode" ] && [ "$index_mode" != "100755" ]; then
    fail "script is not executable in git index: ${path} (${index_mode})"
  fi

  echo "[verify] executable ok: ${path}"
}

echo "[verify] checking review summary fixture logic..."
./scripts/test-review-summary.sh

echo
echo "[verify] checking automation files..."
DOCTOR_SKIP_DIRTY_CHECK=1 ./scripts/automation-doctor.sh

echo
echo "[verify] checking PROJECT_ZURINI documentation baseline..."
require_file "AGENTS.md"
require_file "docs/WORKFLOW.md"
require_file "scripts/review-gate.sh"
require_file "(old)/# [자동매매 전략 기획서].md"
require_file "(old)/# [자동매매 전략 기획서_고도화].md"
require_file "(old)/# [자동매매 플로우 차트].md"
require_file "(old)/[자동매매_시퀀스_다이어그램].md"
require_file "(old)/[자동매매_통합_아키텍처_설계서].md"

require_executable_script "scripts/automation-doctor.sh"
require_executable_script "scripts/collect-review-context.sh"
require_executable_script "scripts/discover-ai-models.sh"
require_executable_script "scripts/make-review-prompts.sh"
require_executable_script "scripts/review-gate.sh"
require_executable_script "scripts/run-ai-reviews.sh"
require_executable_script "scripts/summarize-ai-reviews.sh"
require_executable_script "scripts/test-review-summary.sh"
require_executable_script "scripts/verify.sh"

require_text "AGENTS.md" "Project ZURINI"
require_text "docs/WORKFLOW.md" "PROJECT_ZURINI"
require_text "(old)/# [자동매매 전략 기획서].md" "2-Tier 이중 리스크 방어망"
require_text "(old)/# [자동매매 전략 기획서_고도화].md" "글로벌 베타 스로틀링"
require_text "(old)/# [자동매매 플로우 차트].md" "IOC 연사 탈출"
require_text "(old)/[자동매매_시퀀스_다이어그램].md" "Async NLP Blacklist"
require_text "(old)/[자동매매_통합_아키텍처_설계서].md" "Universal Quant Core"

echo
echo "[verify] success"
