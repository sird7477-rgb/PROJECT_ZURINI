#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-.omx/review-context}"
INCLUDE_UNTRACKED_CONTENT="${INCLUDE_UNTRACKED_CONTENT:-0}"
MAX_UNTRACKED_BYTES="${MAX_UNTRACKED_BYTES:-102400}"
REVIEW_CONTEXT_DETAIL="${REVIEW_CONTEXT_DETAIL:-auto}"
REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES="${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES:-50000}"
REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES="${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES:-80}"
REPO_STATUS_BEFORE_CONTEXT="$(git status --porcelain 2>/dev/null || true)"
OUT_FILE="${OUT_DIR}/latest-review-context.md"

mkdir -p "${OUT_DIR}"

has_worktree_diff() {
  has_unstaged_diff || has_staged_diff
}

has_unstaged_diff() {
  local status
  if git diff --quiet --exit-code >/dev/null 2>&1; then
    return 1
  else
    status="$?"
  fi

  case "$status" in
    1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

has_staged_diff() {
  local status
  if git diff --cached --quiet --exit-code >/dev/null 2>&1; then
    return 1
  else
    status="$?"
  fi

  case "$status" in
    1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

has_head_commit() {
  git rev-parse --verify HEAD >/dev/null 2>&1
}

is_status_clean() {
  [ -z "${REPO_STATUS_BEFORE_CONTEXT}" ]
}

is_positive_integer() {
  printf '%s\n' "$1" | grep -Eq '^[0-9]+$'
}

tracked_diff_bytes() {
  {
    git diff 2>/dev/null || true
    git diff --cached 2>/dev/null || true
  } | wc -c | tr -d ' '
}

use_lightweight_context() {
  case "${REVIEW_CONTEXT_DETAIL}" in
    light)
      return 0
      ;;
    full)
      return 1
      ;;
    auto)
      ;;
    *)
      echo "Unknown REVIEW_CONTEXT_DETAIL=${REVIEW_CONTEXT_DETAIL}; expected auto, light, or full" >&2
      exit 2
      ;;
  esac

  has_worktree_diff || return 1
  is_positive_integer "${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES}" || return 1

  local diff_bytes
  diff_bytes="$(tracked_diff_bytes)"
  is_positive_integer "${diff_bytes}" || return 1
  [ "${diff_bytes}" -gt 0 ] || return 1
  [ "${diff_bytes}" -le "${REVIEW_LIGHTWEIGHT_DIFF_MAX_BYTES}" ]
}

write_diff_stat() {
  if has_worktree_diff; then
    if has_unstaged_diff; then
      echo "### Unstaged Diff Stat"
      echo
      echo '```text'
      git diff --stat
      echo '```'
      echo
    fi
    if has_staged_diff; then
      echo "### Staged Diff Stat"
      echo
      echo '```text'
      git diff --cached --stat
      echo '```'
      echo
    fi
    return 0
  fi

  if has_head_commit && is_status_clean; then
    echo "No working tree diff detected; showing latest commit diff for post-commit review context."
    echo
    echo '```text'
    git show --stat --oneline --decorate --find-renames HEAD
    echo '```'
    echo
    return 0
  fi

  echo "No staged or unstaged tracked diff detected. Untracked files, if any, are shown in the Untracked Files section."
}

write_diff() {
  if has_worktree_diff; then
    if has_unstaged_diff; then
      echo "### Unstaged Diff"
      echo
      echo '```diff'
      git diff
      echo '```'
      echo
    fi
    if has_staged_diff; then
      echo "### Staged Diff"
      echo
      echo '```diff'
      git diff --cached
      echo '```'
      echo
    fi
    return 0
  fi

  if has_head_commit && is_status_clean; then
    echo "No working tree diff detected; showing latest commit diff for post-commit review context."
    echo
    echo '```diff'
    git show --format= --find-renames HEAD
    echo '```'
    echo
    return 0
  fi

  echo "No staged or unstaged tracked diff detected. Untracked files, if any, are shown in the Untracked Files section."
}

LIGHTWEIGHT_CONTEXT=0
if use_lightweight_context; then
  LIGHTWEIGHT_CONTEXT=1
fi

{
  echo "# Review Context"
  echo
  echo "Generated at: $(date -Iseconds)"
  echo
  echo "## Context Mode"
  echo
  if [ "${LIGHTWEIGHT_CONTEXT}" -eq 1 ]; then
    echo "lightweight"
    echo
    echo "Small staged/unstaged tracked diff detected. This context keeps reviewer input focused on the patch, git state, and verification tail."
    echo "Set REVIEW_CONTEXT_DETAIL=full to include planning artifacts and reference files."
  else
    echo "full"
    echo
    echo "Full context includes planning artifacts and repository workflow reference files."
  fi
  echo
  echo "## Repository"
  echo
  echo '```text'
  pwd
  echo '```'
  echo
  echo "## Git Status"
  echo
  echo '```text'
  git status --short
  echo '```'
  echo
  echo "## Diff Stat"
  echo
  write_diff_stat
  echo
  echo "## Untracked Files"
  echo
  echo '```text'
  git ls-files --others --exclude-standard
  echo '```'
  echo
  echo "Untracked text file content is omitted by default. Set INCLUDE_UNTRACKED_CONTENT=1 to include text files up to ${MAX_UNTRACKED_BYTES} bytes after confirming .gitignore excludes secrets."
  echo
  echo "## Diff"
  echo
  write_diff
  if [ "$INCLUDE_UNTRACKED_CONTENT" = "1" ]; then
    echo "### Untracked File Content Diff"
    echo
    echo '```diff'
    while IFS= read -r -d '' file; do
      [ -f "$file" ] || continue
      grep -qI '' "$file" 2>/dev/null || continue
      size="$(wc -c < "$file" | tr -d ' ')"
      if [ "$size" -gt "$MAX_UNTRACKED_BYTES" ]; then
        echo "diff --git a/${file} b/${file}"
        echo "# skipped untracked file content: ${file} is ${size} bytes, limit is ${MAX_UNTRACKED_BYTES}"
        continue
      fi
      git diff --no-index -- /dev/null "$file" || true
    done < <(git ls-files -z --others --exclude-standard)
    echo '```'
  fi
  echo
    if [ -f "${OUT_DIR}/latest-verify-output.txt" ]; then
      echo "## Latest Verification Output"
      echo
      echo '```text'
      if [ "${LIGHTWEIGHT_CONTEXT}" -eq 1 ]; then
        echo "### Tail"
        tail -"${REVIEW_LIGHTWEIGHT_VERIFY_TAIL_LINES}" "${OUT_DIR}/latest-verify-output.txt"
      else
        echo "### Head"
        sed -n '1,160p' "${OUT_DIR}/latest-verify-output.txt"
        echo
        echo "### Tail"
        tail -120 "${OUT_DIR}/latest-verify-output.txt"
      fi
      echo '```'
      echo
    fi
  echo "## Workflow Rule"
  echo
  echo "- Before completion, run ./scripts/verify.sh"
  echo "- If verification fails, the task is not complete."
  echo "- Do not commit without user approval."
  echo
  echo "## Local Planning Artifacts"
  echo
  if [ -f "docs/plan-a-next-actions.md" ]; then
    echo "### docs/plan-a-next-actions.md"
    echo
    echo '```markdown'
    if [ "${LIGHTWEIGHT_CONTEXT}" -eq 1 ]; then
      sed -n '1,180p' "docs/plan-a-next-actions.md"
    else
      sed -n '1,260p' "docs/plan-a-next-actions.md"
    fi
    echo '```'
    echo
  fi
  if [ "${LIGHTWEIGHT_CONTEXT}" -eq 1 ]; then
    echo "Additional .omx planning artifacts are omitted in lightweight context. Set REVIEW_CONTEXT_DETAIL=full when deeper planning artifacts are relevant to the review."
    echo
  else
  plan_files=()
  if [ -d ".omx/plans" ]; then
    while IFS= read -r file; do
      plan_files+=("$file")
    done < <(find .omx/plans -maxdepth 1 -type f \( -name 'prd-*.md' -o -name 'test-spec-*.md' \) | sort | tail -6)
  fi
  if [ "${#plan_files[@]}" -eq 0 ]; then
    echo "No local PRD or test-spec planning artifacts found."
    echo
  else
    for file in "${plan_files[@]}"; do
      echo "### $file"
      echo
      echo '```markdown'
      sed -n '1,180p' "$file"
      echo '```'
      echo
    done
  fi
  fi
  echo "## Relevant Files"
  echo
  if [ "${LIGHTWEIGHT_CONTEXT}" -eq 1 ]; then
    echo "Lightweight context includes policy excerpts because review-gate decisions depend on AGENTS.md and workflow compliance."
    echo
    for file in AGENTS.md docs/WORKFLOW.md docs/AI_ROLES.md; do
      if [ -f "$file" ]; then
        echo "### $file"
        echo
        echo '```markdown'
        sed -n '1,120p' "$file"
        echo '```'
        echo
      fi
    done
  else
  for file in AGENTS.md docs/WORKFLOW.md docs/AI_ROLES.md; do
    if [ -f "$file" ]; then
      echo "### $file"
      echo
      echo '```markdown'
      sed -n '1,200p' "$file"
      echo '```'
      echo
    fi
  done
  fi
} > "${OUT_FILE}"

echo "${OUT_FILE}"
