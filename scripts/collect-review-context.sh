#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-.omx/review-context}"
INCLUDE_UNTRACKED_CONTENT="${INCLUDE_UNTRACKED_CONTENT:-0}"
MAX_UNTRACKED_BYTES="${MAX_UNTRACKED_BYTES:-102400}"
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

{
  echo "# Review Context"
  echo
  echo "Generated at: $(date -Iseconds)"
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
    sed -n '1,240p' "${OUT_DIR}/latest-verify-output.txt"
    echo '```'
    echo
  fi
  echo "## Workflow Rule"
  echo
  echo "- Before completion, run ./scripts/verify.sh"
  echo "- If verification fails, the task is not complete."
  echo "- Do not commit without user approval."
  echo
  echo "## Relevant Files"
  echo
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
} > "${OUT_FILE}"

echo "${OUT_FILE}"
