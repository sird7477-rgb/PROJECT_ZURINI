#!/usr/bin/env bash
set -euo pipefail

CONTEXT_FILE="${1:-.omx/review-context/latest-review-context.md}"
OUT_DIR="${OUT_DIR:-.omx/review-prompts}"

mkdir -p "${OUT_DIR}"

if [ ! -f "${CONTEXT_FILE}" ]; then
  echo "Review context file not found: ${CONTEXT_FILE}"
  echo "Run ./scripts/collect-review-context.sh first."
  exit 1
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
