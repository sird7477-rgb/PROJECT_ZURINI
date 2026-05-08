#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-.omx/review-results}"
CONTEXT_DIR="${CONTEXT_DIR:-.omx/review-context}"
PROMPT_DIR="${PROMPT_DIR:-.omx/review-prompts}"
EXTERNAL_REVIEW_DIR="${EXTERNAL_REVIEW_DIR:-.omx/external-review}"
REVIEW_STATE_DIR="${REVIEW_STATE_DIR:-.omx/reviewer-state}"
REVIEW_EXECUTION_MODE="${REVIEW_EXECUTION_MODE:-local}"
REVIEW_TIMEOUT_SECONDS="${REVIEW_TIMEOUT_SECONDS:-180}"
REVIEW_TIMEOUT_KILL_AFTER_SECONDS="${REVIEW_TIMEOUT_KILL_AFTER_SECONDS:-5}"
CLAUDE_REVIEW_TIMEOUT_SECONDS="${CLAUDE_REVIEW_TIMEOUT_SECONDS:-300}"
GEMINI_REVIEW_TIMEOUT_SECONDS="${GEMINI_REVIEW_TIMEOUT_SECONDS:-${REVIEW_TIMEOUT_SECONDS}}"
CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS="${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS:-300}"
GEMINI_PROMPT_ARG_MAX_BYTES="${GEMINI_PROMPT_ARG_MAX_BYTES:-100000}"
REVIEW_RETRY_LIMIT="${REVIEW_RETRY_LIMIT:-3}"
REVIEW_OUTPUT_MODE="${REVIEW_OUTPUT_MODE:-file}"
SKIP_CONTEXT_GENERATION="${SKIP_CONTEXT_GENERATION:-0}"
REVIEW_INCLUDE_UNTRACKED_CONTENT="${REVIEW_INCLUDE_UNTRACKED_CONTENT:-0}"
AI_MODEL_DISCOVERY="${AI_MODEL_DISCOVERY:-1}"
AI_MODEL_DISCOVERY_DIR="${AI_MODEL_DISCOVERY_DIR:-.omx/model-routing}"
AI_MODEL_ROUTING_ENV="${AI_MODEL_ROUTING_ENV:-${AI_MODEL_DISCOVERY_DIR}/latest.env}"
AI_MODEL_ROUTING_REPORT="${AI_MODEL_ROUTING_REPORT:-${AI_MODEL_DISCOVERY_DIR}/latest.md}"

mkdir -p "${OUT_DIR}" "${CONTEXT_DIR}" "${PROMPT_DIR}" "${EXTERNAL_REVIEW_DIR}" "${REVIEW_STATE_DIR}" "${AI_MODEL_DISCOVERY_DIR}"

if [ "${SKIP_CONTEXT_GENERATION}" = "1" ]; then
  echo "[review] using existing review context and prompts..."
  CONTEXT_FILE="$(find "${CONTEXT_DIR}" -maxdepth 1 -type f \( -name 'review-context-*.md' -o -name 'latest-review-context.md' \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
  CONTEXT_FILE="${CONTEXT_FILE:-existing context in ${CONTEXT_DIR}}"
else
  echo "[review] collecting review context..."
  CONTEXT_FILE="$(OUT_DIR="${CONTEXT_DIR}" INCLUDE_UNTRACKED_CONTENT="${REVIEW_INCLUDE_UNTRACKED_CONTENT}" ./scripts/collect-review-context.sh)"

  echo "[review] generating review prompts..."
  OUT_DIR="${PROMPT_DIR}" ./scripts/make-review-prompts.sh "${CONTEXT_FILE}" >/dev/null
fi

CLAUDE_PROMPT="${PROMPT_DIR}/claude-review.md"
GEMINI_PROMPT="${PROMPT_DIR}/gemini-review.md"

if [ ! -f "${CLAUDE_PROMPT}" ] || [ ! -f "${GEMINI_PROMPT}" ]; then
  echo "[review] review prompts missing; regenerate context without SKIP_CONTEXT_GENERATION=1"
  exit 1
fi

TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
CLAUDE_OUT="${OUT_DIR}/claude-review-${TIMESTAMP}.md"
GEMINI_OUT="${OUT_DIR}/gemini-review-${TIMESTAMP}.md"
CODEX_ARCHITECT_FALLBACK_OUT="${OUT_DIR}/codex-architect-fallback-${TIMESTAMP}.md"
CODEX_TEST_FALLBACK_OUT="${OUT_DIR}/codex-test-fallback-${TIMESTAMP}.md"
CODEX_FALLBACK_SUMMARY_OUT="${OUT_DIR}/codex-fallback-summary-${TIMESTAMP}.md"
SUMMARY_OUT="${OUT_DIR}/review-summary-${TIMESTAMP}.md"
EXTERNAL_RUNNER="${EXTERNAL_REVIEW_DIR}/run-reviewers-${TIMESTAMP}.sh"
EXTERNAL_LATEST="${EXTERNAL_REVIEW_DIR}/run-reviewers-latest.sh"

write_external_runner() {
  cat > "${EXTERNAL_RUNNER}" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail

script_dir="\$(CDPATH= cd -- "\$(dirname -- "\${BASH_SOURCE[0]}")" && pwd)"
if [ -x "\${script_dir}/../../scripts/run-ai-reviews.sh" ]; then
  repo_root="\$(CDPATH= cd -- "\${script_dir}/../.." && pwd)"
else
  repo_root="$(pwd)"
fi
cd "\${repo_root}"

: "\${OUT_DIR:=${OUT_DIR}}"
: "\${CONTEXT_DIR:=${CONTEXT_DIR}}"
: "\${PROMPT_DIR:=${PROMPT_DIR}}"
: "\${REVIEW_STATE_DIR:=${REVIEW_STATE_DIR}}"
: "\${REVIEW_TIMEOUT_SECONDS:=${REVIEW_TIMEOUT_SECONDS}}"
: "\${REVIEW_TIMEOUT_KILL_AFTER_SECONDS:=${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}}"
: "\${CLAUDE_REVIEW_TIMEOUT_SECONDS:=${CLAUDE_REVIEW_TIMEOUT_SECONDS}}"
: "\${GEMINI_REVIEW_TIMEOUT_SECONDS:=${GEMINI_REVIEW_TIMEOUT_SECONDS}}"
: "\${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS:=${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS}}"
: "\${GEMINI_PROMPT_ARG_MAX_BYTES:=${GEMINI_PROMPT_ARG_MAX_BYTES}}"
: "\${REVIEW_RETRY_LIMIT:=${REVIEW_RETRY_LIMIT}}"
: "\${REVIEW_OUTPUT_MODE:=tee}"
: "\${SKIP_CONTEXT_GENERATION:=1}"
: "\${REVIEW_INCLUDE_UNTRACKED_CONTENT:=${REVIEW_INCLUDE_UNTRACKED_CONTENT}}"
: "\${AI_MODEL_DISCOVERY:=${AI_MODEL_DISCOVERY}}"
: "\${AI_MODEL_DISCOVERY_DIR:=${AI_MODEL_DISCOVERY_DIR}}"
: "\${AI_MODEL_ROUTING_ENV:=${AI_MODEL_ROUTING_ENV}}"
: "\${AI_MODEL_ROUTING_REPORT:=${AI_MODEL_ROUTING_REPORT}}"

REVIEW_EXECUTION_MODE=local \\
OUT_DIR="\${OUT_DIR}" \\
CONTEXT_DIR="\${CONTEXT_DIR}" \\
PROMPT_DIR="\${PROMPT_DIR}" \\
REVIEW_STATE_DIR="\${REVIEW_STATE_DIR}" \\
REVIEW_TIMEOUT_SECONDS="\${REVIEW_TIMEOUT_SECONDS}" \\
REVIEW_TIMEOUT_KILL_AFTER_SECONDS="\${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" \\
CLAUDE_REVIEW_TIMEOUT_SECONDS="\${CLAUDE_REVIEW_TIMEOUT_SECONDS}" \\
GEMINI_REVIEW_TIMEOUT_SECONDS="\${GEMINI_REVIEW_TIMEOUT_SECONDS}" \\
CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS="\${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS}" \\
GEMINI_PROMPT_ARG_MAX_BYTES="\${GEMINI_PROMPT_ARG_MAX_BYTES}" \\
REVIEW_RETRY_LIMIT="\${REVIEW_RETRY_LIMIT}" \\
REVIEW_OUTPUT_MODE="\${REVIEW_OUTPUT_MODE}" \\
SKIP_CONTEXT_GENERATION="\${SKIP_CONTEXT_GENERATION}" \\
REVIEW_INCLUDE_UNTRACKED_CONTENT="\${REVIEW_INCLUDE_UNTRACKED_CONTENT}" \\
AI_MODEL_DISCOVERY="\${AI_MODEL_DISCOVERY}" \\
AI_MODEL_DISCOVERY_DIR="\${AI_MODEL_DISCOVERY_DIR}" \\
AI_MODEL_ROUTING_ENV="\${AI_MODEL_ROUTING_ENV}" \\
AI_MODEL_ROUTING_REPORT="\${AI_MODEL_ROUTING_REPORT}" \\
./scripts/run-ai-reviews.sh

RESULT_DIR="\${OUT_DIR}" OUT_DIR="\${OUT_DIR}" ./scripts/summarize-ai-reviews.sh
SCRIPT

  chmod +x "${EXTERNAL_RUNNER}"
  cp "${EXTERNAL_RUNNER}" "${EXTERNAL_LATEST}"
  chmod +x "${EXTERNAL_LATEST}"
}

if [ "${REVIEW_EXECUTION_MODE}" = "external" ]; then
  write_external_runner

  cat > "${SUMMARY_OUT}" <<SUMMARY
# AI Review Summary

Generated at: $(date -Iseconds)

## Inputs

- Context: ${CONTEXT_FILE}
- Claude prompt: ${CLAUDE_PROMPT}
- Gemini prompt: ${GEMINI_PROMPT}

## External Reviewer Command

Run this from an unrestricted interactive terminal:

    ${EXTERNAL_RUNNER}

Latest external reviewer command:

    ${EXTERNAL_LATEST}

## Notes

External mode prepares the review context and prompts, then stops before invoking reviewer CLIs in this restricted agent-run context.
SUMMARY

  echo "[review] external reviewer runner: ${EXTERNAL_RUNNER}"
  echo "[review] latest external reviewer runner: ${EXTERNAL_LATEST}"
  echo "[review] summary: ${SUMMARY_OUT}"
  echo "[review] external review pending"
  exit 2
fi

reset_disabled_reviewers() {
  case "${RESET_DISABLED_AI_REVIEWERS:-}" in
    all)
      rm -f "${REVIEW_STATE_DIR}/claude.disabled" "${REVIEW_STATE_DIR}/gemini.disabled"
      ;;
    claude)
      rm -f "${REVIEW_STATE_DIR}/claude.disabled"
      ;;
    gemini)
      rm -f "${REVIEW_STATE_DIR}/gemini.disabled"
      ;;
    "")
      ;;
    *)
      echo "[review] unknown RESET_DISABLED_AI_REVIEWERS value: ${RESET_DISABLED_AI_REVIEWERS}"
      ;;
  esac
}

reset_disabled_reviewers

load_model_routing() {
  if [ "${AI_MODEL_DISCOVERY}" = "0" ]; then
    echo "[review] AI model discovery disabled by AI_MODEL_DISCOVERY=0"
    return 0
  fi

  if [ ! -x "./scripts/discover-ai-models.sh" ]; then
    echo "[review] AI model discovery script missing; using provider defaults"
    return 0
  fi

  echo "[review] discovering AI model routing..."
  if AI_MODEL_DISCOVERY_DIR="${AI_MODEL_DISCOVERY_DIR}" \
    AI_MODEL_ROUTING_ENV="${AI_MODEL_ROUTING_ENV}" \
    AI_MODEL_ROUTING_REPORT="${AI_MODEL_ROUTING_REPORT}" \
    ./scripts/discover-ai-models.sh >/dev/null; then
    # shellcheck disable=SC1090
    . "${AI_MODEL_ROUTING_ENV}"
    echo "[review] model routing report: ${AI_MODEL_ROUTING_REPORT}"
    echo "[review] selected models: claude=${CLAUDE_REVIEW_MODEL:-provider-default} gemini=${GEMINI_REVIEW_MODEL:-provider-default} codex_architect=${CODEX_ARCHITECT_REVIEW_MODEL:-provider-default} codex_test=${CODEX_TEST_REVIEW_MODEL:-provider-default}"
  else
    echo "[review] AI model discovery failed; using provider defaults"
  fi
}

help_supports_flag() {
  local help_text="$1"
  local flag="$2"

  printf '%s\n' "${help_text}" | grep -Eq "(^|[^[:alnum:]_-])${flag}($|[^[:alnum:]_-])"
}

reviewer_disabled_file() {
  echo "${REVIEW_STATE_DIR}/$1.disabled"
}

disable_reviewer() {
  local reviewer="$1"
  local reason="$2"
  local details="$3"
  local disabled_file
  disabled_file="$(reviewer_disabled_file "${reviewer}")"

  {
    echo "reviewer=${reviewer}"
    echo "disabled_at=$(date -Iseconds)"
    echo "reason=${reason}"
    echo "details=${details}"
  } > "${disabled_file}"

  echo "[review] ${reviewer} review disabled until user re-enables it: ${reason} (${details})"
}

disabled_reason() {
  local reviewer="$1"
  local disabled_file
  disabled_file="$(reviewer_disabled_file "${reviewer}")"

  if [ ! -f "${disabled_file}" ]; then
    return 1
  fi

  local reason details disabled_at
  reason="$(sed -n 's/^reason=//p' "${disabled_file}")"
  details="$(sed -n 's/^details=//p' "${disabled_file}")"
  disabled_at="$(sed -n 's/^disabled_at=//p' "${disabled_file}")"
  echo "reason=${reason}; details=${details}; disabled_at=${disabled_at}"
}

write_disabled_result() {
  local reviewer="$1"
  local output_file="$2"
  local reason="$3"

  echo "[review] ${reviewer} review skipped: disabled until user re-enables it (${reason})"
  cat > "${output_file}" <<MSG
# ${reviewer^} Review

Skipped: ${reviewer} review is disabled until the user re-enables it.

Reason:
${reason}

To re-enable:
- RESET_DISABLED_AI_REVIEWERS=${reviewer} ./scripts/run-ai-reviews.sh
- RESET_DISABLED_AI_REVIEWERS=all ./scripts/run-ai-reviews.sh
MSG
}

is_limit_failure() {
  local output_file="$1"

  grep -qiE 'hit your limit|usage limit|session limit|weekly limit|week limit|rate limit|quota|RESOURCE_EXHAUSTED|resets [0-9]|resets [ap]m|limit reached' "${output_file}"
}

has_usable_verdict() {
  local output_file="$1"

  awk '
    BEGIN { in_verdict = 0; in_code = 0 }
    /^```/ {
      in_code = !in_code
      next
    }
    in_code {
      next
    }
    tolower($0) ~ /^#+[[:space:]]+verdict[[:space:]:.-]*$/ { in_verdict = 1; next }
    in_verdict && /^#+[[:space:]]+/ { exit }
    in_verdict && /^[[:space:]]*$/ { next }
    in_verdict {
      if ($0 ~ /^[[:space:]]*>/) {
        next
      }
      if ($0 ~ /^[[:space:]]*([-*+]|\(?[0-9]+[.)])([[:space:]]|$)/) {
        next
      }
      verdict = tolower($0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", verdict)
      gsub(/^`+|`+$/, "", verdict)
      gsub(/^\*\*|\*\*$/, "", verdict)
      gsub(/[^a-z_]/, "", verdict)
      if (verdict == "approve" || verdict == "approve_with_notes" || verdict == "request_changes") {
        found = 1
        exit
      }
    }
    END { exit found ? 0 : 1 }
  ' "${output_file}"
}

run_review_command() {
  local output_file="$1"
  shift

  if [ "${REVIEW_OUTPUT_MODE}" = "tee" ]; then
    "$@" 2>&1 | tee "${output_file}"
    return "${PIPESTATUS[0]}"
  fi

  "$@" > "${output_file}" 2>&1
}

run_review_command_stdin() {
  local output_file="$1"
  local input_file="$2"
  shift 2

  if [ "${REVIEW_OUTPUT_MODE}" = "tee" ]; then
    "$@" < "${input_file}" 2>&1 | tee "${output_file}"
    return "${PIPESTATUS[0]}"
  fi

  "$@" < "${input_file}" > "${output_file}" 2>&1
}

run_with_retries() {
  local reviewer="$1"
  local output_file="$2"
  shift 2

  local attempt=1
  local status=0

  while [ "${attempt}" -le "${REVIEW_RETRY_LIMIT}" ]; do
    echo "[review] ${reviewer} attempt ${attempt}/${REVIEW_RETRY_LIMIT}"
    "$@"
    status=$?

    if [ "${status}" -eq 0 ] && has_usable_verdict "${output_file}"; then
      return 0
    fi

    if is_limit_failure "${output_file}"; then
      disable_reviewer "${reviewer}" "usage_limit" "reviewer reported a session, weekly, quota, or rate limit"
      return "${status}"
    fi

    if [ "${status}" -eq 0 ]; then
      status=1
      echo "[review] ${reviewer} produced no usable ## Verdict section"
    fi

    echo "[review] ${reviewer} attempt ${attempt}/${REVIEW_RETRY_LIMIT} failed with status ${status}"
    attempt=$((attempt + 1))
  done

  disable_reviewer "${reviewer}" "retry_exhausted" "no usable response after ${REVIEW_RETRY_LIMIT} attempts"
  return "${status}"
}

run_claude() {
  if [ "${RUN_CLAUDE_REVIEW:-1}" = "0" ]; then
    echo "[review] Claude review disabled by RUN_CLAUDE_REVIEW=0"
    cat > "${CLAUDE_OUT}" <<MSG
# Claude Review

Skipped: Claude review was disabled by RUN_CLAUDE_REVIEW=0.
MSG
    return 0
  fi

  local disabled
  if disabled="$(disabled_reason claude)"; then
    write_disabled_result "claude" "${CLAUDE_OUT}" "${disabled}"
    return 0
  fi

  if ! command -v claude >/dev/null 2>&1; then
    echo "[review] claude command not found; skipping Claude review"
    cat > "${CLAUDE_OUT}" <<MSG
# Claude Review

Skipped: claude command not found.
MSG
    return 0
  fi

  echo "[review] running Claude review..."

  set +e
  claude_help="$(claude --help 2>/dev/null)"
  if printf '%s\n' "${claude_help}" | grep -q -- '--print'; then
    claude_args=(--print)

    if printf '%s\n' "${claude_help}" | grep -q -- '--no-session-persistence'; then
      claude_args+=(--no-session-persistence)
    fi

    if printf '%s\n' "${claude_help}" | grep -q -- '--permission-mode'; then
      claude_args+=(--permission-mode plan)
    fi

    if [ -n "${CLAUDE_REVIEW_MODEL:-}" ] && help_supports_flag "${claude_help}" "--model"; then
      claude_args+=(--model "${CLAUDE_REVIEW_MODEL}")
    fi

    run_with_retries "claude" "${CLAUDE_OUT}" run_review_command "${CLAUDE_OUT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${CLAUDE_REVIEW_TIMEOUT_SECONDS}" claude "${claude_args[@]}" "$(cat "${CLAUDE_PROMPT}")"
  else
    run_with_retries "claude" "${CLAUDE_OUT}" run_review_command_stdin "${CLAUDE_OUT}" "${CLAUDE_PROMPT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${CLAUDE_REVIEW_TIMEOUT_SECONDS}" claude
  fi
  status=$?
  set -e

  if [ "${status}" -ne 0 ]; then
    {
      echo
      echo "---"
      echo
      echo "Claude review failed or timed out."
      echo "Exit status: ${status}"
      echo "Timeout seconds: ${CLAUDE_REVIEW_TIMEOUT_SECONDS}"
      echo
      echo "Known possible causes in agent-run contexts:"
      echo "- Anthropic API/network access is blocked or refused"
      echo "- Claude cannot write under its runtime directory"
      echo "- Claude authentication is unavailable in bare or isolated mode"
    } >> "${CLAUDE_OUT}"
    echo "[review] Claude review failed; result captured: ${CLAUDE_OUT}"
    return 0
  fi

  echo "[review] Claude result: ${CLAUDE_OUT}"
}

run_gemini() {
  if [ "${RUN_GEMINI_REVIEW:-1}" = "0" ]; then
    echo "[review] Gemini review disabled; unset RUN_GEMINI_REVIEW or set RUN_GEMINI_REVIEW=1 to enable"
    cat > "${GEMINI_OUT}" <<MSG
# Gemini Review

Skipped: Gemini review was disabled by RUN_GEMINI_REVIEW=0.

Reason:
- Gemini CLI may enter interactive or agent mode.
- Previous runs hung or failed with capacity/tool errors.
- The default is to run Gemini; set RUN_GEMINI_REVIEW=0 to opt out for a specific gate run.
MSG
    return 0
  fi

  local disabled
  if disabled="$(disabled_reason gemini)"; then
    write_disabled_result "gemini" "${GEMINI_OUT}" "${disabled}"
    return 0
  fi

  if ! command -v gemini >/dev/null 2>&1; then
    echo "[review] gemini command not found; skipping Gemini review"
    cat > "${GEMINI_OUT}" <<MSG
# Gemini Review

Skipped: gemini command not found.
MSG
    return 0
  fi

  echo "[review] running Gemini review..."

  set +e
  gemini_help="$(gemini --help 2>/dev/null)"
  if printf '%s\n' "${gemini_help}" | grep -q -- '--prompt'; then
    gemini_prompt_bytes="$(wc -c < "${GEMINI_PROMPT}")"

    if [ "${gemini_prompt_bytes}" -gt "${GEMINI_PROMPT_ARG_MAX_BYTES}" ]; then
      gemini_args=(--prompt "Review the Markdown prompt provided on stdin.")
      gemini_stdin_mode=1
    else
      gemini_args=(--prompt "$(cat "${GEMINI_PROMPT}")")
      gemini_stdin_mode=0
    fi

    if printf '%s\n' "${gemini_help}" | grep -q -- '--approval-mode'; then
      gemini_args+=(--approval-mode plan)
    fi

    if printf '%s\n' "${gemini_help}" | grep -q -- '--skip-trust'; then
      gemini_args+=(--skip-trust)
    fi

    if printf '%s\n' "${gemini_help}" | grep -q -- '--output-format'; then
      gemini_args+=(--output-format text)
    fi

    if [ -n "${GEMINI_REVIEW_MODEL:-}" ] && help_supports_flag "${gemini_help}" "--model"; then
      gemini_args+=(--model "${GEMINI_REVIEW_MODEL}")
    fi

    if [ "${gemini_stdin_mode}" -eq 1 ]; then
      run_with_retries "gemini" "${GEMINI_OUT}" run_review_command_stdin "${GEMINI_OUT}" "${GEMINI_PROMPT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini "${gemini_args[@]}"
    else
      run_with_retries "gemini" "${GEMINI_OUT}" run_review_command "${GEMINI_OUT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini "${gemini_args[@]}"
    fi
  else
    run_with_retries "gemini" "${GEMINI_OUT}" run_review_command_stdin "${GEMINI_OUT}" "${GEMINI_PROMPT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini
  fi
  status=$?
  set -e

  if [ "${status}" -ne 0 ]; then
    {
      echo
      echo "---"
      echo
      echo "Gemini review failed or timed out."
      echo "Exit status: ${status}"
      echo "Timeout seconds: ${GEMINI_REVIEW_TIMEOUT_SECONDS}"
      echo
      echo "Known possible causes:"
      echo "- Gemini model capacity exhausted"
      echo "- Gemini authentication is unavailable in the current context"
      echo "- Gemini stdin fallback was consumed by an auth prompt instead of review input"
      echo "- CLI tool permissions differ from this repository workflow"
      echo "- Gemini CLI entered an agent/tool mode instead of plain review mode"
    } >> "${GEMINI_OUT}"
    echo "[review] Gemini review failed; result captured: ${GEMINI_OUT}"
    return 0
  fi

  echo "[review] Gemini result: ${GEMINI_OUT}"
}

codex_persona_needed() {
  [ -f "$(reviewer_disabled_file claude)" ] || [ -f "$(reviewer_disabled_file gemini)" ]
}

generate_codex_fallback_summary() {
  if ! codex_persona_needed; then
    cat > "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG
# Codex Fallback Review

Generated at: $(date -Iseconds)

## Status

none

## Assigned Fallback Reviewers

none

## Gate Policy

No Codex fallback review was needed for this run.
MSG
    return 0
  fi

  echo "[review] generating Codex fallback review summary: ${CODEX_FALLBACK_SUMMARY_OUT}"

  cat > "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG
# Codex Fallback Review

Generated at: $(date -Iseconds)

## Status

informational_only

## Independence Boundary

This is Codex/GPT fallback coverage for disabled external reviewers. It is degraded, informational-only, and not an independent Claude or Gemini approval.

## Assigned Fallback Reviewers
MSG

  if [ -f "$(reviewer_disabled_file claude)" ]; then
    cat >> "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG

- codex-architect-review
  - covers the disabled Claude lane
  - focus: correctness, maintainability, scope control, hidden risk, AGENTS.md and workflow compliance
  - disabled reason: $(disabled_reason claude)
  - artifact: ${CODEX_ARCHITECT_FALLBACK_OUT}
MSG
  fi

  if [ -f "$(reviewer_disabled_file gemini)" ]; then
    cat >> "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG

- codex-test-alternative-review
  - covers the disabled Gemini lane
  - focus: missed edge cases, simpler alternatives, test coverage gaps, documentation clarity, future automation friction
  - disabled reason: $(disabled_reason gemini)
  - artifact: ${CODEX_TEST_FALLBACK_OUT}
MSG
  fi

  if [ -f "$(reviewer_disabled_file claude)" ] && [ -f "$(reviewer_disabled_file gemini)" ]; then
    cat >> "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG

## Complete External Reviewer Outage

Both Claude and Gemini are disabled. Two Codex/GPT fallback reviews are required, but this remains codex_only_degraded coverage.
MSG
  fi

  cat >> "${CODEX_FALLBACK_SUMMARY_OUT}" <<MSG

## Required Checklist

- Verify disabled reviewer reasons are visible in every run.
- Verify external reviewer prompts stay role-pure and do not simulate another model's perspective.
- Verify summary reports degraded fallback coverage instead of multi_reviewer when external reviewers are missing.
- Verify Codex fallback is not counted as independent Claude or Gemini reviewer approval.
- Verify re-enable instructions are present for disabled reviewers.

## Gate Policy

Codex fallback can reduce blind spots during reviewer outages, but it does not upgrade review coverage to multi_reviewer.
MSG
}

write_codex_fallback_skipped() {
  local output_file="$1"
  local persona="$2"
  local reason="$3"

  cat > "${output_file}" <<MSG
# ${persona}

## Status

skipped

Skipped: ${reason}

## Reason

${reason}

## Verdict

missing
MSG
}

write_codex_fallback_prompt() {
  local prompt_file="$1"
  local persona="$2"
  local disabled_reviewer="$3"
  local focus="$4"
  local reason
  reason="$(disabled_reason "${disabled_reviewer}")"

  cat > "${prompt_file}" <<MSG
# ${persona}

You are running as a Codex/GPT fallback reviewer because ${disabled_reviewer} is disabled.

This is a degraded fallback review. Do not claim to be an independent external Claude or Gemini reviewer.

Focus:
${focus}

Return exactly this Markdown structure:

## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes

## Findings

List concrete issues only. If no blocking issues exist, say "No blocking findings."

## Fallback Boundary

State that this is Codex/GPT fallback coverage and not independent external review.

## Final Recommendation

Give a short recommendation for the review gate.

Disabled reviewer reason:
${reason}

---

MSG

  if [ -f "${CONTEXT_FILE}" ]; then
    cat "${CONTEXT_FILE}" >> "${prompt_file}"
  else
    cat >> "${prompt_file}" <<MSG
Review context file is unavailable: ${CONTEXT_FILE}
MSG
  fi
}

run_codex_fallback_review() {
  local persona="$1"
  local output_file="$2"
  local disabled_reviewer="$3"
  local focus="$4"
  local prompt_file="${OUT_DIR}/${persona}-${TIMESTAMP}-prompt.md"
  local log_file="${output_file}.log"
  local codex_model=""
  local codex_model_args=()

  case "${persona}" in
    codex-architect-review)
      codex_model="${CODEX_ARCHITECT_REVIEW_MODEL:-}"
      ;;
    codex-test-alternative-review)
      codex_model="${CODEX_TEST_REVIEW_MODEL:-}"
      ;;
  esac

  if [ "${RUN_CODEX_FALLBACK_REVIEW:-1}" = "0" ]; then
    write_codex_fallback_skipped "${output_file}" "${persona}" "RUN_CODEX_FALLBACK_REVIEW=0"
    return 0
  fi

  if ! command -v codex >/dev/null 2>&1; then
    write_codex_fallback_skipped "${output_file}" "${persona}" "codex command not found"
    return 0
  fi

  if [ -n "${codex_model}" ]; then
    codex_exec_help="$(codex exec --help 2>/dev/null || true)"
    if help_supports_flag "${codex_exec_help}" "--model"; then
      codex_model_args=(--model "${codex_model}")
    else
      echo "[review] Codex model selector ignored for ${persona}: codex exec does not advertise --model"
    fi
  fi

  write_codex_fallback_prompt "${prompt_file}" "${persona}" "${disabled_reviewer}" "${focus}"
  echo "[review] running ${persona} Codex fallback review..."

  set +e
  timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS}" \
    codex exec "${codex_model_args[@]}" --cd "$(pwd)" --sandbox read-only --ephemeral -o "${output_file}" - < "${prompt_file}" > "${log_file}" 2>&1
  status=$?
  set -e

  if [ "${status}" -ne 0 ]; then
    {
      echo "# ${persona}"
      echo
      echo "## Status"
      echo
      echo "failed"
      echo
      echo "Codex fallback review failed or timed out."
      echo
      echo "Exit status: ${status}"
      echo "Timeout seconds: ${CODEX_FALLBACK_REVIEW_TIMEOUT_SECONDS}"
      echo "Log file: ${log_file}"
      echo
      echo "## Verdict"
      echo
      echo "failed"
    } > "${output_file}"
    echo "[review] ${persona} Codex fallback failed; result captured: ${output_file}"
    return 0
  fi

  if ! has_usable_verdict "${output_file}"; then
    {
      echo
      echo "---"
      echo
      echo "Codex fallback review produced no usable ## Verdict section."
      echo "Log file: ${log_file}"
    } >> "${output_file}"
  fi

  echo "[review] ${persona} Codex fallback result: ${output_file}"
}

run_codex_fallback_reviews() {
  if ! codex_persona_needed; then
    return 0
  fi

  if [ -f "$(reviewer_disabled_file claude)" ]; then
    run_codex_fallback_review \
      "codex-architect-review" \
      "${CODEX_ARCHITECT_FALLBACK_OUT}" \
      "claude" \
      "- correctness
- maintainability
- scope control
- hidden risk
- AGENTS.md and docs/WORKFLOW.md compliance"
  fi

  if [ -f "$(reviewer_disabled_file gemini)" ]; then
    run_codex_fallback_review \
      "codex-test-alternative-review" \
      "${CODEX_TEST_FALLBACK_OUT}" \
      "gemini" \
      "- missed edge cases
- simpler alternatives
- test coverage gaps
- documentation clarity
- future automation friction"
  fi
}

load_model_routing
run_claude
run_gemini
run_codex_fallback_reviews
generate_codex_fallback_summary

cat > "${SUMMARY_OUT}" <<SUMMARY
# AI Review Summary

Generated at: $(date -Iseconds)

## Inputs

- Context: ${CONTEXT_FILE}
- Claude prompt: ${CLAUDE_PROMPT}
- Gemini prompt: ${GEMINI_PROMPT}
- Model routing report: ${AI_MODEL_ROUTING_REPORT}

## Outputs

- Claude result: ${CLAUDE_OUT}
- Gemini result: ${GEMINI_OUT}
- Codex architect fallback: ${CODEX_ARCHITECT_FALLBACK_OUT}
- Codex test fallback: ${CODEX_TEST_FALLBACK_OUT}
- Codex fallback summary: ${CODEX_FALLBACK_SUMMARY_OUT}

## Notes

A reviewer failure does not fail this script. Failures are captured in the corresponding result file.
SUMMARY

echo "[review] summary: ${SUMMARY_OUT}"
echo "[review] done"
