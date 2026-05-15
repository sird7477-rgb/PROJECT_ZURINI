#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
CLAUDE_PROMPT_ARG_MAX_BYTES="${CLAUDE_PROMPT_ARG_MAX_BYTES:-100000}"
GEMINI_PROMPT_ARG_MAX_BYTES="${GEMINI_PROMPT_ARG_MAX_BYTES:-100000}"
GEMINI_PROMPT_MAX_BYTES="${GEMINI_PROMPT_MAX_BYTES:-750000}"
REVIEW_CONTEXT_MAX_BYTES="${REVIEW_CONTEXT_MAX_BYTES:-750000}"
REVIEW_CONTEXT_DETAIL="${REVIEW_CONTEXT_DETAIL:-auto}"
REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES="${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES:-50000}"
REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES="${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES:-80}"
REVIEW_RETRY_LIMIT="${REVIEW_RETRY_LIMIT:-3}"
REVIEW_OUTPUT_MODE="${REVIEW_OUTPUT_MODE:-file}"
SKIP_CONTEXT_GENERATION="${SKIP_CONTEXT_GENERATION:-0}"
REVIEW_INCLUDE_UNTRACKED_CONTENT="${REVIEW_INCLUDE_UNTRACKED_CONTENT:-0}"
AI_MODEL_DISCOVERY="${AI_MODEL_DISCOVERY:-1}"
AI_MODEL_DISCOVERY_DIR="${AI_MODEL_DISCOVERY_DIR:-.omx/model-routing}"
AI_MODEL_ROUTING_ENV="${AI_MODEL_ROUTING_ENV:-${AI_MODEL_DISCOVERY_DIR}/latest.env}"
AI_MODEL_ROUTING_REPORT="${AI_MODEL_ROUTING_REPORT:-${AI_MODEL_DISCOVERY_DIR}/latest.md}"

mkdir -p "${OUT_DIR}" "${CONTEXT_DIR}" "${PROMPT_DIR}" "${EXTERNAL_REVIEW_DIR}" "${REVIEW_STATE_DIR}" "${AI_MODEL_DISCOVERY_DIR}"

# shellcheck source=scripts/lib-review-verdict.sh
. "${SCRIPT_DIR}/lib-review-verdict.sh"

if [ "${SKIP_CONTEXT_GENERATION}" = "1" ]; then
  echo "[review] using existing review context and prompts..."
  CONTEXT_FILE="$(find "${CONTEXT_DIR}" -maxdepth 1 -type f \( -name 'review-context-*.md' -o -name 'latest-review-context.md' \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
  CONTEXT_FILE="${CONTEXT_FILE:-existing context in ${CONTEXT_DIR}}"
else
  echo "[review] collecting review context..."
  CONTEXT_FILE="$(OUT_DIR="${CONTEXT_DIR}" INCLUDE_UNTRACKED_CONTENT="${REVIEW_INCLUDE_UNTRACKED_CONTENT}" REVIEW_CONTEXT_DETAIL="${REVIEW_CONTEXT_DETAIL}" REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES="${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES}" REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES="${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES}" ./scripts/collect-review-context.sh)"

  echo "[review] generating review prompts..."
  OUT_DIR="${PROMPT_DIR}" REVIEW_CONTEXT_MAX_BYTES="${REVIEW_CONTEXT_MAX_BYTES}" ./scripts/make-review-prompts.sh "${CONTEXT_FILE}" >/dev/null
fi

CODEX_FALLBACK_CONTEXT_FILE="${CONTEXT_FILE}"
if [ -f "${PROMPT_DIR}/focused-review-context.md" ]; then
  CODEX_FALLBACK_CONTEXT_FILE="${PROMPT_DIR}/focused-review-context.md"
fi

CLAUDE_PROMPT="${PROMPT_DIR}/claude-review.md"
GEMINI_PROMPT="${PROMPT_DIR}/gemini-review.md"

if [ ! -f "${CLAUDE_PROMPT}" ] || [ ! -f "${GEMINI_PROMPT}" ]; then
  echo "[review] review prompts missing; regenerate context without SKIP_CONTEXT_GENERATION=1"
  exit 1
fi

TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
REVIEW_RUN_ID_RAW="${REVIEW_RUN_ID:-${TIMESTAMP}}"
REVIEW_RUN_ID="$(printf '%s' "${REVIEW_RUN_ID_RAW}" | sed 's/[^A-Za-z0-9_.-]/_/g')"
if [ -z "${REVIEW_RUN_ID}" ]; then
  REVIEW_RUN_ID="${TIMESTAMP}"
fi
CLAUDE_OUT="${OUT_DIR}/claude-review-${TIMESTAMP}.md"
GEMINI_OUT="${OUT_DIR}/gemini-review-${TIMESTAMP}.md"
CODEX_ARCHITECT_FALLBACK_OUT="${OUT_DIR}/codex-architect-fallback-${TIMESTAMP}.md"
CODEX_TEST_FALLBACK_OUT="${OUT_DIR}/codex-test-fallback-${TIMESTAMP}.md"
CODEX_FALLBACK_SUMMARY_OUT="${OUT_DIR}/codex-fallback-summary-${TIMESTAMP}.md"
SUMMARY_OUT="${OUT_DIR}/review-summary-${TIMESTAMP}.md"
MANIFEST_OUT="${OUT_DIR}/review-run-${REVIEW_RUN_ID}.md"
EXTERNAL_RUNNER="${EXTERNAL_REVIEW_DIR}/run-reviewers-${TIMESTAMP}.sh"
EXTERNAL_LATEST="${EXTERNAL_REVIEW_DIR}/run-reviewers-latest.sh"

reviewer_disabled_file() {
  echo "${REVIEW_STATE_DIR}/$1.disabled"
}

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

disabled_reason() {
  local reviewer="$1"
  local disabled_file
  disabled_file="$(reviewer_disabled_file "${reviewer}")"

  if [ ! -f "${disabled_file}" ]; then
    return 1
  fi

  local reason details disabled_at source_run_id next_action reset_hint
  reason="$(sed -n 's/^reason=//p' "${disabled_file}" 2>/dev/null | head -n 1)"
  details="$(sed -n 's/^details=//p' "${disabled_file}" 2>/dev/null | head -n 1)"
  disabled_at="$(sed -n 's/^disabled_at=//p' "${disabled_file}" 2>/dev/null | head -n 1)"
  source_run_id="$(sed -n 's/^source_run_id=//p' "${disabled_file}" 2>/dev/null | head -n 1)"
  next_action="$(sed -n 's/^next_action=//p' "${disabled_file}" 2>/dev/null | head -n 1)"
  reset_hint="$(sed -n 's/^reset_hint=//p' "${disabled_file}" 2>/dev/null | head -n 1)"

  echo "reason=${reason}; details=${details}; disabled_at=${disabled_at}; source_run_id=${source_run_id:-unknown}; next_action=${next_action:-user_reset_required}; reset_hint=${reset_hint:-RESET_DISABLED_AI_REVIEWERS=${reviewer} ./scripts/review-gate.sh}"
}

disabled_reviewers_summary() {
  local found=0
  local reviewer reason

  for reviewer in claude gemini; do
    if reason="$(disabled_reason "${reviewer}")"; then
      found=1
      echo "- ${reviewer}: ${reason}"
    fi
  done

  if [ "${found}" -eq 0 ]; then
    echo "- none"
  fi
}

write_run_manifest() {
  cat > "${MANIFEST_OUT}" <<MANIFEST
# AI Review Run Manifest

Generated at: $(date -Iseconds)

## Run

- Review run id: ${REVIEW_RUN_ID}
- Execution mode: ${REVIEW_EXECUTION_MODE}
- Context: ${CONTEXT_FILE}
- Claude prompt: ${CLAUDE_PROMPT}
- Gemini prompt: ${GEMINI_PROMPT}
- Model routing report: ${AI_MODEL_ROUTING_REPORT}
- Model routing cache status: ${AI_MODEL_ROUTING_CACHE_STATUS:-unknown}
- Model routing cache age seconds: ${AI_MODEL_ROUTING_CACHE_AGE_SECONDS:-unknown}
- Model routing cache TTL seconds: ${AI_MODEL_ROUTING_CACHE_TTL_SECONDS:-unknown}

## Outputs

- Claude result: ${CLAUDE_OUT}
- Gemini result: ${GEMINI_OUT}
- Codex architect fallback: ${CODEX_ARCHITECT_FALLBACK_OUT}
- Codex test fallback: ${CODEX_TEST_FALLBACK_OUT}
- Codex fallback summary: ${CODEX_FALLBACK_SUMMARY_OUT}
- Review summary: ${SUMMARY_OUT}
- External runner: ${EXTERNAL_RUNNER}
- Latest external runner: ${EXTERNAL_LATEST}

## Disabled Reviewers At Manifest Time

$(disabled_reviewers_summary)
MANIFEST
}

reset_disabled_reviewers

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
: "\${CLAUDE_PROMPT_ARG_MAX_BYTES:=${CLAUDE_PROMPT_ARG_MAX_BYTES}}"
: "\${GEMINI_PROMPT_ARG_MAX_BYTES:=${GEMINI_PROMPT_ARG_MAX_BYTES}}"
: "\${GEMINI_PROMPT_MAX_BYTES:=${GEMINI_PROMPT_MAX_BYTES}}"
: "\${REVIEW_CONTEXT_MAX_BYTES:=${REVIEW_CONTEXT_MAX_BYTES}}"
: "\${REVIEW_CONTEXT_DETAIL:=${REVIEW_CONTEXT_DETAIL}}"
: "\${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES:=${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES}}"
: "\${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES:=${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES}}"
: "\${REVIEW_RETRY_LIMIT:=${REVIEW_RETRY_LIMIT}}"
: "\${REVIEW_OUTPUT_MODE:=tee}"
: "\${SKIP_CONTEXT_GENERATION:=1}"
: "\${REVIEW_INCLUDE_UNTRACKED_CONTENT:=${REVIEW_INCLUDE_UNTRACKED_CONTENT}}"
: "\${AI_MODEL_DISCOVERY:=${AI_MODEL_DISCOVERY}}"
: "\${AI_MODEL_DISCOVERY_DIR:=${AI_MODEL_DISCOVERY_DIR}}"
: "\${AI_MODEL_ROUTING_ENV:=${AI_MODEL_ROUTING_ENV}}"
: "\${AI_MODEL_ROUTING_REPORT:=${AI_MODEL_ROUTING_REPORT}}"
: "\${AI_MODEL_ROUTING_OBSERVATIONS:=}"
: "\${AI_MODEL_DISCOVERY_REFRESH:=${AI_MODEL_DISCOVERY_REFRESH:-0}}"
: "\${AI_MODEL_ROUTING_TTL_SECONDS:=${AI_MODEL_ROUTING_TTL_SECONDS:-43200}}"
: "\${CLAUDE_REVIEW_MODEL_AUTO:=${CLAUDE_REVIEW_MODEL_AUTO:-0}}"
: "\${REVIEW_RUN_ID:=${REVIEW_RUN_ID}}"

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
CLAUDE_PROMPT_ARG_MAX_BYTES="\${CLAUDE_PROMPT_ARG_MAX_BYTES}" \\
GEMINI_PROMPT_ARG_MAX_BYTES="\${GEMINI_PROMPT_ARG_MAX_BYTES}" \\
GEMINI_PROMPT_MAX_BYTES="\${GEMINI_PROMPT_MAX_BYTES}" \\
REVIEW_CONTEXT_MAX_BYTES="\${REVIEW_CONTEXT_MAX_BYTES}" \\
REVIEW_CONTEXT_DETAIL="\${REVIEW_CONTEXT_DETAIL}" \\
REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES="\${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES}" \\
REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES="\${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES}" \\
REVIEW_RETRY_LIMIT="\${REVIEW_RETRY_LIMIT}" \\
REVIEW_OUTPUT_MODE="\${REVIEW_OUTPUT_MODE}" \\
SKIP_CONTEXT_GENERATION="\${SKIP_CONTEXT_GENERATION}" \\
REVIEW_INCLUDE_UNTRACKED_CONTENT="\${REVIEW_INCLUDE_UNTRACKED_CONTENT}" \\
AI_MODEL_DISCOVERY="\${AI_MODEL_DISCOVERY}" \\
AI_MODEL_DISCOVERY_DIR="\${AI_MODEL_DISCOVERY_DIR}" \\
AI_MODEL_ROUTING_ENV="\${AI_MODEL_ROUTING_ENV}" \\
AI_MODEL_ROUTING_REPORT="\${AI_MODEL_ROUTING_REPORT}" \\
AI_MODEL_ROUTING_OBSERVATIONS="\${AI_MODEL_ROUTING_OBSERVATIONS}" \\
AI_MODEL_DISCOVERY_REFRESH="\${AI_MODEL_DISCOVERY_REFRESH}" \\
AI_MODEL_ROUTING_TTL_SECONDS="\${AI_MODEL_ROUTING_TTL_SECONDS}" \\
CLAUDE_REVIEW_MODEL_AUTO="\${CLAUDE_REVIEW_MODEL_AUTO}" \\
REVIEW_RUN_ID="\${REVIEW_RUN_ID}" \\
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

Disabled reviewer state is shared with the generated external runner. If a reviewer is listed below, the external runner will also skip it until reset.

$(disabled_reviewers_summary)
SUMMARY

  write_run_manifest
  echo "[review] external reviewer runner: ${EXTERNAL_RUNNER}"
  echo "[review] latest external reviewer runner: ${EXTERNAL_LATEST}"
  echo "[review] run manifest: ${MANIFEST_OUT}"
  echo "[review] summary: ${SUMMARY_OUT}"
  echo "[review] disabled reviewers for external runner:"
  disabled_reviewers_summary
  echo "[review] external review pending"
  exit 2
fi

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
    if [ -n "${AI_MODEL_ROUTING_DISCOVERED_EPOCH:-}" ] && printf '%s\n' "${AI_MODEL_ROUTING_DISCOVERED_EPOCH}" | grep -Eq '^[0-9]+$'; then
      routing_age=$(( $(date +%s) - AI_MODEL_ROUTING_DISCOVERED_EPOCH ))
      if [ "${routing_age}" -ge 0 ]; then
        echo "[review] model routing cache: ${AI_MODEL_ROUTING_CACHE_STATUS:-unknown}, age=${routing_age}s, ttl=${AI_MODEL_ROUTING_CACHE_TTL_SECONDS:-unknown}s"
      fi
    fi
    echo "[review] selected models: claude(${CLAUDE_REVIEW_ROLE:-review})=${CLAUDE_REVIEW_MODEL:-provider-default} gemini(${GEMINI_REVIEW_ROLE:-review})=${GEMINI_REVIEW_MODEL:-provider-default} codex_architect(${CODEX_ARCHITECT_REVIEW_ROLE:-fallback})=${CODEX_ARCHITECT_REVIEW_MODEL:-provider-default} codex_test(${CODEX_TEST_REVIEW_ROLE:-fallback})=${CODEX_TEST_REVIEW_MODEL:-provider-default}"
  else
    echo "[review] AI model discovery failed; using provider defaults"
  fi
}

help_supports_flag() {
  local help_text="$1"
  local flag="$2"

  printf '%s\n' "${help_text}" | grep -Eq "(^|[^[:alnum:]_-])${flag}($|[^[:alnum:]_-])"
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
    echo "source_run_id=${REVIEW_RUN_ID}"
    echo "next_action=user_reset_required"
    echo "reset_hint=RESET_DISABLED_AI_REVIEWERS=${reviewer} ./scripts/review-gate.sh"
  } > "${disabled_file}"

  echo "[review] ${reviewer} review disabled until user re-enables it: ${reason} (${details})"
}

failure_details() {
  local output_file="$1"
  local status="$2"
  local class="unknown"
  local tail_text

  if grep -qiE 'heap out of memory|JavaScript heap|allocation failed|out of memory|ENOMEM' "${output_file}" 2>/dev/null; then
    class="oom"
  elif grep -qiE 'trust folder|trusted folder|trust.*workspace|workspace.*trust|skip-trust' "${output_file}" 2>/dev/null; then
    class="trust_required"
  elif grep -qiE 'ECONNREFUSED|ConnectionRefused|connection refused|network.*blocked|sandbox|read-only file system|EROFS' "${output_file}" 2>/dev/null; then
    class="network_or_sandbox"
  elif grep -qiE 'timed out|timeout|SIGTERM|Killed' "${output_file}" 2>/dev/null; then
    class="timeout_or_killed"
  elif grep -qiE 'auth|login|credential|permission denied|unauthorized|forbidden' "${output_file}" 2>/dev/null; then
    class="auth_or_permission"
  elif is_limit_failure "${output_file}"; then
    class="usage_limit"
  elif [ "${status}" -eq 0 ]; then
    class="no_usable_verdict"
  else
    class="command_failed"
  fi

  tail_text="$(tail -20 "${output_file}" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g' | cut -c1-500)"
  printf 'class=%s; exit_status=%s; tail=%s' "${class}" "${status}" "${tail_text:-none}"
  if [ -n "${REVIEWER_PREFLIGHT_DETAILS:-}" ]; then
    printf '; preflight=%s' "${REVIEWER_PREFLIGHT_DETAILS}"
  fi
}

preflight_details() {
  local reviewer="$1"
  local help_text="$2"
  local prompt_file="$3"
  local prompt_bytes
  prompt_bytes="$(wc -c < "${prompt_file}")"

  case "${reviewer}" in
    gemini)
      printf 'prompt_bytes=%s' "${prompt_bytes}"
      if printf '%s\n' "${help_text}" | grep -q -- '--prompt'; then
        printf ',prompt_flag=yes'
      else
        printf ',prompt_flag=no'
      fi
      if printf '%s\n' "${help_text}" | grep -q -- '--skip-trust'; then
        printf ',skip_trust=yes'
      else
        printf ',skip_trust=no'
      fi
      if [ -n "${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}" ]; then
        printf ',api_env=present'
      else
        printf ',api_env=missing'
      fi
      ;;
    claude)
      printf 'prompt_bytes=%s' "${prompt_bytes}"
      if printf '%s\n' "${help_text}" | grep -q -- '--print'; then
        printf ',print_flag=yes'
      else
        printf ',print_flag=no'
      fi
      if printf '%s\n' "${help_text}" | grep -q -- '--permission-mode'; then
        printf ',permission_mode=yes'
      else
        printf ',permission_mode=no'
      fi
      ;;
  esac
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
      disable_reviewer "${reviewer}" "usage_limit" "$(failure_details "${output_file}" "${status}")"
      return "${status}"
    fi

    if [ "${status}" -eq 0 ]; then
      status=1
      echo "[review] ${reviewer} produced no usable ## Verdict section"
    fi

    echo "[review] ${reviewer} attempt ${attempt}/${REVIEW_RETRY_LIMIT} failed with status ${status}"
    attempt=$((attempt + 1))
  done

  disable_reviewer "${reviewer}" "retry_exhausted" "$(failure_details "${output_file}" "${status}")"
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
  REVIEWER_PREFLIGHT_DETAILS="$(preflight_details claude "${claude_help}" "${CLAUDE_PROMPT}")"
  if printf '%s\n' "${claude_help}" | grep -q -- '--print'; then
    claude_args=(--print)
    claude_prompt_bytes="$(wc -c < "${CLAUDE_PROMPT}")"

    if printf '%s\n' "${claude_help}" | grep -q -- '--no-session-persistence'; then
      claude_args+=(--no-session-persistence)
    fi

    if printf '%s\n' "${claude_help}" | grep -q -- '--permission-mode'; then
      claude_args+=(--permission-mode plan)
    fi

    if [ -n "${CLAUDE_REVIEW_MODEL:-}" ] && help_supports_flag "${claude_help}" "--model"; then
      claude_args+=(--model "${CLAUDE_REVIEW_MODEL}")
    fi

    if [ "${claude_prompt_bytes}" -gt "${CLAUDE_PROMPT_ARG_MAX_BYTES}" ]; then
      run_with_retries "claude" "${CLAUDE_OUT}" run_review_command_stdin "${CLAUDE_OUT}" "${CLAUDE_PROMPT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${CLAUDE_REVIEW_TIMEOUT_SECONDS}" claude "${claude_args[@]}"
    else
      run_with_retries "claude" "${CLAUDE_OUT}" run_review_command "${CLAUDE_OUT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${CLAUDE_REVIEW_TIMEOUT_SECONDS}" claude "${claude_args[@]}" "$(cat "${CLAUDE_PROMPT}")"
    fi
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
  gemini_prompt_file="${GEMINI_PROMPT}"
  gemini_prompt_bytes="$(wc -c < "${GEMINI_PROMPT}")"
  REVIEWER_PREFLIGHT_DETAILS="$(preflight_details gemini "${gemini_help}" "${GEMINI_PROMPT}")"
  if [ "${gemini_prompt_bytes}" -gt "${GEMINI_PROMPT_MAX_BYTES}" ]; then
    gemini_prompt_file="${PROMPT_DIR}/gemini-review-capped-${TIMESTAMP}.md"
    {
      echo "# Gemini Review Prompt"
      echo
      echo "The original Gemini prompt was ${gemini_prompt_bytes} bytes and exceeded GEMINI_PROMPT_MAX_BYTES=${GEMINI_PROMPT_MAX_BYTES}."
      echo "The review context below is truncated to avoid Gemini CLI Node/V8 heap exhaustion."
      echo "If the truncated context is insufficient, return request_changes with the missing context noted."
      echo
      python3 - "${GEMINI_PROMPT}" "${GEMINI_PROMPT_MAX_BYTES}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
limit = int(sys.argv[2])
sys.stdout.write(path.read_bytes()[:limit].decode("utf-8", errors="ignore"))
PY
      echo
      echo
      echo "## Truncation Notice"
      echo
      echo "Gemini prompt truncated by run-ai-reviews.sh. Required output remains: ## Verdict with approve, approve_with_notes, or request_changes."
    } > "${gemini_prompt_file}"
    echo "[review] Gemini prompt capped: ${gemini_prompt_file}"
  fi
  if printf '%s\n' "${gemini_help}" | grep -q -- '--prompt'; then
    gemini_prompt_bytes="$(wc -c < "${gemini_prompt_file}")"

    if [ "${gemini_prompt_bytes}" -gt "${GEMINI_PROMPT_ARG_MAX_BYTES}" ]; then
      gemini_args=(--prompt "Review the Markdown prompt provided on stdin.")
      gemini_stdin_mode=1
    else
      gemini_args=(--prompt "$(cat "${gemini_prompt_file}")")
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
      run_with_retries "gemini" "${GEMINI_OUT}" run_review_command_stdin "${GEMINI_OUT}" "${gemini_prompt_file}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini "${gemini_args[@]}"
    else
      run_with_retries "gemini" "${GEMINI_OUT}" run_review_command "${GEMINI_OUT}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini "${gemini_args[@]}"
    fi
  else
    run_with_retries "gemini" "${GEMINI_OUT}" run_review_command_stdin "${GEMINI_OUT}" "${gemini_prompt_file}" timeout -k "${REVIEW_TIMEOUT_KILL_AFTER_SECONDS}" "${GEMINI_REVIEW_TIMEOUT_SECONDS}" gemini
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

You are running in the repository root with read-only filesystem access. The
embedded review context may be bounded or truncated for prompt-size safety.
When it is insufficient, inspect the referenced files directly with read-only
commands such as rg, sed, git diff, git diff --cached, git status, and git show.
Do not request changes solely because the embedded context is truncated if the
missing evidence is available from the repository.

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

  if [ -f "${CODEX_FALLBACK_CONTEXT_FILE}" ]; then
    cat "${CODEX_FALLBACK_CONTEXT_FILE}" >> "${prompt_file}"
  else
    cat >> "${prompt_file}" <<MSG
Review context file is unavailable: ${CODEX_FALLBACK_CONTEXT_FILE}
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

write_run_manifest
echo "[review] run manifest: ${MANIFEST_OUT}"
echo "[review] summary: ${SUMMARY_OUT}"
echo "[review] done"
