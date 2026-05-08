#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${AI_MODEL_DISCOVERY_DIR:-.omx/model-routing}"
ENV_OUT="${AI_MODEL_ROUTING_ENV:-${OUT_DIR}/latest.env}"
REPORT_OUT="${AI_MODEL_ROUTING_REPORT:-${OUT_DIR}/latest.md}"

mkdir -p "${OUT_DIR}" "$(dirname "${ENV_OUT}")" "$(dirname "${REPORT_OUT}")"

shell_quote() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

write_env() {
  local key="$1"
  local value="$2"

  printf "%s='%s'\n" "${key}" "$(shell_quote "${value}")" >> "${ENV_OUT}"
}

command_version() {
  local command_name="$1"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "missing"
    return 0
  fi

  "${command_name}" --version 2>/dev/null | head -1 || echo "available"
}

command_help() {
  local command_name="$1"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    return 0
  fi

  "${command_name}" --help 2>/dev/null || true
}

supports_flag() {
  local help_text="$1"
  local flag="$2"

  printf '%s\n' "${help_text}" | grep -Eq "(^|[^[:alnum:]_-])${flag}($|[^[:alnum:]_-])"
}

contains_word() {
  local text="$1"
  local word="$2"

  printf '%s\n' "${text}" | grep -qiE "(^|[^[:alnum:]_-])${word}([^[:alnum:]_-]|$)"
}

first_nonempty() {
  local value

  for value in "$@"; do
    if [ -n "${value}" ]; then
      echo "${value}"
      return 0
    fi
  done

  return 0
}

claude_help="$(command_help claude)"
gemini_help="$(command_help gemini)"
codex_exec_help=""
if command -v codex >/dev/null 2>&1; then
  codex_exec_help="$(codex exec --help 2>/dev/null || true)"
fi

claude_supports_model=0
gemini_supports_model=0
codex_supports_model=0

if supports_flag "${claude_help}" "--model"; then
  claude_supports_model=1
fi

if supports_flag "${gemini_help}" "--model"; then
  gemini_supports_model=1
fi

if supports_flag "${codex_exec_help}" "--model"; then
  codex_supports_model=1
fi

claude_aliases=()
if contains_word "${claude_help}" "opus"; then
  claude_aliases+=("opus")
fi
if contains_word "${claude_help}" "sonnet"; then
  claude_aliases+=("sonnet")
fi

claude_review_model="${CLAUDE_REVIEW_MODEL:-}"
claude_review_model_source="env:CLAUDE_REVIEW_MODEL"
if [ -z "${claude_review_model}" ] && [ "${claude_supports_model}" -eq 1 ]; then
  if contains_word "${claude_help}" "opus"; then
    claude_review_model="opus"
    claude_review_model_source="claude-cli-alias:opus"
  elif contains_word "${claude_help}" "sonnet"; then
    claude_review_model="sonnet"
    claude_review_model_source="claude-cli-alias:sonnet"
  else
    claude_review_model_source="default"
  fi
fi

gemini_review_model="${GEMINI_REVIEW_MODEL:-}"
gemini_review_model_source="env:GEMINI_REVIEW_MODEL"
if [ -z "${gemini_review_model}" ]; then
  gemini_review_model_source="default"
fi

codex_architect_model="$(first_nonempty \
  "${CODEX_ARCHITECT_REVIEW_MODEL:-}" \
  "${CODEX_FALLBACK_MODEL:-}" \
  "${OMX_DEFAULT_FRONTIER_MODEL:-}")"
codex_architect_model_source="default"
if [ -n "${CODEX_ARCHITECT_REVIEW_MODEL:-}" ]; then
  codex_architect_model_source="env:CODEX_ARCHITECT_REVIEW_MODEL"
elif [ -n "${CODEX_FALLBACK_MODEL:-}" ]; then
  codex_architect_model_source="env:CODEX_FALLBACK_MODEL"
elif [ -n "${OMX_DEFAULT_FRONTIER_MODEL:-}" ]; then
  codex_architect_model_source="env:OMX_DEFAULT_FRONTIER_MODEL"
fi

codex_test_model="$(first_nonempty \
  "${CODEX_TEST_REVIEW_MODEL:-}" \
  "${CODEX_FALLBACK_MODEL:-}" \
  "${OMX_DEFAULT_FRONTIER_MODEL:-}")"
codex_test_model_source="default"
if [ -n "${CODEX_TEST_REVIEW_MODEL:-}" ]; then
  codex_test_model_source="env:CODEX_TEST_REVIEW_MODEL"
elif [ -n "${CODEX_FALLBACK_MODEL:-}" ]; then
  codex_test_model_source="env:CODEX_FALLBACK_MODEL"
elif [ -n "${OMX_DEFAULT_FRONTIER_MODEL:-}" ]; then
  codex_test_model_source="env:OMX_DEFAULT_FRONTIER_MODEL"
fi

if [ "${claude_supports_model}" -ne 1 ]; then
  claude_review_model=""
  claude_review_model_source="unsupported"
fi

if [ "${gemini_supports_model}" -ne 1 ]; then
  gemini_review_model=""
  gemini_review_model_source="unsupported"
fi

if [ "${codex_supports_model}" -ne 1 ]; then
  codex_architect_model=""
  codex_architect_model_source="unsupported"
  codex_test_model=""
  codex_test_model_source="unsupported"
fi

: > "${ENV_OUT}"
write_env "AI_MODEL_ROUTING_DISCOVERED_AT" "$(date -Iseconds)"
write_env "AI_MODEL_ROUTING_REPORT" "${REPORT_OUT}"
write_env "CLAUDE_REVIEW_MODEL" "${claude_review_model}"
write_env "CLAUDE_REVIEW_MODEL_SOURCE" "${claude_review_model_source}"
write_env "GEMINI_REVIEW_MODEL" "${gemini_review_model}"
write_env "GEMINI_REVIEW_MODEL_SOURCE" "${gemini_review_model_source}"
write_env "CODEX_ARCHITECT_REVIEW_MODEL" "${codex_architect_model}"
write_env "CODEX_ARCHITECT_REVIEW_MODEL_SOURCE" "${codex_architect_model_source}"
write_env "CODEX_TEST_REVIEW_MODEL" "${codex_test_model}"
write_env "CODEX_TEST_REVIEW_MODEL_SOURCE" "${codex_test_model_source}"

cat > "${REPORT_OUT}" <<REPORT
# AI Model Routing Inventory

Generated at: $(date -Iseconds)

## Discovery Policy

- Prefer explicit environment overrides.
- Prefer provider aliases that the installed CLI advertises, such as Claude's latest-model aliases.
- Do not hardcode dated provider model names in workflow scripts.
- Fall back to the provider CLI default when no safe model list or alias is available.

## CLI Capabilities

| Provider | Version | Supports --model | Discovered aliases |
|---|---|---:|---|
| Claude | $(command_version claude) | ${claude_supports_model} | ${claude_aliases[*]:-none} |
| Gemini | $(command_version gemini) | ${gemini_supports_model} | none exposed by help |
| Codex exec | $(command_version codex) | ${codex_supports_model} | use env/OMX model contract |

## Selected Review Models

| Lane | Model | Source |
|---|---|---|
| Claude review | ${claude_review_model:-provider-default} | ${claude_review_model_source} |
| Gemini review | ${gemini_review_model:-provider-default} | ${gemini_review_model_source} |
| Codex architect fallback | ${codex_architect_model:-provider-default} | ${codex_architect_model_source} |
| Codex test fallback | ${codex_test_model:-provider-default} | ${codex_test_model_source} |

## Override Variables

- CLAUDE_REVIEW_MODEL
- GEMINI_REVIEW_MODEL
- CODEX_ARCHITECT_REVIEW_MODEL
- CODEX_TEST_REVIEW_MODEL
- CODEX_FALLBACK_MODEL
- OMX_DEFAULT_FRONTIER_MODEL
REPORT

echo "${ENV_OUT}"
