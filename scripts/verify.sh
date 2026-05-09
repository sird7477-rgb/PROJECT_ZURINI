#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "[verify] fail: $1" >&2
  exit 1
}

log() {
  printf '[verify] %s %s\n' "$(date -Is)" "$*"
}

require_file() {
  local path="$1"
  [ -f "$path" ] || fail "missing required file: ${path}"
  log "file ok: ${path}"
}

require_text() {
  local path="$1"
  local pattern="$2"
  if ! grep -Fq "$pattern" "$path"; then
    fail "missing expected text in ${path}: ${pattern}"
  fi
  log "anchor ok: ${path} :: ${pattern}"
}

require_absent_text() {
  local pattern="$1"
  local label="$2"
  local index="$3"
  local total="$4"
  local path
  local found=0
  local scan_list
  log "sensitive scan ${index}/${total} start: ${label}"

  # Scope the secret scan to files that can be committed: tracked files plus
  # untracked files not ignored by .gitignore. Large ignored raw-data/report
  # trees are intentionally excluded from this repository-persistence gate.
  scan_list="$(mktemp)"
  git ls-files --cached --others --exclude-standard -z > "$scan_list" || fail "failed to enumerate git candidate files"
  while IFS= read -r -d '' path; do
    if [ "$path" = ".env" ]; then
      continue
    fi
    if grep -F -q -- "$pattern" "$path"; then
      found=1
      break
    fi
  done < "$scan_list"
  rm -f "$scan_list"

  if [ "$found" -eq 1 ]; then
    fail "sensitive literal must not be stored in repository files"
  fi
  log "sensitive scan ${index}/${total} ok: ${label}"
}

require_env_not_tracked() {
  if git ls-files --cached --error-unmatch .env >/dev/null 2>&1; then
    fail ".env must not be tracked or staged"
  fi
  log ".env not tracked or staged"
}

require_executable_script() {
  local path="$1"
  local index_mode

  [ -x "$path" ] || fail "script is not executable in working tree: ${path}"

  index_mode="$(git ls-files --stage -- "$path" | cut -d ' ' -f 1 | head -n 1)"
  if [ -n "$index_mode" ] && [ "$index_mode" != "100755" ]; then
    fail "script is not executable in git index: ${path} (${index_mode})"
  fi

  log "executable ok: ${path}"
}

log "start"
log "checking review summary fixture logic..."
./scripts/test-review-summary.sh

echo
log "checking project memory helper secret screening..."
memory_test_file="$(mktemp)"
rm -f "$memory_test_file"
OMX_PROJECT_MEMORY_FILE="$memory_test_file" ./scripts/record-project-memory.sh \
  --category workflow \
  --content "safe automation merge memory" \
  --source "verify-smoke" >/dev/null
if OMX_PROJECT_MEMORY_FILE="$memory_test_file" ./scripts/record-project-memory.sh \
  --category workflow \
  --content "safe automation merge memory" \
  --source "api_key: should-not-store" >/dev/null 2>&1; then
  rm -f "$memory_test_file"
  fail "record-project-memory accepted secret-like source text"
fi
rm -f "$memory_test_file"

log "checking feedback helper secret screening..."
feedback_test_file="$(mktemp)"
rm -f "$feedback_test_file"
OMX_FEEDBACK_QUEUE_FILE="$feedback_test_file" ./scripts/record-feedback.sh \
  --repeat-key "verify:feedback-secret-screen" \
  --summary "safe feedback smoke" \
  --source "verify-smoke" >/dev/null
if OMX_FEEDBACK_QUEUE_FILE="$feedback_test_file" ./scripts/record-feedback.sh \
  --repeat-key "verify:feedback-secret-screen" \
  --summary "safe feedback smoke" \
  --source "token: should-not-store" >/dev/null 2>&1; then
  rm -f "$feedback_test_file"
  fail "record-feedback accepted secret-like source text"
fi
rm -f "$feedback_test_file"

echo
log "checking automation files..."
DOCTOR_SKIP_DIRTY_CHECK=1 ./scripts/automation-doctor.sh

echo
log "checking PROJECT_ZURINI onboarding baseline..."
require_file "AGENTS.md"
require_file "docs/WORKFLOW.md"
require_file "docs/AI_MODEL_ROUTING.md"
require_file "docs/AUTOMATION_OPERATING_POLICY.md"
require_file "docs/SESSION_QUALITY_PLAN.md"
require_file "docs/DATA_COMPLETION.md"
require_file "docs/DEPLOYMENT_COMPLETION.md"
require_file "docs/OBSERVABILITY_COMPLETION.md"
require_file "docs/PERFORMANCE_COMPLETION.md"
require_file "docs/SECURITY_COMPLETION.md"
require_file "docs/UI_COMPLETION.md"
require_file "docs/phase-1-development.md"
require_file "docs/phase-1-prd.md"
require_file "docs/phase-1-test-spec.md"
require_file "docs/phase-1-baseline.md"
require_file "docs/phase-1-completion.md"
require_file "docs/phase-1.5-large-dummy-rehearsal.md"
require_file "docs/phase-2-real-data-runbook.md"
require_file "docs/api-smoke-tests.md"
require_file "docs/strategy-baseline.md"
require_file "docs/backtest-report-analysis.md"
require_file "references/api/README.md"
require_file "references/api/credentials-inventory.md"
require_file ".env.example"
require_file "pyproject.toml"
require_file "docker-compose.yml"
require_file "config/phase1-backtest.toml"
require_file "src/zurini/data/schema.sql"
require_file "scripts/review-gate.sh"
require_file "(old)/# [자동매매 전략 기획서].md"
require_file "(old)/# [자동매매 전략 기획서_고도화].md"
require_file "(old)/# [자동매매 플로우 차트].md"
require_file "(old)/[자동매매_시퀀스_다이어그램].md"
require_file "(old)/[자동매매_통합_아키텍처_설계서].md"

require_executable_script "scripts/automation-doctor.sh"
require_executable_script "scripts/archive-omx-artifacts.sh"
require_executable_script "scripts/collect-review-context.sh"
require_executable_script "scripts/discover-ai-models.sh"
require_executable_script "scripts/make-review-prompts.sh"
require_executable_script "scripts/record-feedback.sh"
require_executable_script "scripts/record-project-memory.sh"
require_executable_script "scripts/review-gate.sh"
require_executable_script "scripts/run-ai-reviews.sh"
require_executable_script "scripts/summarize-ai-reviews.sh"
require_executable_script "scripts/test-review-summary.sh"
require_executable_script "scripts/verify.sh"
require_executable_script "scripts/write-session-checkpoint.sh"

require_text "AGENTS.md" "phase-1 development"
require_text "AGENTS.md" "starting baseline for trading"
require_text "AGENTS.md" "not absolute"
require_text "AGENTS.md" "Phase 1 ends at a reproducible local backtest"
require_text "AGENTS.md" "Docker Compose Postgres"
require_text "AGENTS.md" "Automation Template Merge Policy"
require_text "docs/WORKFLOW.md" "재현 가능한 로컬 백테스트"
require_text "docs/WORKFLOW.md" "출발 기준"
require_text "docs/WORKFLOW.md" "절대 기준이 아니다"
require_text "docs/WORKFLOW.md" "references/api/"
require_text "docs/WORKFLOW.md" "자동화 기반 병합 정책"
require_text "docs/AI_MODEL_ROUTING.md" "role-first"
require_text "docs/AUTOMATION_OPERATING_POLICY.md" "Review Intensity"
require_text "docs/SESSION_QUALITY_PLAN.md" "Model Routing Cache"
require_text "docs/DATA_COMPLETION.md" "Data Completion"
require_text "docs/DEPLOYMENT_COMPLETION.md" "Deployment Completion"
require_text "docs/OBSERVABILITY_COMPLETION.md" "Observability Completion"
require_text "docs/PERFORMANCE_COMPLETION.md" "Performance Completion"
require_text "docs/SECURITY_COMPLETION.md" "Security Completion"
require_text "docs/UI_COMPLETION.md" "UI Completion"
require_text "docs/WORKFLOW.md" "유지/제안 후 승인"
require_text "docs/WORKFLOW.md" "실전 주문 관련 버튼은 표시하더라도 잠금 상태"
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
require_text "docs/phase-1-test-spec.md" "most recently saved old document"
require_text "docs/phase-1-test-spec.md" "conservative conflict handling applies only"
require_text "docs/phase-1-test-spec.md" "real historical 1-minute data acquisition is deferred"
require_text "docs/phase-1-test-spec.md" "2026-05-09"
require_text "docs/phase-1-test-spec.md" "multi-symbol dummy data"
require_text "docs/phase-1-test-spec.md" "CLI smoke test"
require_text "docs/phase-1-test-spec.md" "JSON, CSV, and text report outputs"
require_text "docs/phase-1-baseline.md" "VWAP first-pullback"
require_text "docs/phase-1-baseline.md" "Global beta throttle"
require_text "docs/phase-1-baseline.md" "Blacklist behavior"
require_text "docs/phase-1-baseline.md" "symbol + timestamp"
require_text "docs/phase-1-baseline.md" "friction layer"
require_text "docs/phase-1-baseline.md" "most recently saved old document"
require_text "docs/phase-1-baseline.md" "saved-time evidence is unavailable or tied"
require_text "docs/phase-1-baseline.md" "Real historical 1-minute data acquisition starts after"
require_text "docs/phase-1-baseline.md" "multi-symbol execution"
require_text "docs/phase-1-baseline.md" "Rationale for adding multi-symbol support"
require_text "docs/phase-1-baseline.md" "CLI path"
require_text "docs/phase-1-baseline.md" "JSON, CSV, and text reports"
require_text "docs/phase-1-completion.md" "Phase 1 is ready"
require_text "docs/phase-1-completion.md" "Acceptance-Criteria Mapping"
require_text "docs/phase-1-completion.md" "Daishin Securities CYBOS"
require_text "docs/phase-1.5-large-dummy-rehearsal.md" "Synthetic Large-Dummy Rehearsal"
require_text "docs/phase-1.5-large-dummy-rehearsal.md" "Daishin Securities CYBOS"
require_text "docs/phase-1.5-large-dummy-rehearsal.md" "accelerated logical time"
require_text "docs/phase-1.5-large-dummy-rehearsal.md" "not a strategy validation result"
require_text "docs/phase-2-real-data-runbook.md" "Phase 2 Real-Data Runbook"
require_text "docs/phase-2-real-data-runbook.md" "Korea Investment Securities only"
require_text "docs/phase-2-real-data-runbook.md" "acceptance.status"
require_text "docs/api-smoke-tests.md" "API Smoke Tests"
require_text "docs/api-smoke-tests.md" "Do not inspect or print"
require_text "docs/strategy-baseline.md" "Strategy Baseline"
require_text "docs/backtest-report-analysis.md" "Backtest Report Analysis Template"
require_text "references/api/README.md" "API Reference Vault"
require_text "references/api/README.md" "Do not place secrets"
require_text "references/api/README.md" "real historical-data ingestion"
require_text "references/api/credentials-inventory.md" "does not contain real secrets"
require_text "references/api/credentials-inventory.md" "as exposed"
require_text ".env.example" "GEMINI_API_KEY="
require_text ".env.example" "KIS_LIVE_APP_SECRET="

echo
log "checking that provided secret literals are not persisted..."
require_env_not_tracked
require_absent_text "AI""za" "gemini key prefix" 1 6
require_absent_text "AAH""x3" "telegram token prefix" 2 6
require_absent_text "PSH""Slf" "KIS live app key prefix" 3 6
require_absent_text "PS9""KYZ" "KIS paper app key prefix" 4 6
require_absent_text "fly""lmj" "daishin id literal" 5 6
require_absent_text "373""69c" "daishin password/cert prefix" 6 6

echo
log "checking archived old-document baseline anchors..."
# These anchors intentionally pin the phase-1 starting baseline to representative
# archived strategy, sequence, risk, and architecture concepts.
require_text "(old)/# [자동매매 전략 기획서].md" "단타 전략"
require_text "(old)/# [자동매매 전략 기획서_고도화].md" "글로벌 베타 스로틀링"
require_text "(old)/# [자동매매 플로우 차트].md" "IOC 연사 탈출"
require_text "(old)/[자동매매_시퀀스_다이어그램].md" "Async NLP Blacklist"
require_text "(old)/[자동매매_통합_아키텍처_설계서].md" "Universal Quant Core"

echo
log "starting local Postgres..."
docker compose up -d db
for attempt in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U zurini -d zurini >/dev/null 2>&1; then
    log "Postgres ready on attempt ${attempt}/30"
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    fail "Postgres did not become ready"
  fi
  log "Postgres not ready yet: attempt ${attempt}/30"
  sleep 1
done

echo
log "running pytest..."
if [ -x ".venv/bin/python" ]; then
  .venv/bin/python -m pytest
else
  python3 -m pytest
fi

echo
log "success"
