#!/usr/bin/env bash
set -euo pipefail

RESULT_DIR="${RESULT_DIR:-.omx/review-results}"
OUT_DIR="${OUT_DIR:-.omx/review-results}"

mkdir -p "${OUT_DIR}"

latest_file() {
  local pattern="$1"
  find "${RESULT_DIR}" -maxdepth 1 -type f -name "${pattern}" -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | head -1 \
    | cut -d' ' -f2-
}

manifest_file() {
  local label="$1"
  local fallback_pattern="$2"
  local value=""

  if [ -n "${REVIEW_RUN_SUMMARY_FILE:-}" ] && [ -f "${REVIEW_RUN_SUMMARY_FILE}" ]; then
    value="$(sed -n "s/^- ${label}: //p" "${REVIEW_RUN_SUMMARY_FILE}" | tail -1)"
  fi

  if [ -n "${value}" ]; then
    echo "${value}"
    return 0
  fi

  latest_file "${fallback_pattern}"
}

is_failure_result() {
  local file="$1"

  awk '
    /^```/ {
      in_code = !in_code
      next
    }
    in_code {
      next
    }
    /^[A-Za-z -]+ review failed or timed out\.$/ {
      marker_line = NR
      next
    }
    marker_line && NR <= marker_line + 4 && /^Exit status: [0-9]+$/ {
      has_exit_status = 1
      next
    }
    marker_line && NR <= marker_line + 5 && /^Timeout seconds: [0-9]+$/ {
      has_timeout = 1
      next
    }
    END {
      exit !(marker_line && has_exit_status && has_timeout)
    }
  ' "${file}"
}

extract_verdict() {
  local file="$1"

  if [ -z "${file}" ] || [ ! -f "${file}" ]; then
    echo "missing"
    return 0
  fi

  if is_failure_result "${file}"; then
    echo "failed"
    return 0
  fi

  local verdict
  verdict="$(
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
          print verdict
          exit
        }
      }
    ' "${file}"
  )"

  if [ -n "${verdict}" ]; then
    echo "${verdict}"
    return 0
  fi

  if grep -qi '^Skipped:' "${file}"; then
    echo "skipped"
    return 0
  fi

  echo "unknown"
}

final_decision() {
  local claude="$1"
  local gemini="$2"
  local codex_architect="$3"
  local codex_test="$4"
  local external_usable_count=0
  local codex_usable_count=0

  if is_usable_review "${claude}"; then
    external_usable_count=$((external_usable_count + 1))
  fi

  if is_usable_review "${gemini}"; then
    external_usable_count=$((external_usable_count + 1))
  fi

  if is_usable_review "${codex_architect}"; then
    codex_usable_count=$((codex_usable_count + 1))
  fi

  if is_usable_review "${codex_test}"; then
    codex_usable_count=$((codex_usable_count + 1))
  fi

  # Approval/request_changes disagreement means a human should inspect the reviews.
  if is_approval "${claude}" && [ "${gemini}" = "request_changes" ]; then
    echo "review_manually"
    return 0
  fi

  if is_approval "${gemini}" && [ "${claude}" = "request_changes" ]; then
    echo "review_manually"
    return 0
  fi

  if { is_approval "${claude}" || is_approval "${gemini}"; } && \
     { [ "${codex_architect}" = "request_changes" ] || [ "${codex_test}" = "request_changes" ]; }; then
    echo "review_manually"
    return 0
  fi

  if [ "${claude}" = "request_changes" ] || [ "${gemini}" = "request_changes" ]; then
    echo "revise"
    return 0
  fi

  if [ "${codex_architect}" = "request_changes" ] || [ "${codex_test}" = "request_changes" ]; then
    echo "revise"
    return 0
  fi

  if [ "${claude}" = "failed" ] && [ "${gemini}" = "failed" ]; then
    if [ "${codex_usable_count}" -ge 2 ] && is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "proceed_degraded"
      return 0
    fi

    echo "blocked"
    return 0
  fi

  if [ "${claude}" = "missing" ] && [ "${gemini}" = "missing" ]; then
    if [ "${codex_usable_count}" -ge 2 ] && is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "proceed_degraded"
      return 0
    fi

    echo "blocked"
    return 0
  fi

  if [ "${external_usable_count}" -eq 0 ]; then
    if [ "${codex_usable_count}" -ge 2 ] && is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "proceed_degraded"
      return 0
    fi

    echo "blocked"
    return 0
  fi

  if is_approval "${claude}" && is_approval "${gemini}"; then
    echo "proceed"
    return 0
  fi

  if is_approval "${claude}" || is_approval "${gemini}"; then
    if [ "${codex_usable_count}" -eq 0 ]; then
      echo "review_manually"
      return 0
    fi

    echo "proceed_degraded"
    return 0
  fi

  echo "review_manually"
}

is_approval() {
  [ "$1" = "approve" ] || [ "$1" = "approve_with_notes" ]
}

review_coverage() {
  local claude="$1"
  local gemini="$2"
  local codex_architect="$3"
  local codex_test="$4"
  local external_usable_count=0
  local codex_usable_count=0

  if is_usable_review "${claude}"; then
    external_usable_count=$((external_usable_count + 1))
  fi

  if is_usable_review "${gemini}"; then
    external_usable_count=$((external_usable_count + 1))
  fi

  if is_usable_review "${codex_architect}"; then
    codex_usable_count=$((codex_usable_count + 1))
  fi

  if is_usable_review "${codex_test}"; then
    codex_usable_count=$((codex_usable_count + 1))
  fi

  if [ "${external_usable_count}" -eq 2 ]; then
    echo "multi_reviewer"
    return 0
  fi

  if [ "${external_usable_count}" -eq 1 ] && [ "${codex_usable_count}" -gt 0 ]; then
    echo "single_external_plus_codex_fallback"
    return 0
  fi

  if [ "${external_usable_count}" -eq 1 ]; then
    echo "single_reviewer"
    return 0
  fi

  if [ "${codex_usable_count}" -ge 2 ]; then
    echo "codex_only_degraded"
    return 0
  fi

  if [ "${codex_usable_count}" -eq 1 ]; then
    echo "partial_codex_fallback_only"
    return 0
  fi

  echo "no_usable_review"
}

is_usable_review() {
  is_approval "$1" || [ "$1" = "request_changes" ]
}

decision_reason() {
  local claude="$1"
  local gemini="$2"
  local codex_architect="$3"
  local codex_test="$4"

  if { is_approval "${claude}" && [ "${gemini}" = "request_changes" ]; } || \
     { is_approval "${gemini}" && [ "${claude}" = "request_changes" ]; }; then
    echo "reviewer_disagreement"
    return 0
  fi

  if { is_approval "${claude}" || is_approval "${gemini}"; } && \
     { [ "${codex_architect}" = "request_changes" ] || [ "${codex_test}" = "request_changes" ]; }; then
    echo "codex_fallback_requested_changes"
    return 0
  fi

  if [ "${claude}" = "request_changes" ] || [ "${gemini}" = "request_changes" ]; then
    echo "reviewer_requested_changes"
    return 0
  fi

  if [ "${codex_architect}" = "request_changes" ] || [ "${codex_test}" = "request_changes" ]; then
    echo "codex_fallback_requested_changes"
    return 0
  fi

  if [ "${claude}" = "failed" ] && [ "${gemini}" = "failed" ]; then
    if is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "codex_only_degraded_approval"
      return 0
    fi

    echo "all_reviewers_failed"
    return 0
  fi

  if [ "${claude}" = "missing" ] && [ "${gemini}" = "missing" ]; then
    if is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "codex_only_degraded_approval"
      return 0
    fi

    echo "all_reviewers_missing"
    return 0
  fi

  if ! is_usable_review "${claude}" && ! is_usable_review "${gemini}"; then
    if is_approval "${codex_architect}" && is_approval "${codex_test}"; then
      echo "codex_only_degraded_approval"
      return 0
    fi

    echo "no_usable_review"
    return 0
  fi

  if is_approval "${claude}" && is_approval "${gemini}"; then
    echo "multi_reviewer_approval"
    return 0
  fi

  if is_approval "${claude}" || is_approval "${gemini}"; then
    if is_approval "${codex_architect}" || is_approval "${codex_test}"; then
      echo "single_external_plus_codex_fallback_approval"
      return 0
    fi

    echo "single_reviewer_without_codex_fallback"
    return 0
  fi

  echo "unclassified_review_output"
}

missing_reviewers() {
  local claude="$1"
  local gemini="$2"
  local missing=()

  case "${claude}" in
    skipped|missing|failed|unknown) missing+=("claude:${claude}") ;;
  esac

  case "${gemini}" in
    skipped|missing|failed|unknown) missing+=("gemini:${gemini}") ;;
  esac

  if [ "${#missing[@]}" -eq 0 ]; then
    echo "none"
  else
    local joined="${missing[0]}"
    local item
    for item in "${missing[@]:1}"; do
      joined="${joined}, ${item}"
    done
    echo "${joined}"
  fi
}

REVIEW_RUN_SUMMARY_FILE="$(latest_file 'review-summary-*.md')"
CLAUDE_FILE="$(manifest_file 'Claude result' 'claude-review-*.md')"
GEMINI_FILE="$(manifest_file 'Gemini result' 'gemini-review-*.md')"
CODEX_ARCHITECT_FALLBACK_FILE="$(manifest_file 'Codex architect fallback' 'codex-architect-fallback-*.md')"
CODEX_TEST_FALLBACK_FILE="$(manifest_file 'Codex test fallback' 'codex-test-fallback-*.md')"
CODEX_FALLBACK_SUMMARY_FILE="$(manifest_file 'Codex fallback summary' 'codex-fallback-summary-*.md')"
CODEX_FALLBACK_REQUIRED=0
if [ -n "${CODEX_FALLBACK_SUMMARY_FILE}" ] && [ -f "${CODEX_FALLBACK_SUMMARY_FILE}" ] && grep -q '^informational_only$' "${CODEX_FALLBACK_SUMMARY_FILE}"; then
  CODEX_FALLBACK_REQUIRED=1
fi

CLAUDE_VERDICT="$(extract_verdict "${CLAUDE_FILE}")"
GEMINI_VERDICT="$(extract_verdict "${GEMINI_FILE}")"
CODEX_ARCHITECT_VERDICT="missing"
CODEX_TEST_VERDICT="missing"
if [ "${CODEX_FALLBACK_REQUIRED}" -eq 1 ]; then
  CODEX_ARCHITECT_VERDICT="$(extract_verdict "${CODEX_ARCHITECT_FALLBACK_FILE}")"
  CODEX_TEST_VERDICT="$(extract_verdict "${CODEX_TEST_FALLBACK_FILE}")"
fi
FINAL_DECISION="$(final_decision "${CLAUDE_VERDICT}" "${GEMINI_VERDICT}" "${CODEX_ARCHITECT_VERDICT}" "${CODEX_TEST_VERDICT}")"
REVIEW_COVERAGE="$(review_coverage "${CLAUDE_VERDICT}" "${GEMINI_VERDICT}" "${CODEX_ARCHITECT_VERDICT}" "${CODEX_TEST_VERDICT}")"
DECISION_REASON="$(decision_reason "${CLAUDE_VERDICT}" "${GEMINI_VERDICT}" "${CODEX_ARCHITECT_VERDICT}" "${CODEX_TEST_VERDICT}")"
MISSING_REVIEWERS="$(missing_reviewers "${CLAUDE_VERDICT}" "${GEMINI_VERDICT}")"
CODEX_FALLBACK_COVERAGE="none"
if is_usable_review "${CODEX_ARCHITECT_VERDICT}" || is_usable_review "${CODEX_TEST_VERDICT}"; then
  CODEX_FALLBACK_COVERAGE="available_degraded_informational_only"
elif [ "${CODEX_FALLBACK_REQUIRED}" -eq 1 ]; then
  CODEX_FALLBACK_COVERAGE="required_but_unusable"
fi

TRUST_LEVEL="degraded"
if [ "${REVIEW_COVERAGE}" = "multi_reviewer" ] && [ "${FINAL_DECISION}" = "proceed" ]; then
  TRUST_LEVEL="normal"
elif [ "${FINAL_DECISION}" = "blocked" ] || [ "${FINAL_DECISION}" = "revise" ] || [ "${FINAL_DECISION}" = "review_manually" ]; then
  TRUST_LEVEL="blocked_or_needs_attention"
fi

TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
SUMMARY_FILE="${OUT_DIR}/review-verdict-${TIMESTAMP}.md"

cat > "${SUMMARY_FILE}" <<SUMMARY
# AI Review Verdict

Generated at: $(date -Iseconds)

## Final Decision

${FINAL_DECISION}

## Decision Reason

${DECISION_REASON}

## Review Coverage

${REVIEW_COVERAGE}

## Trust Level

${TRUST_LEVEL}

## Missing Or Unusable Reviewers

${MISSING_REVIEWERS}

## Codex Fallback Coverage

${CODEX_FALLBACK_COVERAGE}

Codex fallback coverage is degraded and informational-only. It is not independent Claude or Gemini reviewer approval.

## Reviewer Verdicts

| Reviewer | Verdict | File |
|---|---|---|
| Claude | ${CLAUDE_VERDICT} | ${CLAUDE_FILE:-missing} |
| Gemini | ${GEMINI_VERDICT} | ${GEMINI_FILE:-missing} |

## Codex Fallback Reviews

| Fallback Reviewer | Verdict | File |
|---|---|---|
| codex-architect-review | ${CODEX_ARCHITECT_VERDICT} | ${CODEX_ARCHITECT_FALLBACK_FILE:-missing} |
| codex-test-alternative-review | ${CODEX_TEST_VERDICT} | ${CODEX_TEST_FALLBACK_FILE:-missing} |
| summary | ${CODEX_FALLBACK_COVERAGE} | ${CODEX_FALLBACK_SUMMARY_FILE:-missing} |

## Interpretation

- proceed: review is sufficient to continue toward user approval or commit.
- proceed_degraded: review may continue with explicit degraded trust; at least one external reviewer is missing or only Codex fallback coverage is available.
- revise: at least one reviewer requested changes.
- blocked: no usable review result is available.
- review_manually: review output exists, but the verdict could not be confidently parsed, reviewers disagreed, Codex fallback requested changes alongside external approval, or only one external reviewer approved without usable fallback coverage.
- single_reviewer: only one external reviewer produced a usable verdict; inspect missing reviewer status before relying on multi-agent coverage.
- single_external_plus_codex_fallback: one external reviewer approved and at least one Codex fallback reviewer ran; this is degraded coverage.
- codex_only_degraded: no external reviewer produced a usable verdict; two Codex fallback reviewers ran, but this is not independent external review.
- multi_reviewer: both reviewers produced usable verdicts.

## Next Step

If the final decision is proceed or proceed_degraded, inspect the review files and continue with normal verification/commit approval. For proceed_degraded, report the degraded trust level to the user.

If the final decision is revise, inspect reviewer findings and apply only accepted feedback.

If the final decision is blocked or review_manually, inspect the raw review files before continuing.
SUMMARY

echo "${SUMMARY_FILE}"
echo
cat "${SUMMARY_FILE}"

if [ "${FINAL_DECISION}" != "proceed" ] && [ "${FINAL_DECISION}" != "proceed_degraded" ]; then
  exit 1
fi
