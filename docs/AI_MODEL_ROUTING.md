# AI Model Routing

AI model routing is role-first and runtime-surface-first.

Do not route work by a dated hardcoded model name. Route work by the role and
capability needed, then resolve that role onto the models or aliases actually
available in the current CLI/runtime/account.

## Precedence

1. Explicit project/run override environment variables.
2. Current local CLI capability and advertised aliases.
3. Current OMX/Codex model contract from the active runtime.
4. Provider default with no explicit model flag.

Provider documentation is reference material only. It is not proof that a local
CLI, login session, account, or Codex runtime can use a specific model.

## Leader vs Delegated Routing

The active Codex/GPT leader is selected by the runtime or user. Do not claim
that the leader changed its own model mid-session unless the runtime provides
explicit evidence of a supported change path.

Cost and latency optimization should happen through bounded delegated lanes:
route lookup, scanning, or lightweight synthesis to role-appropriate child
agents such as `explore`/fast-scan lanes, and keep planning, architecture,
security-sensitive decisions, integration, final verification, and user-facing
completion claims on the leader or stronger reviewer roles.

Default child-agent routing should inherit the current runtime contract. Use an
explicit model override only when a lane has a concrete reason and current
runtime evidence supports that model. Prefer role and `reasoning_effort`
selection over hardcoded model names.

For detailed subagent delegation boundaries, use
`docs/AUTOMATION_OPERATING_POLICY.md` as the source of truth. Native subagents
are throughput and focus lanes, not independent external reviewer coverage.

## Role Profiles

| Role | Target Capability | Default Runtime Mapping |
|---|---|---|
| `architect_review` | deep reasoning, long-context risk review, maintainability judgment | Claude provider default with suggested alias recorded; Codex architect fallback |
| `alternative_review` | independent second opinion, missed cases, simpler alternatives | Gemini provider default unless explicitly configured; Codex test fallback |
| `implementation` | repo-local code edits and test fixes | Codex executor/current runtime default |
| `debug` | logs, reproduction, root cause, regression isolation | Codex debugger/current runtime default |
| `test_review` | verification shape, missing tests, failure modes | Codex test-engineer plus Gemini when available |
| `fast_scan` | file/symbol lookup and lightweight synthesis | Codex explore/spark lane |
| `docs` | documentation and handoff clarity | Codex writer or provider default |

## Current Review Lanes

`scripts/discover-ai-models.sh` writes `.omx/model-routing/latest.env` and
`.omx/model-routing/latest.md` before review execution. The discovery result is
cached for a session-scale TTL so repeated review runs do not churn model
selection without an explicit reason.

The current review lanes are:

- Claude: `architect_review`
- Gemini: `alternative_review`
- Codex architect fallback: `architect_fallback`
- Codex test fallback: `test_alternative`

Codex/GPT fallback lanes are delegated review artifacts for continuity when an
external reviewer is disabled. They are not independent Claude/Gemini coverage
and must be reported as degraded or informational when used.

Claude stays on provider default by default. Discovery records the suggested
alias for the role when the installed CLI advertises one, but it does not pass a
Claude `--model` flag unless `CLAUDE_REVIEW_MODEL` is set explicitly or
`CLAUDE_REVIEW_MODEL_AUTO=1` is used for that run. This avoids turning a
session-local alias guess into a default that can amplify timeout or quota
issues.

Gemini stays on provider default unless a project/run override supplies a model,
because the local CLI may not expose a reliable model inventory through help
text.

Codex fallback prefers the current OMX/Codex runtime contract or explicit
override variables instead of public API model names.

## Overrides

Use these only when the current project has a concrete reason to force routing:

- `CLAUDE_REVIEW_ROLE`
- `GEMINI_REVIEW_ROLE`
- `CODEX_ARCHITECT_REVIEW_ROLE`
- `CODEX_TEST_REVIEW_ROLE`
- `CLAUDE_REVIEW_MODEL`
- `CLAUDE_REVIEW_MODEL_AUTO=1`
- `GEMINI_REVIEW_MODEL`
- `CODEX_ARCHITECT_REVIEW_MODEL`
- `CODEX_TEST_REVIEW_MODEL`
- `CODEX_FALLBACK_MODEL`
- `OMX_DEFAULT_FRONTIER_MODEL`

Set `AI_MODEL_DISCOVERY=0` to skip model discovery and use provider defaults.

Discovery also writes output-only variables such as
`CLAUDE_REVIEW_SUGGESTED_MODEL` and `AI_MODEL_ROUTING_OBSERVATIONS_STATUS`.
Do not set those as overrides; treat them as evidence for reports and tuning.

## Cache And Refresh

Default behavior:

- reuse `.omx/model-routing/latest.env` and `.omx/model-routing/latest.md` when
  they exist and are within `AI_MODEL_ROUTING_TTL_SECONDS`
- default TTL: `43200` seconds, 12 hours
- refresh immediately with `AI_MODEL_DISCOVERY_REFRESH=1`
- reuse cache only when the role/model override fingerprint matches
- bypass cache automatically when a role/model override changes
- bypass cache automatically when Claude, Gemini, or Codex CLI version/help
  output changes

Examples:

```bash
./scripts/review-gate.sh
AI_MODEL_DISCOVERY_REFRESH=1 ./scripts/review-gate.sh
AI_MODEL_ROUTING_TTL_SECONDS=86400 ./scripts/review-gate.sh
AI_MODEL_DISCOVERY=0 ./scripts/review-gate.sh
```

The routing report records cache status, discovery epoch, TTL, selected roles,
selected models, suggested Claude model, observation-log status, and source
labels.

The routing script also appends refreshed selections to
`.omx/model-routing/observations.tsv`. Treat this as operational evidence for
future tuning: adjust role selectors only after repeated local runs show that a
provider alias or default is consistently better for that lane. Do not change
defaults from a single provider announcement or one-off failure. The TSV is
capped to its header plus the latest 1000 rows.

## Uncertainty Rule

If a model choice is inferred from CLI help, local config, aliases, or current
runtime metadata, report it as suggested or inferred. Do not present it as a
verified provider fact.

If model availability is unclear, say so directly and fall back to provider
default or an explicit user override. Do not invent a model name and do not
claim that a model is available unless the current runtime or the user provided
evidence.
