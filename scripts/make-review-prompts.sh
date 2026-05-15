#!/usr/bin/env bash
set -euo pipefail

CONTEXT_FILE="${1:-.omx/review-context/latest-review-context.md}"
OUT_DIR="${OUT_DIR:-.omx/review-prompts}"
REVIEW_CONTEXT_MAX_BYTES="${REVIEW_CONTEXT_MAX_BYTES:-750000}"
FOCUSED_CONTEXT_DIFF_MAX_BYTES="${FOCUSED_CONTEXT_DIFF_MAX_BYTES:-300000}"
FOCUSED_CONTEXT_UNTRACKED_MAX_BYTES="${FOCUSED_CONTEXT_UNTRACKED_MAX_BYTES:-102400}"

mkdir -p "${OUT_DIR}"
rm -f "${OUT_DIR}/focused-review-context.md"

if [ ! -f "${CONTEXT_FILE}" ]; then
  echo "Review context file not found: ${CONTEXT_FILE}"
  echo "Run ./scripts/collect-review-context.sh first."
  exit 1
fi

ORIGINAL_CONTEXT_FILE="${CONTEXT_FILE}"
context_bytes="$(wc -c < "${CONTEXT_FILE}")"
if [ "${context_bytes}" -gt "${REVIEW_CONTEXT_MAX_BYTES}" ]; then
  FOCUSED_CONTEXT_FILE="${OUT_DIR}/focused-review-context.md"
  FOCUSED_DIFF_FILE="$(mktemp "${OUT_DIR}/focused-diff.XXXXXX")"
  {
    git diff
    git diff --cached
    while IFS= read -r -d '' file; do
      [ -f "$file" ] || continue
      grep -qI '' "$file" 2>/dev/null || continue
      size="$(wc -c < "$file" | tr -d ' ')"
      if [ "$size" -gt "$FOCUSED_CONTEXT_UNTRACKED_MAX_BYTES" ]; then
        echo "diff --git a/${file} b/${file}"
        echo "# skipped untracked file content: ${file} is ${size} bytes, limit is ${FOCUSED_CONTEXT_UNTRACKED_MAX_BYTES}"
        continue
      fi
      git diff --no-index -- /dev/null "$file" || true
    done < <(git ls-files -z --others --exclude-standard)
  } > "${FOCUSED_DIFF_FILE}"
  focused_diff_bytes="$(wc -c < "${FOCUSED_DIFF_FILE}")"
  {
    echo "# Focused Review Context"
    echo
    echo "The original review context was ${context_bytes} bytes and exceeded REVIEW_CONTEXT_MAX_BYTES=${REVIEW_CONTEXT_MAX_BYTES}."
    echo "This focused context keeps the review bounded so external reviewers do not have to consume the full dirty workspace context."
    echo "If this focused context is insufficient, return request_changes and name the missing file or section."
    echo
    echo "## Source Context"
    echo
    echo "- Full context: ${ORIGINAL_CONTEXT_FILE}"
    echo
    echo "## Changed Files"
    echo
    echo '```text'
    git diff --name-only
    git diff --cached --name-only
    git ls-files --others --exclude-standard
    echo '```'
    echo
    echo "## Diff Stat"
    echo
    echo '```text'
    git diff --stat
    git diff --cached --stat
    echo '```'
    echo
    echo "## Bounded Actual Diff"
    echo
    echo "This section preserves actual patch content before the head/tail excerpts. It is capped at FOCUSED_CONTEXT_DIFF_MAX_BYTES=${FOCUSED_CONTEXT_DIFF_MAX_BYTES}."
    echo
    echo '```diff'
    if [ "${focused_diff_bytes}" -gt 0 ]; then
      head -c "${FOCUSED_CONTEXT_DIFF_MAX_BYTES}" "${FOCUSED_DIFF_FILE}"
      echo
      if [ "${focused_diff_bytes}" -gt "${FOCUSED_CONTEXT_DIFF_MAX_BYTES}" ]; then
        echo "# focused diff truncated: ${focused_diff_bytes} bytes total, limit is ${FOCUSED_CONTEXT_DIFF_MAX_BYTES}"
      fi
    else
      echo "# no tracked diff or untracked text content available"
    fi
    echo '```'
    echo
    echo "## Context Head"
    echo
    echo '```markdown'
    sed -n '1,220p' "${ORIGINAL_CONTEXT_FILE}"
    echo '```'
    echo
    echo "## Context Tail"
    echo
    echo '```markdown'
    tail -220 "${ORIGINAL_CONTEXT_FILE}"
    echo '```'
  } > "${FOCUSED_CONTEXT_FILE}"
  rm -f "${FOCUSED_DIFF_FILE}"
  CONTEXT_FILE="${FOCUSED_CONTEXT_FILE}"
fi

CLAUDE_PROMPT="${OUT_DIR}/claude-review.md"
GEMINI_PROMPT="${OUT_DIR}/gemini-review.md"

cat > "${CLAUDE_PROMPT}" <<PROMPT
# Claude Review Request

You are reviewing a small Codex-generated change in this repository.

Focus on:

- correctness
- maintainability
- scope control
- hidden risk
- whether the change follows AGENTS.md and docs/WORKFLOW.md
PROMPT

cat >> "${CLAUDE_PROMPT}" <<PROMPT

Do not suggest broad rewrites unless the current diff is unsafe.

Return your review in this format:

## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes

## Findings

List concrete issues only. For each issue include:

- severity: low / medium / high
- file or area
- reason
- suggested fix

## Scope Check

Say whether the change stayed within the requested scope.

## Verification Check

Say whether the reported verification evidence is sufficient.

## Final Recommendation

Give a short final recommendation.

---
PROMPT

cat "${CONTEXT_FILE}" >> "${CLAUDE_PROMPT}"

cat > "${GEMINI_PROMPT}" <<PROMPT
# Gemini Review Request

You are reviewing a small Codex-generated change in this repository.

Focus on:

- missed edge cases
- alternative simpler approaches
- test coverage
- documentation clarity
- whether the change creates future automation friction
PROMPT

cat >> "${GEMINI_PROMPT}" <<PROMPT

Do not expand the task beyond the requested scope.

Return your review in this format:

## Verdict

Choose one:

- approve
- approve_with_notes
- request_changes

## Missed Cases

List any missing cases or assumptions.

## Simpler Alternative

Mention a simpler approach only if it is clearly better.

## Test Ideas

Suggest only relevant tests or checks.

## Documentation Clarity

Say whether the documentation is clear enough for the next agent.

## Final Recommendation

Give a short final recommendation.

---
PROMPT

cat "${CONTEXT_FILE}" >> "${GEMINI_PROMPT}"

echo "${CLAUDE_PROMPT}"
echo "${GEMINI_PROMPT}"
