#!/usr/bin/env bash
set -euo pipefail

FIX=0
SKIP_DIRTY_CHECK="${DOCTOR_SKIP_DIRTY_CHECK:-0}"

usage() {
  cat <<'USAGE'
Usage: ./scripts/automation-doctor.sh [--fix]

Diagnose whether this repository is ready for the Codex/OMX automation loop.

Default mode prints status and suggested repair commands without changing files.
With --fix, the doctor may apply safe non-overwriting automation setup fixes.
--fix does not edit shell profile files or other user environment configuration.

Environment:
  DOCTOR_SKIP_DIRTY_CHECK=1  skip the uncommitted-changes check
USAGE
}

case "${1:-}" in
  "")
    ;;
  --fix)
    # Fix-mode invariants:
    # - never install external tools
    # - never overwrite existing project files
    # - never run destructive git operations
    # - only repair automation setup files, directories, executable bits, and helper links
    FIX=1
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown option: $1"
    echo
    usage
    exit 2
    ;;
esac

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
FIX_COUNT=0
SKIP_COUNT=0
SUGGESTIONS=()

ROOT="$(pwd)"
TEMPLATE_DIR="${ROOT}/templates/automation-base"
IN_AI_LAB=0
HOME_DIR="${HOME:-}"
HOME_READY=0

if [ -n "$HOME_DIR" ] && [ -d "$HOME_DIR" ]; then
  HOME_READY=1
fi

if [ -d "${TEMPLATE_DIR}" ] && [ -x "${ROOT}/tools/ai-auto-init" ] && [ -x "${ROOT}/tools/workspace-scan" ]; then
  IN_AI_LAB=1
fi

say_pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[pass] %s\n' "$1"
}

say_warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf '[warn] %s\n' "$1"
}

say_fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '[fail] %s\n' "$1"
}

say_fix() {
  FIX_COUNT=$((FIX_COUNT + 1))
  printf '[fix] %s\n' "$1"
}

say_skip() {
  SKIP_COUNT=$((SKIP_COUNT + 1))
  printf '[skip] %s\n' "$1"
}

suggest() {
  local suggestion="$1"
  local existing

  if [ "${#SUGGESTIONS[@]}" -gt 0 ]; then
    for existing in "${SUGGESTIONS[@]}"; do
      if [ "$existing" = "$suggestion" ]; then
        return
      fi
    done
  fi

  SUGGESTIONS+=("$suggestion")
}

copy_from_template_if_missing() {
  local path="$1"
  local source_path="${TEMPLATE_DIR}/${path}"

  if [ -e "$path" ]; then
    return 1
  fi

  if [ "$IN_AI_LAB" -ne 1 ] || [ ! -f "$source_path" ]; then
    return 1
  fi

  mkdir -p "$(dirname "$path")"
  cp "$source_path" "$path"
  case "$path" in
    scripts/*.sh)
      chmod +x "$path"
      ;;
  esac
  say_fix "created ${path} from automation template"
  return 0
}

ensure_dir() {
  local path="$1"

  if [ -d "$path" ]; then
    say_pass "directory exists: ${path}"
    return
  fi

  if [ "$FIX" -eq 1 ]; then
    mkdir -p "$path"
    say_fix "created directory: ${path}"
  else
    say_warn "directory missing: ${path}"
    suggest "./scripts/automation-doctor.sh --fix"
  fi
}

check_required_file() {
  local path="$1"

  if [ -f "$path" ]; then
    say_pass "required file exists: ${path}"
    return
  fi

  if [ "$FIX" -eq 1 ] && copy_from_template_if_missing "$path"; then
    return
  fi

  say_fail "required file missing: ${path}"
  if [ "$IN_AI_LAB" -eq 1 ]; then
    suggest "./scripts/automation-doctor.sh --fix"
  else
    suggest "aiinit"
  fi
}

check_executable() {
  local path="$1"

  if [ ! -f "$path" ]; then
    return
  fi

  if [ -x "$path" ]; then
    say_pass "script is executable: ${path}"
    return
  fi

  if [ "$FIX" -eq 1 ]; then
    chmod +x "$path"
    say_fix "made script executable: ${path}"
  else
    say_fail "script is not executable: ${path}"
    suggest "./scripts/automation-doctor.sh --fix"
    suggest "chmod +x scripts/*.sh"
  fi
}

check_command() {
  local name="$1"
  local severity="$2"

  if command -v "$name" >/dev/null 2>&1; then
    say_pass "command available: ${name}"
  elif [ "$severity" = "fail" ]; then
    say_fail "required command missing: ${name}"
    suggest "install ${name} and ensure it is on PATH"
  else
    say_warn "optional command missing: ${name}"
    suggest "install ${name} if this workflow needs it"
  fi
}

check_helper_link() {
  local link_path="$1"
  local target_path="$2"

  if [ "$IN_AI_LAB" -ne 1 ]; then
    return
  fi

  if [ -L "$link_path" ] && [ "$(readlink "$link_path")" = "$target_path" ]; then
    say_pass "global helper link ok: ${link_path}"
    return
  fi

  if [ -e "$link_path" ] && [ ! -L "$link_path" ]; then
    say_warn "global helper path exists but is not a symlink: ${link_path}"
    suggest "review ${link_path} before replacing it"
    return
  fi

  if [ "$FIX" -eq 1 ]; then
    mkdir -p "$(dirname "$link_path")"
    ln -sfn "$target_path" "$link_path"
    say_fix "linked ${link_path} -> ${target_path}"
  elif [ -L "$link_path" ]; then
    say_warn "global helper link points elsewhere: ${link_path}"
    suggest "./scripts/automation-doctor.sh --fix"
  else
    say_warn "global helper link missing or points elsewhere: ${link_path}"
    suggest "./scripts/automation-doctor.sh --fix"
  fi
}

printf '[doctor] checking automation readiness in %s\n\n' "$ROOT"

check_command git fail

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  say_pass "git repository detected"

  git_root="$(git rev-parse --show-toplevel)"
  if [ "$ROOT" = "$git_root" ]; then
    say_pass "running from git repository root"
  else
    say_fail "not running from git repository root: ${git_root}"
    suggest "cd ${git_root}"
    echo
    printf 'Summary: %s passed, %s warnings, %s failed' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
    if [ "$SKIP_COUNT" -gt 0 ]; then
      printf ', %s skipped' "$SKIP_COUNT"
    fi
    printf '\n'
    echo
    echo "Suggested fixes:"
    echo "  cd ${git_root}"
    exit 1
  fi

  if [ "$SKIP_DIRTY_CHECK" = "1" ]; then
    say_skip "working tree dirty check skipped (DOCTOR_SKIP_DIRTY_CHECK=1)"
  elif [ -n "$(git status --short 2>/dev/null)" ]; then
    say_warn "working tree has uncommitted changes"
    suggest "git status --short"
  else
    say_pass "working tree is clean"
  fi

  if git remote get-url origin >/dev/null 2>&1; then
    say_pass "git remote origin is configured"
  else
    say_warn "git remote origin is not configured"
    suggest "git remote add origin <repo-url>"
  fi
else
  say_fail "current directory is not a git repository"
  suggest "git init"
fi

echo
echo "[doctor] checking automation files"

ensure_dir ".omx"
ensure_dir ".omx/reviewer-state"
ensure_dir "docs"
ensure_dir "scripts"

REQUIRED_FILES=(
  "AGENTS.md"
  "docs/WORKFLOW.md"
  "scripts/review-gate.sh"
  "scripts/collect-review-context.sh"
  "scripts/discover-ai-models.sh"
  "scripts/make-review-prompts.sh"
  "scripts/run-ai-reviews.sh"
  "scripts/summarize-ai-reviews.sh"
  "scripts/test-review-summary.sh"
)

for path in "${REQUIRED_FILES[@]}"; do
  check_required_file "$path"
done

if [ -f "scripts/verify.sh" ]; then
  say_pass "required file exists: scripts/verify.sh"
  if grep -q "VERIFY_TEMPLATE_UNCONFIGURED=1" "scripts/verify.sh"; then
    say_warn "scripts/verify.sh is still the generic onboarding placeholder"
    suggest "interview the project requirements and replace scripts/verify.sh with project-specific checks"
  fi
elif [ -f "scripts/verify.example.sh" ]; then
  say_warn "scripts/verify.sh is missing; template example exists"
  suggest "mv scripts/verify.example.sh scripts/verify.sh && chmod +x scripts/verify.sh"
else
  check_required_file "scripts/verify.sh"
fi

for path in scripts/*.sh; do
  [ -e "$path" ] || continue
  check_executable "$path"
done

echo
echo "[doctor] checking optional runtime tools"

check_command docker warn

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    say_pass "Docker daemon is reachable"
  else
    say_warn "Docker command exists but daemon is not reachable"
    suggest "start Docker or check Docker socket permissions"
  fi
fi

check_command claude warn
check_command gemini warn

echo
echo "[doctor] checking reviewer state"

if [ -d ".omx/reviewer-state" ]; then
  disabled_count=0
  for marker in .omx/reviewer-state/*.disabled; do
    [ -e "$marker" ] || continue
    disabled_count=$((disabled_count + 1))
    reviewer="$(basename "$marker" .disabled)"
    reason="$(sed -n 's/^reason=//p' "$marker" 2>/dev/null | head -n 1)"
    if [ -n "$reason" ]; then
      say_warn "reviewer disabled: ${reviewer} (${reason})"
    else
      say_warn "reviewer disabled: ${reviewer}"
    fi
  done

  if [ "$disabled_count" -eq 0 ]; then
    say_pass "no disabled reviewers recorded"
  else
    suggest "RESET_DISABLED_AI_REVIEWERS=all ./scripts/review-gate.sh"
  fi
else
  say_warn "reviewer state directory is missing"
  suggest "./scripts/automation-doctor.sh --fix"
fi

echo
echo "[doctor] checking ai-lab helper links"

if [ "$IN_AI_LAB" -eq 1 ] && [ -n "$HOME_DIR" ] && [ "$HOME_READY" -eq 1 ]; then
  check_helper_link "${HOME_DIR}/bin/ai-auto-init" "${ROOT}/tools/ai-auto-init"
  check_helper_link "${HOME_DIR}/bin/aiinit" "${ROOT}/tools/ai-auto-init"
  check_helper_link "${HOME_DIR}/bin/workspace-scan" "${ROOT}/tools/workspace-scan"
  case ":${PATH}:" in
    *":${HOME_DIR}/bin:"*)
      say_pass "global helper directory is on PATH: ${HOME_DIR}/bin"
      ;;
    *)
      say_warn "global helper directory is not on PATH: ${HOME_DIR}/bin"
      suggest 'export PATH="$HOME/bin:$PATH"'
      ;;
  esac
elif [ "$IN_AI_LAB" -eq 1 ] && [ -n "$HOME_DIR" ]; then
  say_warn "HOME directory does not exist; ai-lab helper link checks skipped: ${HOME_DIR}"
  suggest "set HOME to an existing user directory"
elif [ "$IN_AI_LAB" -eq 1 ]; then
  say_warn "HOME is not set; ai-lab helper link checks skipped"
else
  say_pass "not running inside ai-lab source checkout; helper link checks skipped"
fi

echo
printf 'Summary: %s passed, %s warnings, %s failed' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
if [ "$FIX_COUNT" -gt 0 ]; then
  printf ', %s fixed' "$FIX_COUNT"
fi
if [ "$SKIP_COUNT" -gt 0 ]; then
  printf ', %s skipped' "$SKIP_COUNT"
fi
printf '\n'

if [ "${#SUGGESTIONS[@]}" -gt 0 ]; then
  echo
  echo "Suggested fixes:"
  for suggestion in "${SUGGESTIONS[@]}"; do
    printf '  %s\n' "$suggestion"
  done
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi

exit 0
