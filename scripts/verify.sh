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
echo "[verify] checking PROJECT_ZURINI onboarding baseline..."
require_file "AGENTS.md"
require_file "docs/WORKFLOW.md"
require_file "docs/phase-1-development.md"
require_file "docs/phase-1-prd.md"
require_file "docs/phase-1-test-spec.md"
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

require_text "AGENTS.md" "phase-1 development"
require_text "AGENTS.md" "starting baseline for trading"
require_text "AGENTS.md" "not absolute"
require_text "AGENTS.md" "Phase 1 ends at a reproducible local backtest"
require_text "AGENTS.md" "Docker Compose Postgres"
require_text "docs/WORKFLOW.md" "재현 가능한 로컬 백테스트"
require_text "docs/WORKFLOW.md" "출발 기준"
require_text "docs/WORKFLOW.md" "절대 기준이 아니다"
require_text "docs/phase-1-development.md" "1분봉 데이터 스키마와 계약"
require_text "docs/phase-1-development.md" "deterministic dummy data"
require_text "docs/phase-1-development.md" "과거 문서 사용 원칙"
require_text "docs/phase-1-development.md" "절대 조건이 아니다"
require_text "docs/phase-1-development.md" "symbol + timestamp"
require_text "docs/phase-1-development.md" "trade_count"
require_text "docs/phase-1-development.md" "실거래/API/secret"
require_text "docs/phase-1-prd.md" "Local Backtest Foundation"
require_text "docs/phase-1-prd.md" "Old-Document Baseline Extraction"
require_text "docs/phase-1-prd.md" "not an absolute constraint"
require_text "docs/phase-1-prd.md" "Postgres Schema"
require_text "docs/phase-1-prd.md" "Dummy Data Generator"
require_text "docs/phase-1-prd.md" "Acceptance Criteria"
require_text "docs/phase-1-test-spec.md" "Postgres Availability"
require_text "docs/phase-1-test-spec.md" "Old-Document Baseline Checks"
require_text "docs/phase-1-test-spec.md" "not an absolute constraint"
require_text "docs/phase-1-test-spec.md" "Schema Tests"
require_text "docs/phase-1-test-spec.md" "Backtest Tests"
require_text "docs/phase-1-test-spec.md" "Safety Tests"

echo
echo "[verify] checking archived old-document baseline anchors..."
# These anchors intentionally pin the phase-1 starting baseline to representative
# archived strategy, sequence, risk, and architecture concepts.
require_text "(old)/# [자동매매 전략 기획서].md" "단타 전략"
require_text "(old)/# [자동매매 전략 기획서_고도화].md" "글로벌 베타 스로틀링"
require_text "(old)/# [자동매매 플로우 차트].md" "IOC 연사 탈출"
require_text "(old)/[자동매매_시퀀스_다이어그램].md" "Async NLP Blacklist"
require_text "(old)/[자동매매_통합_아키텍처_설계서].md" "Universal Quant Core"

echo
echo "[verify] success"
