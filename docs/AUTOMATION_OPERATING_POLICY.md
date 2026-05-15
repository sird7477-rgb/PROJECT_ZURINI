# Automation Operating Policy

This document defines the reusable default policy for AI review intensity and
failure-pattern feedback. Project onboarding should copy the defaults, then tune
them to the target project's risk level.

## Review Intensity

Default mode: `standard`.

Use one of these project policies during onboarding:

| Mode | Use When | Required Gate |
| --- | --- | --- |
| `lightweight` | Documentation-only, local-only, or very small reversible changes | `./scripts/verify.sh`; run `review-gate` only for risky or shared automation changes |
| `standard` | Normal application or automation work | `./scripts/verify.sh`; run `review-gate` before commit candidates when behavior, workflow, data, deployment, security, or shared scripts change |
| `strict` | Finance, production deployment, auth/security, destructive data, regulated workflow, or high-blast-radius automation | `./scripts/verify.sh` and `./scripts/review-gate.sh` before every commit candidate |

Escalate one level when:

- the change touches shared automation, review routing, model routing, or
  verification scripts
- the change affects data persistence, migrations, deployment, credentials,
  security boundaries, or user-visible workflows
- prior verification or review failed on the same task
- the agent is making assumptions that materially affect behavior

De-escalate one level only when all are true:

- the change is documentation-only or a small local maintenance edit
- `./scripts/verify.sh` proves the relevant behavior
- no external reviewer or domain-specific judgment is needed
- the completion report explicitly states that `review-gate` was intentionally
  skipped under the project's review-intensity policy

## Advisory Reviewer Sessions

External reviewers may be kept open during local development only as an
advisory optimization. This is useful for repeated small iterations where a
human or agent wants fast feedback before the final gate.

Rules:

- Treat warm reviewer sessions as advisory only, not as commit-candidate
  approval.
- Clear the reviewer context before each advisory request when the CLI supports
  it, for example with `/clear`.
- Send a compact prompt or changed-file summary rather than the full review
  context whenever possible.
- Save any useful advisory finding in the work notes, diff, or feedback queue;
  do not rely on hidden reviewer session memory as evidence.
- Run the normal stateless `./scripts/review-gate.sh` for final commit-candidate
  judgment whenever the project's review-intensity policy requires it.

The final gate remains stateless because `review-gate` writes review context,
prompts, manifests, outputs, disabled reviewer state, and summaries as
reproducible artifacts. A warm session with `/clear` can reduce iteration cost,
but it does not replace those artifacts.

## Failure-Pattern Feedback

Record a feedback item when it has reuse value, not for every transient mistake.

Record when any of these are true:

- the same repeat key appears 2 or more times
- a failure blocks verify, review, commit, push, deploy, or onboarding
- manual user intervention was required
- an AI made a wrong assumption that caused rework
- a project-local fix should become an AI_AUTO template improvement

Do not record:

- secrets, credentials, tokens, customer data, private logs, or copied stack
  traces that contain sensitive context
- one-off typos with no reuse value
- speculative ideas that were not accepted as future guidance
- raw generated output when a short symptom/cause/resolution summary is enough

Use:

```bash
./scripts/record-feedback.sh \
  --type failure_pattern \
  --repeat-key git:index-lock-permission \
  --summary ".git/index.lock permission denied during commit" \
  --resolution "Use the approved escalated git commit path in this environment" \
  --severity medium
```

Feedback is written to `.omx/feedback/queue.jsonl`. `.omx/` is ignored by git,
so raw project feedback stays local by default.

When a feedback item has been handled, mark it instead of deleting it:

```bash
./scripts/resolve-feedback.sh \
  --repeat-key git:index-lock-permission \
  --note "Template guidance updated"
```

Use `status=resolved` for accepted and completed work, `ignored` for items that
were reviewed and intentionally rejected, and `deferred` when the item remains
valid but is not in the current implementation scope. Missing status on older
queue entries is treated as `open`.

## Required Input Fail-Closed Policy

Automation must not treat required operating inputs as optional once a workflow
claims operational readiness, dry-run validity, promotion readiness, or field
start evidence. Missing, stale, incomplete, or contract-invalid required inputs
must stop the operational path before downstream execution.

Fail-closed means:

- return a failing/non-ready status for the operational command
- preserve the blocking reason in a machine-readable artifact
- skip dependent execution that would make the output look valid
- avoid hidden substitutions such as stale cache reuse, narrowed scope, reduced
  cadence, placeholder defaults, or "restricted mode" unless the command is
  explicitly analysis-only

Analysis-only runs are allowed for diagnostics and fixtures, but their artifacts
must not be promoted as operational evidence.

## Subagent Utilization

The leader owns scope, integration, final verification, and user-facing claims.
Use subagents only when a bounded lane can improve speed, quality, or risk
coverage without blocking the immediate next step.

Good subagent lanes:

- repo lookup and symbol mapping
- focused implementation slices with disjoint write ownership
- test strategy or verification review
- UX/design review for UI work
- dependency or official-doc research
- independent critique of a plan or risky diff

Do not delegate:

- destructive actions, credentialed operations, production deploys, or commits
  and pushes
- ambiguous scope decisions that require user judgment
- the final integration decision or completion claim
- work that would duplicate the leader's immediate critical path

External reviewers such as Claude and Gemini do not directly control Codex
native subagents. They may recommend subagent follow-ups, but the leader decides
whether to spawn them, assigns a narrow task, and reports the result. When an
external reviewer is disabled, Codex fallback review lanes may cover the missing
perspective, but this remains degraded informational coverage and must be
reported as such.

Prefer role selection and reasoning effort over hardcoded model overrides.
Inherit the current runtime model unless a concrete, current runtime-supported
reason exists to override it.

### Hardware-Aware Parallelism

Tune subagent and reviewer parallelism to the local machine, current workload,
and WSL/tmux health. PROJECT_ZURINI currently runs on a 16 GB RAM Windows/WSL
personal PC, so the default concurrency budget is intentionally conservative.

Use this operating budget unless the user explicitly approves a heavier run:

| Workload | Default Parallelism | Notes |
| --- | --- | --- |
| Simple lookup or documentation edit | solo, or 1 short read-only subagent | Keep the leader on the critical path. |
| Normal code/test work | solo to 2 concurrent lanes | Use targeted tests before full verification. |
| Strategy analysis, report scans, or review loops | 1-2 concurrent lanes | Avoid stacking with Docker/Postgres or full review-gate. |
| Heavy verify/review/Docker work | sequential by default | Run broad checks after the environment is stable. |

Reduce to solo mode and checkpoint immediately when the PC becomes sluggish,
WSL reports vsock/socket errors, tmux reports `target_not_found`, or Ubuntu
terminals repeatedly fail to launch. Hardware pressure changes scheduling, not
the verification requirement.

### Stage Transition Checkpoints

Long-running automation must leave resumable state behind as it moves through
stages. This applies to Ralph, team, strategy-analysis, data-rehearsal, review,
and multi-phase implementation loops. The primary purpose is recovery after
forced session loss: WSL/tmux crashes, terminal closure, PC reboot, context
compaction, or other interruption where the previous conversation cannot be
trusted as the only state store.

Record a compact checkpoint at each stage transition:

- current stage, target result, and stop condition
- completed evidence and verification result
- pending next action
- active constraints, safety boundaries, and non-goals
- changed files or expected write scope
- reviewer state, degraded trust, blockers, and environment warnings
- recovery instructions for WSL, tmux, terminal, or PC interruption

Use the narrowest durable surface available: `.omx/context/` for handoffs,
`.omx/notepad.md` for session notes, project memory for reusable facts, or the
checkpoint helper when the workflow provides one. Do not defer all state capture
until final completion. A replacement agent should be able to resume from the
latest checkpoint without replaying the lost session.

## Planning And Interview Escalation

Default posture: act directly when the request is clear, narrow, and reversible.
Do not interview for routine edits, small fixes, local documentation updates,
or commands the user already requested.

Escalate to a short interview when one decision would materially change the
result. Ask one concise question, then proceed from the answer.

Escalate to a plan-first interview when the task involves any of these:

- broad words such as foundation, standard, strategy, architecture, workflow,
  policy, automation, onboarding, or hardening
- long-lived guidance files such as `AGENTS.md`, `docs/WORKFLOW.md`,
  `scripts/verify.sh`, templates, completion packs, or domain packs
- multiple valid approaches with different cost, safety, or maintenance impact
- data loss, security, credentials, deployment, production, billing, or
  irreversible behavior
- unclear success criteria, unknown users, or final deliverables that cannot be
  inferred from local evidence
- a user explicitly asks for recommendation, review, discussion, interview,
  planning, or "don't assume"

Use this intensity scale:

| Intensity | Use When | Expected Behavior |
| --- | --- | --- |
| `none` | Small, clear, reversible task | Execute, verify, report |
| `light` | One material branch or missing fact | Ask one question, then execute |
| `standard` | Several choices shape the outcome | Inspect evidence, ask 2-4 focused questions, write a short plan, then execute |
| `deep` | High-risk, long-lived, or strategic work | Run a staged interview, produce a plan/test shape, optionally request reviewer/subagent critique, then execute only the approved/safe slice |

When interviewing, first inspect local files and ask only for facts that cannot
be inferred safely. Label assumptions explicitly. If the user says "바로 진행",
skip interview only for safe and reversible work; keep approval gates for
destructive, credentialed, production, or materially scope-changing actions.

## Onboarding Interview Structure

After `aiinit`, interview before feature work. Keep the interview short but
complete enough to replace the template placeholders with project-specific
rules.

Use this order:

1. Existing evidence: read README, docs, package files, scripts, and old notes
   before asking.
2. Outcome: purpose, users, final deliverable, and non-goals.
3. Scope and safety: allowed changes, forbidden changes, data/secret/credential
   boundaries, and destructive-operation rules.
4. Stack and commands: runtime, setup, test, build, lint, smoke, and deploy
   commands.
5. Completion packs: select or reject UI, deployment, security, data,
   performance, and observability packs.
6. Domain packs: select or reject installed `.omx/domain-packs/` references.
7. Operating policy: review intensity, feedback recording, approval-friction
   handling, and subagent usage expectations.
8. Verification contract: exact `scripts/verify.sh` checks and evidence needed
   before claiming completion.
9. Decision record: write confirmed rules into `AGENTS.md`, `docs/WORKFLOW.md`,
   and `scripts/verify.sh`; record rejected packs as non-goals.

Ask only for information that cannot be inferred safely from local evidence.
When proceeding from an assumption, label it as an assumption and keep the
change reversible.

## Promotion Policy

AI_AUTO may later collect project feedback queues and promote only sanitized,
generalizable patterns into versioned guidance.

Promotion targets:

- repeated environment failures -> `docs/WORKFLOW.md`, `AGENTS.md`, or doctor
  diagnostics
- repeated onboarding gaps -> template onboarding interview guidance
- repeated verification gaps -> template `scripts/verify.sh` or completion packs
- repeated review noise -> review-intensity policy adjustments

Do not promote raw project logs. Promote a short pattern with:

- repeat key
- symptom
- likely cause
- safe resolution
- affected surface
- confidence
- evidence count

SQLite or another database may be added later as a local search/index cache, but
the source of truth should remain reviewable text files (`jsonl` and markdown)
so changes can be diffed, reviewed, committed, and distributed through git.

## Approval Friction

Do not bypass safety approval for destructive, credentialed, external-production,
or materially scope-changing actions. Reduce approval friction by making common
safe paths explicit and repeatable.

Preferred order:

1. Use repo-owned helper scripts for safe repeated operations.
2. Use narrow approved command prefixes for non-destructive recurring commands
   such as verification, review gate, helper installation, commit, and push.
3. Use preflight checks (`automation-doctor`, `workspace-scan`, `git status`) to
   find permission or environment blockers before long work starts.
4. Use `REVIEW_EXECUTION_MODE=external` only when the agent runtime cannot access
   reviewer CLIs but the user's interactive terminal can.
5. Record repeated permission blockers as feedback patterns instead of silently
   retrying the same failing command.

Still require explicit approval for:

- deleting data, resetting git state, overwriting project instructions, or
  removing user files
- installing dependencies or external programs
- using credentials, production SSH, deployment targets, or paid external APIs
- changing permission boundaries rather than using an approved narrow command
  path
