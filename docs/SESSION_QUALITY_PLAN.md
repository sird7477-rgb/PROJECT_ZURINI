# Session Quality Plan

This is the draft operating plan for long-running AI automation sessions.

The goal is to keep model routing stable, preserve important working memory,
and reduce quality drift as token usage and session length grow.

## Scope

This plan covers:

- model routing cache and refresh behavior
- working memory capture during tasks
- long-session quality controls
- handoff/resume checkpoints

It does not change production behavior by itself. Scripts should implement this
plan incrementally.

## 1. Model Routing Cache

Model routing should be discovered once per session or first AI-review run, then
reused while the session remains coherent.

Implemented/default behavior:

1. If `.omx/model-routing/latest.env` and `.omx/model-routing/latest.md` exist
   and are fresh enough, reuse them.
2. If no cache exists, run `scripts/discover-ai-models.sh`.
3. If `AI_MODEL_DISCOVERY_REFRESH=1`, ignore the cache and rediscover.
4. If `AI_MODEL_DISCOVERY=0`, skip discovery and use provider defaults.
5. Reuse cache only when the role/model override fingerprint matches.
6. If a role/model override changes, bypass cache and write a new routing
   snapshot for that override.
7. If Claude, Gemini, or Codex CLI version/help output changes, bypass cache
   and write a new routing snapshot.

Recommended freshness policy:

- default TTL: 12 hours, implemented as `AI_MODEL_ROUTING_TTL_SECONDS=43200`
- hard stale warning: 24 hours
- always refresh after CLI upgrade, provider login change, or reviewer reset

The routing snapshot should record:

- discovery timestamp
- CLI versions
- `--model` support per provider
- discovered aliases
- selected role/model/source
- whether each selection is `env`, `inferred`, `default`, or `unsupported`
- cache age when used by a review run

Important rule:

Model routing cache and reviewer availability are separate. A reviewer may have
a valid routing candidate but still be skipped because `.omx/reviewer-state`
marks it disabled.

Leader routing is also separate from delegated routing. The active Codex/GPT
leader should be treated as runtime-selected for the session; cost and latency
optimization should be done by routing bounded work to child agents or OMX lanes
with explicit role, reasoning, and trust boundaries.

## 2. Working Memory

Status: active guidance with a repo helper. Use
`scripts/record-project-memory.sh` for sanitized durable entries.

Working memory should capture durable decisions, not every intermediate thought.

Use three layers:

| Layer | File | Purpose |
|---|---|---|
| Project memory | `.omx/project-memory.json` | durable cross-session decisions and user preferences |
| Current state | `docs/CURRENT_STATE.md` | human-readable repo status and known issues |
| Session checkpoint | `.omx/state/session-checkpoint.md` | active plan progress, current step, and continue/escalate decision |
| Run artifacts | `.omx/review-results/review-run-*.md` | per-run evidence and links |

Record a memory item when one of these happens:

- the user establishes a standing preference
- a workflow decision should survive a new session
- an external constraint affects future work
- a reviewer/tool failure changes normal operation
- a project-specific setup rule is learned

Do not store:

- secrets, tokens, private credentials, or copied sensitive logs
- noisy command output that already exists in review artifacts
- speculative ideas that were not accepted
- temporary implementation details with no future value

Memory entry format should include:

- category
- concise content
- timestamp
- source/evidence when available
- optional expiry or revisit condition

Examples:

- `model-routing`: Claude routing uses inferred CLI aliases; refresh after reviewer reset.
- `reviewer-state`: Claude disabled until user resets after session limit.
- `workflow`: Existing initialized projects require merge/upgrade flow, not overwrite.

## 3. Long-Session Quality Controls

Status: active guidance with checkpoint automation. `review-gate` writes
`.omx/state/session-checkpoint.md` after a successful summary unless
`OMX_AUTO_CHECKPOINT=0` is set.

Long sessions should be treated as operational risk. The agent should preserve
quality by checkpointing state and reducing context load.

Recommended checkpoints:

- after each commit or push
- after each completed review-gate run
- after a major plan changes
- after a plan step completes or a search axis fails and the next axis is chosen
- before switching domains, for example generic automation to phase-2 data
  validation
- when the conversation becomes long enough that recent context may crowd out
  original goals

Checkpoint content:

- current objective
- active plan file
- current plan step
- completed steps
- next step or next search axis
- changed files
- completed decisions
- pending decisions
- continue-or-escalate decision and reason
- resource profile and parallelism notes
- latest verification evidence
- reviewer state
- model routing snapshot
- leader/delegated lane ownership and any degraded fallback coverage
- known warnings and blockers

Autonomous continuation rule:

- A failed attempt, empty search result, or "no valid candidate found" checkpoint
  is not a stop condition by itself when the user already delegated the
  objective, boundaries, and decision principles.
- Treat that checkpoint as a pivot point: record the failed axis, choose the
  next reasonable axis, and continue inside the delegated scope.
- Escalate to the user only when the next axis requires a new business
  decision, exceeds the delegated scope, creates destructive/credentialed or
  production risk, hits a configured time/cost/resource limit, or the reasonable
  search space has been exhausted.
- In resource-constrained sessions, such as a host that has previously forced
  Ubuntu/WSL shutdowns or while another heavy review is running, lower
  parallelism before continuing and record that resource profile in the
  checkpoint.

Quality drift triggers:

- repeated restatement of old or already-resolved context
- uncertainty about whether the latest request overrides an older one
- more than one failed review-gate cycle on the same issue
- large uncommitted diff across unrelated concerns
- tool outputs becoming too large to reason about directly
- user asks a strategic question after a long implementation stretch

When a trigger appears, the agent should:

1. stop expanding scope
2. inspect git status and current diff
3. read the latest run manifest/verdict if relevant
4. summarize the active state in 5-10 bullets
5. continue from the newest user request only

## 4. Token And Context Hygiene

Status: active guidance using existing repo/runtime artifacts.

Use compact artifacts instead of carrying raw logs in conversation.

Preferred artifacts:

- `.omx/model-routing/latest.md`
- `.omx/review-results/review-run-*.md`
- `.omx/review-results/review-verdict-*.md`
- `.omx/review-context/latest-review-context.md`
- `docs/CURRENT_STATE.md`

Avoid repeatedly loading:

- all `.omx/review-results/*`
- `.omx/review-results/archive/*` unless investigating a specific historical run
- `.omx/logs/*` unless the current failure requires runtime trace evidence
- large historical logs
- old prompt files unless investigating a specific run
- full provider documentation when local runtime evidence is enough

For long sessions, prefer:

- targeted `rg`
- latest manifest first
- latest verdict first
- docs/current-state first
- exact file reads over repo-wide dumps

Checkpoint hygiene:

- `.omx/state/session-checkpoint.md` should stay a compact resume pointer, not a
  transcript or raw log sink.
- `scripts/write-session-checkpoint.sh` caps `git status --short` output with
  `OMX_SESSION_CHECKPOINT_STATUS_LIMIT` and long field values with
  `OMX_SESSION_CHECKPOINT_FIELD_LIMIT`.
- If a checkpoint points to large evidence, read the linked manifest or verdict
  first, then open only the specific referenced file needed for the current
  question.
- Do not use broad `.omx` reads as a default resume step; explicitly exclude
  archived review artifacts and logs unless they are the target of the
  investigation.

## 5. Resume Protocol

Status: active guidance. The agent performs these reads manually today; a
single resume command is planned.

On resume or after compaction, the agent should recover from repo-native state:

1. `git status --short`
2. `.omx/state/session-checkpoint.md`
3. latest relevant `docs/CURRENT_STATE.md` section
4. latest `.omx/model-routing/latest.md`
5. latest review verdict/manifest if a review was in progress
6. `.omx/project-memory.json` only for durable preferences

The final answer after a resume must answer the newest user request, not an
older task that happened to be active before compaction.

## 6. Implementation Roadmap

Phase 1, documentation and guardrails:

- add this plan
- link it from current-state and AI role docs
- document model cache refresh flags
- Phases 1 and 2 were bundled in the initial implementation to keep the docs
  and script behavior consistent.

Phase 2, model routing cache:

- add `AI_MODEL_DISCOVERY_REFRESH=1` (implemented)
- add `AI_MODEL_ROUTING_TTL_SECONDS` (implemented)
- invalidate cache when CLI version/help output changes (implemented)
- add cache age to review-run output (implemented)
- add cache age to review manifests (implemented)
- warn when the cache is stale

Phase 3, memory helper:

- add a small script to append sanitized memory entries to
  `.omx/project-memory.json` (implemented)
- add categories and optional expiry fields (implemented)
- add doctor checks for malformed memory JSON

Phase 4, quality checkpoints:

- add a command or script that writes `.omx/state/session-checkpoint.md`
  (implemented)
- include git status, latest verification, review state, and routing snapshot
  (implemented)
- reference the checkpoint from review manifests

Phase 5, cleanup and retention:

- archive old review artifacts automatically after successful review-gate runs
  and during `automation-doctor.sh --fix` when retention thresholds are exceeded
  (implemented)
- keep latest manifests, verdicts, summaries, and referenced reviewer files
  active in `.omx/review-results` (implemented)
- never auto-delete evidence during normal review or doctor runs; deletion
  requires explicit `archive-omx-artifacts.sh --delete --confirm-delete`
  (implemented)
