#!/usr/bin/env bash
set -euo pipefail

FIX=0
SKIP_DIRTY_CHECK="${DOCTOR_SKIP_DIRTY_CHECK:-0}"
OMX_ARTIFACT_WARN_COUNT="${OMX_ARTIFACT_WARN_COUNT:-200}"

usage() {
  cat <<'USAGE'
Usage: ./scripts/automation-doctor.sh [--fix]

Diagnose whether this repository is ready for the Codex/OMX automation loop.

Default mode prints status and suggested repair commands without changing files.
With --fix, the doctor may apply safe non-overwriting automation setup fixes.
--fix does not edit shell profile files or other user environment configuration.

Environment:
  DOCTOR_SKIP_DIRTY_CHECK=1  skip the uncommitted-changes check
  OMX_ARTIFACT_WARN_COUNT=N   warn when a .omx artifact directory has more than N files
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

if [ -d "${TEMPLATE_DIR}" ] && [ -x "${ROOT}/tools/ai-auto-init" ] && [ -x "${ROOT}/tools/ai-home" ] && [ -x "${ROOT}/tools/ai-register" ] && [ -x "${ROOT}/tools/ai-auto-template-status" ] && [ -x "${ROOT}/tools/ai-refactor-scan" ] && [ -x "${ROOT}/tools/ai-rebuild-plan" ] && [ -x "${ROOT}/tools/ai-split-plan" ] && [ -x "${ROOT}/tools/ai-split-dry-run" ] && [ -x "${ROOT}/tools/ai-split-apply" ] && [ -x "${ROOT}/tools/ai-plan-status" ] && [ -x "${ROOT}/tools/ai-interview-record" ] && [ -x "${ROOT}/tools/ai-plan-review" ] && [ -x "${ROOT}/tools/ai-plan-export" ] && [ -x "${ROOT}/tools/feedback-collect" ] && [ -x "${ROOT}/tools/workspace-scan" ]; then
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

case "${OMX_ARTIFACT_WARN_COUNT}" in
  ''|*[!0-9]*)
    say_warn "invalid OMX_ARTIFACT_WARN_COUNT='${OMX_ARTIFACT_WARN_COUNT}'; using 200"
    OMX_ARTIFACT_WARN_COUNT=200
    ;;
esac

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

command_help_supports() {
  local help_text="$1"
  local flag="$2"

  printf '%s\n' "$help_text" | grep -q -- "$flag"
}

check_gemini_cli_capabilities() {
  local gemini_help

  if ! command -v gemini >/dev/null 2>&1; then
    return
  fi

  gemini_help="$(gemini --help 2>/dev/null || true)"
  if [ -z "$gemini_help" ]; then
    say_warn "Gemini help output unavailable; non-interactive review mode could not be inspected"
    suggest "run gemini --help in an interactive terminal"
    return
  fi

  if command_help_supports "$gemini_help" "--prompt"; then
    say_pass "Gemini supports non-interactive prompt mode (--prompt)"
  else
    say_warn "Gemini --prompt support not detected; review may fall back to stdin and can be affected by auth prompts"
    suggest "check Gemini CLI version or use REVIEW_EXECUTION_MODE=external when Gemini hangs"
  fi

  if command_help_supports "$gemini_help" "--approval-mode"; then
    say_pass "Gemini supports approval mode control"
  else
    say_warn "Gemini approval mode flag not detected; CLI may request interactive approvals"
  fi

  if command_help_supports "$gemini_help" "--skip-trust"; then
    say_pass "Gemini supports skip-trust flag"
  else
    say_warn "Gemini skip-trust flag not detected; workspace trust prompts may appear"
  fi

  if command_help_supports "$gemini_help" "--output-format"; then
    say_pass "Gemini supports text output format control"
  else
    say_warn "Gemini output format flag not detected; review parsing may be less predictable"
  fi

  if command_help_supports "$gemini_help" "--model"; then
    say_pass "Gemini supports explicit model selection"
  else
    say_warn "Gemini --model flag not detected; provider default model will be used"
  fi

  printf '[doctor] Gemini review timeout default: %s seconds\n' "${GEMINI_REVIEW_TIMEOUT_SECONDS:-${REVIEW_TIMEOUT_SECONDS:-300}}"
  printf '[doctor] Gemini large prompt stdin threshold: %s bytes\n' "${GEMINI_PROMPT_ARG_MAX_BYTES:-100000}"
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
  "AI_AUTO_TEMPLATE_VERSION"
  "AGENTS.md"
  "docs/AI_MODEL_ROUTING.md"
  "docs/AUTOMATION_OPERATING_POLICY.md"
  "docs/DOMAIN_PACKS.md"
  "docs/DOMAIN_PACK_AUTHORING_GUIDE.md"
  "docs/INTERVIEW_PLAN_LAYER.md"
  "docs/INCIDENT_OPS.md"
  "docs/DATA_COMPLETION.md"
  "docs/DEPLOYMENT_COMPLETION.md"
  "docs/OBSERVABILITY_COMPLETION.md"
  "docs/PERFORMANCE_COMPLETION.md"
  "docs/SECURITY_COMPLETION.md"
  "docs/SESSION_QUALITY_PLAN.md"
  "docs/UI_COMPLETION.md"
  "docs/WORKFLOW.md"
  "scripts/archive-omx-artifacts.sh"
  "scripts/review-gate.sh"
  "scripts/collect-review-context.sh"
  "scripts/discover-ai-models.sh"
  "scripts/make-review-prompts.sh"
  "scripts/record-feedback.sh"
  "scripts/record-project-memory.sh"
  "scripts/resolve-feedback.sh"
  "scripts/run-ai-reviews.sh"
  "scripts/summarize-ai-reviews.sh"
  "scripts/test-review-summary.sh"
  "scripts/write-session-checkpoint.sh"
)

for path in "${REQUIRED_FILES[@]}"; do
  check_required_file "$path"
done

if [ "${IN_AI_LAB}" -eq 1 ]; then
  check_required_file "docs/AI_ROLES.md"
fi

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

check_gemini_cli_capabilities

echo
echo "[doctor] checking reviewer state"

if [ -d ".omx/reviewer-state" ]; then
  disabled_count=0
  for marker in .omx/reviewer-state/*.disabled; do
    [ -e "$marker" ] || continue
    disabled_count=$((disabled_count + 1))
    reviewer="$(basename "$marker" .disabled)"
    reason="$(sed -n 's/^reason=//p' "$marker" 2>/dev/null | head -n 1)"
    details="$(sed -n 's/^details=//p' "$marker" 2>/dev/null | head -n 1)"
    disabled_at="$(sed -n 's/^disabled_at=//p' "$marker" 2>/dev/null | head -n 1)"
    source_run_id="$(sed -n 's/^source_run_id=//p' "$marker" 2>/dev/null | head -n 1)"
    next_action="$(sed -n 's/^next_action=//p' "$marker" 2>/dev/null | head -n 1)"
    reset_hint="$(sed -n 's/^reset_hint=//p' "$marker" 2>/dev/null | head -n 1)"
    if [ -n "$reason" ]; then
      say_warn "reviewer disabled: ${reviewer} (${reason})"
    else
      say_warn "reviewer disabled: ${reviewer}"
    fi
    [ -n "$details" ] && printf '       details: %s\n' "$details"
    [ -n "$disabled_at" ] && printf '       disabled_at: %s\n' "$disabled_at"
    [ -n "$source_run_id" ] && printf '       source_run_id: %s\n' "$source_run_id"
    [ -n "$next_action" ] && printf '       next_action: %s\n' "$next_action"
    if [ -n "$reset_hint" ]; then
      printf '       reset_hint: %s\n' "$reset_hint"
      suggest "$reset_hint"
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
echo "[doctor] checking .omx session artifacts"

if [ -d ".omx" ]; then
  for artifact_dir in \
    ".omx/review-results" \
    ".omx/review-context" \
    ".omx/review-prompts" \
    ".omx/model-routing" \
    ".omx/external-review"
  do
    if [ ! -d "$artifact_dir" ]; then
      say_skip "session artifact directory missing: ${artifact_dir}"
      continue
    fi

    artifact_count="$(find "$artifact_dir" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$artifact_count" -gt "$OMX_ARTIFACT_WARN_COUNT" ]; then
      if [ "$FIX" -eq 1 ] && [ "$artifact_dir" = ".omx/review-results" ] && [ -x "scripts/archive-omx-artifacts.sh" ]; then
        if OMX_REVIEW_ARCHIVE_THRESHOLD="$OMX_ARTIFACT_WARN_COUNT" ./scripts/archive-omx-artifacts.sh; then
          say_fix "archived old review artifacts from ${artifact_dir}"
        else
          say_warn "review artifact archive failed for ${artifact_dir}"
          suggest "OMX_REVIEW_ARCHIVE_THRESHOLD=${OMX_ARTIFACT_WARN_COUNT} ./scripts/archive-omx-artifacts.sh --dry-run"
        fi
      else
        say_warn "session artifact directory has ${artifact_count} files: ${artifact_dir}"
        suggest "./scripts/archive-omx-artifacts.sh --dry-run"
        suggest "./scripts/automation-doctor.sh --fix"
      fi
    else
      say_pass "session artifact directory size ok: ${artifact_dir} (${artifact_count} files)"
    fi
  done

  latest_manifest="$(ls -t .omx/review-results/review-run-*.md 2>/dev/null | head -n 1 || true)"
  if [ -n "$latest_manifest" ]; then
    say_pass "latest review run manifest: ${latest_manifest}"
  else
    say_skip "no review run manifest recorded yet"
  fi
else
  say_warn ".omx directory is missing"
  suggest "./scripts/automation-doctor.sh --fix"
fi

echo
echo "[doctor] checking ai-lab helper links"

if [ "$IN_AI_LAB" -eq 1 ] && [ -n "$HOME_DIR" ] && [ "$HOME_READY" -eq 1 ]; then
  check_helper_link "${HOME_DIR}/bin/AI_AUTO" "${ROOT}/tools/ai-home"
  check_helper_link "${HOME_DIR}/bin/ai-auto-init" "${ROOT}/tools/ai-auto-init"
  check_helper_link "${HOME_DIR}/bin/ai-home" "${ROOT}/tools/ai-home"
  check_helper_link "${HOME_DIR}/bin/aiinit" "${ROOT}/tools/ai-auto-init"
  check_helper_link "${HOME_DIR}/bin/ai-register" "${ROOT}/tools/ai-register"
  check_helper_link "${HOME_DIR}/bin/ai-auto-template-status" "${ROOT}/tools/ai-auto-template-status"
  check_helper_link "${HOME_DIR}/bin/ai-refactor-scan" "${ROOT}/tools/ai-refactor-scan"
  check_helper_link "${HOME_DIR}/bin/ai-rebuild-plan" "${ROOT}/tools/ai-rebuild-plan"
  check_helper_link "${HOME_DIR}/bin/ai-split-plan" "${ROOT}/tools/ai-split-plan"
  check_helper_link "${HOME_DIR}/bin/ai-split-dry-run" "${ROOT}/tools/ai-split-dry-run"
  check_helper_link "${HOME_DIR}/bin/ai-split-apply" "${ROOT}/tools/ai-split-apply"
  check_helper_link "${HOME_DIR}/bin/ai-plan-status" "${ROOT}/tools/ai-plan-status"
  check_helper_link "${HOME_DIR}/bin/ai-interview-record" "${ROOT}/tools/ai-interview-record"
  check_helper_link "${HOME_DIR}/bin/ai-plan-review" "${ROOT}/tools/ai-plan-review"
  check_helper_link "${HOME_DIR}/bin/ai-plan-export" "${ROOT}/tools/ai-plan-export"
  check_helper_link "${HOME_DIR}/bin/feedback-collect" "${ROOT}/tools/feedback-collect"
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
