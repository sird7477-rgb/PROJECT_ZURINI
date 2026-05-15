#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
SUMMARY_SCRIPT="${REPO_ROOT}/scripts/summarize-ai-reviews.sh"
TMP_ROOT="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_ROOT}"
}

trap cleanup EXIT

write_verdict() {
  local file="$1"
  local verdict="$2"

  printf '# Review\n\n## Verdict\n\n%s\n' "${verdict}" > "${file}"
}

write_skipped() {
  local file="$1"

  printf '# Review\n\nSkipped: disabled for fixture\n' > "${file}"
}

write_failed_with_prompt_verdict() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Reviewer Prompt Echo

## Verdict

approve_with_notes

---

Gemini review failed or timed out.
Exit status: 124
Timeout seconds: 180
RESOURCE_EXHAUSTED
MSG
}

write_failed_with_skipped_prompt() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Reviewer Prompt Echo

Skipped: this text was echoed from prompt context and is not the runner status.

---

Gemini review failed or timed out.
Exit status: 124
Timeout seconds: 180
MSG
}

write_valid_with_failure_words() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

approve_with_notes

## Findings

The reviewed change discusses command not found, Too Many Requests, Operation cancelled, and RESOURCE_EXHAUSTED as handled error text.
MSG
}

write_valid_with_fenced_failure_footer() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

approve_with_notes

## Findings

The reviewer quotes a runner footer without failing:

```text
Gemini review failed or timed out.
Exit status: 124
Timeout seconds: 180
```
MSG
}

write_valid_request_changes_with_skipped_word() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

request_changes

## Findings

The review context mentions Skipped: output from disabled reviewers, but this review itself requested changes.
MSG
}

write_prompt_echo_only() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes

## Findings

The reviewer echoed the prompt choices but did not provide a verdict.
MSG
}

write_prompt_echo_then_valid_verdict() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes

approve_with_notes

## Findings

The first list is prompt echo; the bare verdict is the actual answer.
MSG
}

write_single_bullet_verdict() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

- approve_with_notes

## Findings

No blocking findings.
MSG
}

write_single_bullet_echo_then_valid_verdict() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

## Verdict

- approve_with_notes

request_changes

## Findings

The first line is echoed prompt context; the bare verdict is the actual answer.
MSG
}

write_fenced_prompt_echo_only() {
  local file="$1"

  cat > "${file}" <<'MSG'
# Review

```markdown
## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes
```

## Findings

The verdict heading appeared only inside a fenced prompt echo.
MSG
}

write_fallback_summary() {
  local file="$1"
  local status="$2"

  printf '# Codex Fallback Review\n\n## Status\n\n%s\n' "${status}" > "${file}"
}

write_run_summary() {
  local dir="$1"
  local claude="$2"
  local gemini="$3"
  local architect="$4"
  local test_fallback="$5"
  local fallback_summary="$6"

  cat > "${dir}/review-summary-current.md" <<MSG
# AI Review Summary

## Outputs

- Claude result: ${claude}
- Gemini result: ${gemini}
- Codex architect fallback: ${architect}
- Codex test fallback: ${test_fallback}
- Codex fallback summary: ${fallback_summary}
MSG
}

summary_value() {
  local file="$1"
  local heading="$2"

  awk -v heading="## ${heading}" '
    $0 == heading {
      getline
      while ($0 == "") {
        getline
      }
      print
      exit
    }
  ' "${file}"
}

assert_summary() {
  local name="$1"
  local expected_decision="$2"
  local expected_coverage="$3"
  local expected_status="$4"
  local expected_missing="${5:-}"
  local dir="${TMP_ROOT}/${name}"
  local out_dir="${dir}/out"
  local status=0

  mkdir -p "${out_dir}"

  set +e
  RESULT_DIR="${dir}" OUT_DIR="${out_dir}" "${SUMMARY_SCRIPT}" >/tmp/review-summary-test-output.txt 2>&1
  status=$?
  set -e

  local summary_file
  summary_file="$(find "${out_dir}" -maxdepth 1 -type f -name 'review-verdict-*.md' -print | head -1)"

  if [ -z "${summary_file}" ]; then
    echo "[summary-test] ${name}: summary file was not created"
    cat /tmp/review-summary-test-output.txt
    exit 1
  fi

  local decision coverage missing
  decision="$(summary_value "${summary_file}" "Final Decision")"
  coverage="$(summary_value "${summary_file}" "Review Coverage")"
  missing="$(summary_value "${summary_file}" "Missing Or Unusable Reviewers")"

  if [ "${decision}" != "${expected_decision}" ]; then
    echo "[summary-test] ${name}: expected decision ${expected_decision}, got ${decision}"
    cat "${summary_file}"
    exit 1
  fi

  if [ "${coverage}" != "${expected_coverage}" ]; then
    echo "[summary-test] ${name}: expected coverage ${expected_coverage}, got ${coverage}"
    cat "${summary_file}"
    exit 1
  fi

  if [ "${status}" -ne "${expected_status}" ]; then
    echo "[summary-test] ${name}: expected exit ${expected_status}, got ${status}"
    cat "${summary_file}"
    exit 1
  fi

  if [ -n "${expected_missing}" ] && [ "${missing}" != "${expected_missing}" ]; then
    echo "[summary-test] ${name}: expected missing reviewers ${expected_missing}, got ${missing}"
    cat "${summary_file}"
    exit 1
  fi

  echo "[summary-test] ${name}: pass"
}

case_multi_reviewer() {
  local dir="${TMP_ROOT}/multi_reviewer"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_verdict "${dir}/gemini-review-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "multi_reviewer" "proceed" "multi_reviewer" 0
}

case_single_external_plus_codex() {
  local dir="${TMP_ROOT}/single_external_plus_codex"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_verdict "${dir}/gemini-review-current.md" "approve"
  write_verdict "${dir}/codex-architect-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "single_external_plus_codex" "proceed_degraded" "single_external_plus_codex_fallback" 0
}

case_codex_only_degraded() {
  local dir="${TMP_ROOT}/codex_only_degraded"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_skipped "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-architect-current.md" "approve"
  write_verdict "${dir}/codex-test-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/codex-test-current.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "codex_only_degraded" "proceed_degraded" "codex_only_degraded" 0
}

case_missing_fallback_blocks() {
  local dir="${TMP_ROOT}/missing_fallback_blocks"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_verdict "${dir}/gemini-review-current.md" "approve"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "missing_fallback_blocks" "review_manually" "single_reviewer" 1
}

case_request_changes_blocks() {
  local dir="${TMP_ROOT}/request_changes_blocks"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_verdict "${dir}/gemini-review-current.md" "approve"
  write_verdict "${dir}/codex-architect-current.md" "request_changes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "request_changes_blocks" "review_manually" "single_external_plus_codex_fallback" 1
}

case_stale_fallback_ignored() {
  local dir="${TMP_ROOT}/stale_fallback_ignored"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_verdict "${dir}/gemini-review-current.md" "approve"
  write_verdict "${dir}/codex-architect-fallback-stale.md" "request_changes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "stale_fallback_ignored" "proceed" "multi_reviewer" 0
}

case_failed_reviewer_prompt_text_ignored() {
  local dir="${TMP_ROOT}/failed_reviewer_prompt_text_ignored"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_failed_with_prompt_verdict "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-test-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/codex-test-current.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "failed_reviewer_prompt_text_ignored" "proceed_degraded" "single_external_plus_codex_fallback" 0
}

case_failed_reviewer_skipped_text_ignored() {
  local dir="${TMP_ROOT}/failed_reviewer_skipped_text_ignored"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_failed_with_skipped_prompt "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-test-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/codex-test-current.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "failed_reviewer_skipped_text_ignored" "proceed_degraded" "single_external_plus_codex_fallback" 0 "gemini:failed"
}

case_valid_review_with_failure_words() {
  local dir="${TMP_ROOT}/valid_review_with_failure_words"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_valid_with_failure_words "${dir}/gemini-review-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "valid_review_with_failure_words" "proceed" "multi_reviewer" 0
}

case_valid_review_with_fenced_failure_footer() {
  local dir="${TMP_ROOT}/valid_review_with_fenced_failure_footer"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_valid_with_fenced_failure_footer "${dir}/gemini-review-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "valid_review_with_fenced_failure_footer" "proceed" "multi_reviewer" 0
}

case_valid_request_changes_with_skipped_word() {
  local dir="${TMP_ROOT}/valid_request_changes_with_skipped_word"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_skipped "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-architect-current.md" "approve_with_notes"
  write_valid_request_changes_with_skipped_word "${dir}/codex-test-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/codex-test-current.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "valid_request_changes_with_skipped_word" "revise" "codex_only_degraded" 1 "claude:skipped, gemini:skipped"
}

case_prompt_echo_choices_do_not_approve() {
  local dir="${TMP_ROOT}/prompt_echo_choices_do_not_approve"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_prompt_echo_only "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-architect-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "prompt_echo_choices_do_not_approve" "proceed_degraded" "single_external_plus_codex_fallback" 0 "gemini:unknown"
}

case_prompt_echo_then_real_verdict() {
  local dir="${TMP_ROOT}/prompt_echo_then_real_verdict"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_prompt_echo_then_valid_verdict "${dir}/gemini-review-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "prompt_echo_then_real_verdict" "proceed" "multi_reviewer" 0
}

case_single_bullet_verdict() {
  local dir="${TMP_ROOT}/single_bullet_verdict"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_single_bullet_verdict "${dir}/gemini-review-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "none"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/missing-architect.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "single_bullet_verdict" "proceed" "multi_reviewer" 0
}

case_single_bullet_echo_then_valid_verdict() {
  local dir="${TMP_ROOT}/single_bullet_echo_then_valid_verdict"
  mkdir -p "${dir}"

  write_skipped "${dir}/claude-review-current.md"
  write_skipped "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-architect-current.md" "approve"
  write_single_bullet_echo_then_valid_verdict "${dir}/codex-test-current.md"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/codex-test-current.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "single_bullet_echo_then_valid_verdict" "revise" "codex_only_degraded" 1 "claude:skipped, gemini:skipped"
}

case_fenced_prompt_echo_ignored() {
  local dir="${TMP_ROOT}/fenced_prompt_echo_ignored"
  mkdir -p "${dir}"

  write_verdict "${dir}/claude-review-current.md" "approve"
  write_fenced_prompt_echo_only "${dir}/gemini-review-current.md"
  write_verdict "${dir}/codex-architect-current.md" "approve_with_notes"
  write_fallback_summary "${dir}/codex-fallback-summary-current.md" "informational_only"
  write_run_summary "${dir}" \
    "${dir}/claude-review-current.md" \
    "${dir}/gemini-review-current.md" \
    "${dir}/codex-architect-current.md" \
    "${dir}/missing-test.md" \
    "${dir}/codex-fallback-summary-current.md"

  assert_summary "fenced_prompt_echo_ignored" "proceed_degraded" "single_external_plus_codex_fallback" 0 "gemini:unknown"
}

case_multi_reviewer
case_single_external_plus_codex
case_codex_only_degraded
case_missing_fallback_blocks
case_request_changes_blocks
case_stale_fallback_ignored
case_failed_reviewer_prompt_text_ignored
case_failed_reviewer_skipped_text_ignored
case_valid_review_with_failure_words
case_valid_review_with_fenced_failure_footer
case_valid_request_changes_with_skipped_word
case_prompt_echo_choices_do_not_approve
case_prompt_echo_then_real_verdict
case_single_bullet_verdict
case_single_bullet_echo_then_valid_verdict
case_fenced_prompt_echo_ignored

echo "[summary-test] success"
