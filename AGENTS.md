# Project ZURINI Agent Instructions

PROJECT_ZURINI is a development repository for rebuilding an automated trading
system from the strategy stage.

The `(old)/` directory is preserved as past-history reference material. Do not
rewrite or delete those files unless the user explicitly asks for archival
cleanup.

The `references/api/` directory is the vault for uploaded API reference
materials. Keep API documents there until a later task promotes specific
contracts into current docs, config, code, or tests. Do not store secrets,
account identifiers, API keys, tokens, or credentials in this repository.
If credentials are provided in conversation, treat them as exposed, do not echo
or persist the values, and record only placeholder environment-variable names.

For phase-1 development, use `(old)/` as the starting baseline for trading
conditions, strategy rules, risk controls, system sequence, and architecture
decisions. Extract current implementation requirements from those files into
new docs or code instead of editing the archived originals directly.

This baseline is not absolute. During phase-1 work, direction may change when
tests, schema design, implementation constraints, or user decisions show a
better path. Record the reason in `docs/` before changing direction.

There is no executable trading engine in the repository yet.

## Current Phase

Phase 1 ends at a reproducible local backtest.

Target:

- Python-based automated-trading system foundation
- local personal PC execution
- Docker Compose Postgres as the phase-1 database
- standard 1-minute-bar DB schema and data contract
- deterministic dummy 1-minute-bar data
- schema/data validator
- at least one simple strategy that can run through the backtest framework
- minimal reproducible backtest report
- initial trading conditions, sequence, and risk rules derived from `(old)/`

Phase 1 is not trying to prove that a strategy is profitable. It is building the
framework that lets future strategies be tested repeatedly and safely.

## Scope Rules

Allowed without a new plan:

- phase-1 documentation under `docs/`
- Python project scaffolding for data contracts, dummy data, validation, and
  backtesting
- Docker Compose Postgres setup for local development and tests
- pytest tests for schema validation, deterministic fixtures, and backtest smoke
  behavior
- verification script improvements
- narrow automation reliability fixes
- user-approved phase-2 raw market-data staging under `sample/collect_yearly/`,
  limited to historical market data and metadata collection
- user-approved phase-2 dry-run infrastructure for KIS read-only market-data
  smoke checks, limited to token issuance and domestic quote reads for universe
  construction, and only when the CLI requires explicit production read-only
  acknowledgement; this does not allow orders, account reads, balance reads,
  paper/live execution, or real-fill/slippage measurement
  Operational deployment must use preconfigured read-only network/auth
  permissions and preflight checks, not interactive ad hoc permission grants.
- user-approved phase-2 dry-run news/DART/RSS risk-defense collection, limited
  to explicit local files, external read-only HTTPS URL fetches, or local
  loopback HTTP smoke sources for async blacklist artifacts, and only when both
  CLI-level and library-level network gates are explicit; this does not allow
  credentialed news APIs, broker calls, KIS calls, order-decision-path network
  calls, account reads, balance reads, or storage of raw proprietary/customer
  data

Not allowed without an explicit new plan:

- live trading code that can place real orders
- broker API integration
- API keys, account numbers, credentials, or secret handling
- paper trading that connects to an external broker
- broker actions beyond historical market-data reads, including order placement,
  account actions, or live/paper execution
- production server deployment or cloud infrastructure
- strategy-parameter hardcoding as a final trading recommendation
- destructive storage changes outside disposable local test databases
- new dependencies unrelated to phase-1 backtest infrastructure

## Required Operating Input Contract

No operating workflow may continue in best-effort, reduced, restricted, or
partial mode when a required operating input is missing, stale, incomplete, or
contract-invalid. Required inputs must be collected, rebuilt, or rejected before
the workflow advances to universe selection, scenario execution, field dry-run
monitoring, review promotion, or any field-start approval claim.

This rule applies to every required operating input, including market-data
reports, API payload reports, source freshness, schema contracts, universe source
history, blacklist/news/risk-defense inputs when enabled, and future readiness
signals. A command may explicitly run in analysis-only mode, but it must label
the output as non-operational evidence and must not present the result as a
valid dry-run, readiness, promotion, or field-start artifact.

The default failure shape is fail-closed:

- return a non-zero status for operational commands
- write a status artifact that records the blocking input flags
- do not execute downstream scenarios or selection steps that depend on the
  invalid input
- do not silently substitute defaults, cached artifacts, narrower symbol sets,
  slower cadence, or stale snapshots unless a documented command option defines
  the run as analysis-only

Universe source readiness specifically requires 60 prior trading days before
field universe selection unless a test fixture or explicitly analysis-only
command narrows the threshold and labels the output accordingly.

## External API Permission Baseline

Operational external API checks, including KIS read-only market-data collection,
must run through the preapproved real-network execution path rather than the
default sandbox network path. If a sandboxed probe reports connection refusal,
timeout, DNS failure, or auth cooldown while a real-network retry succeeds,
classify the first result as sandbox permission noise, not provider instability.
Record the distinction in the run evidence before drawing conclusions about the
user network or the upstream API.

## Phase-1 Quality Bar

Be strict about framework quality:

- reproducible commands
- deterministic dummy data generation
- explicit 1-minute-bar schema contract
- DB constraints that protect data shape
- validator failures for invalid data
- tests that explain what broke
- no real broker calls, real orders, or secrets

Be flexible about strategy details:

- universe filters
- entry/exit thresholds
- stop/take-profit numbers
- fee and slippage assumptions
- detailed report metrics
- table/module names when a clearer design emerges

When strategy details are needed for the first implementation pass, start from
the archived trading plans and diagrams in `(old)/`. If a detail is ambiguous or
conflicting across old files, document the chosen interpretation in `docs/`
before coding. If implementation evidence suggests a better direction, update
the current docs and tests instead of treating the archived files as immutable
requirements.

## Local Hardware-Aware Parallelism

This project is developed on a local personal PC. As of 2026-05-10, observed
hardware is Lenovo 83HF, Intel i5-13420H, 16 GB RAM, integrated graphics, and a
238 GB C: drive with limited free space. WSL is the normal execution surface and
has shown instability when Ralph/tmux/subagent work is too concurrent.

Adjust agent and reviewer parallelism to the current workload and machine
health:

- Default to solo execution or at most 1-2 concurrent subagents for normal
  coding, verification, strategy analysis, and review loops.
- Use 3+ parallel lanes only for short, read-only, clearly independent lookups
  when WSL/tmux is healthy and no heavy local tests, Docker/Postgres work, or
  external review loop is already running.
- Do not stack heavyweight operations casually: full `./scripts/verify.sh`,
  `./scripts/review-gate.sh`, Docker Compose/Postgres, broad report scans, and
  multiple Codex subagents should be sequenced or capped.
- If the PC becomes sluggish, WSL reports vsock/socket errors, tmux reports
  `target_not_found`, or Ubuntu terminals repeatedly fail to open, immediately
  reduce to solo mode, checkpoint the current state, stop spawning new
  subagents, and prefer small targeted verification.
- Treat hardware pressure as an operational constraint, not a reason to skip
  verification. Use narrower tests first, then run the required full
  verification when the environment is stable.

## Stage Transition Checkpoints

For long-running Ralph, team, review, strategy-analysis, data-rehearsal, or
multi-phase automation work, persist progress whenever the work advances to a
new stage. Treat these checkpoints as a recovery safety net for forced session
loss, WSL/tmux crashes, terminal closure, PC reboot, or context compaction. Use
`.omx/context/`, `.omx/notepad.md`, project memory, or the available checkpoint
helper, depending on the active workflow.

Each checkpoint should be compact and resumable:

- current stage and stop condition
- completed evidence and verification status
- pending next action
- active constraints and safety boundaries
- changed files or expected write scope
- blockers, degraded reviewer state, or environment warnings
- recovery instruction for resuming after WSL, tmux, terminal, or PC
  interruption

Do not wait until the end of a long run to record state. A new agent should be
able to recover the last safe stage from checkpoints without relying on the
lost conversation. Stage checkpoints are part of safe local operation on this
hardware.

## Plan Document Index Policy

For multi-document plans, maintain one current index document as the first
navigation surface. The index should name the active status, immediate next
actions, weekend or later work queues, promotion/fallback gates, and links to
the detailed contract documents.

When adding, splitting, or updating plan material:

- update the index first or in the same change;
- keep detailed matrices, readiness contracts, and runbooks in separate
  documents linked from the index;
- do not duplicate full criteria across multiple plan files when a link to the
  source-of-truth document is enough;
- if a user asks where the plan is stored, answer from the index and then cite
  detailed documents;
- if a plan lacks an index, create or designate one before expanding the plan.

At the end of any long-running Ralph, team, review-gate, strategy-analysis,
data-rehearsal, dry-run, or multi-stage automation task, reconcile the current
index before claiming completion:

- inspect whether completed work, blockers, verification evidence, review-gate
  status, immediate next actions, promotion/fallback gates, or operating-input
  status changed;
- if any of those changed, update the index in the same change as the work or
  before the final report;
- if nothing changed, explicitly record "index unchanged" with the reason in
  the checkpoint or final report;
- treat generated checkpoints as recovery evidence, not as a replacement for
  the index source of truth;
- final reports for these workflows must say whether the index was updated,
  unchanged, or not applicable.

Current Plan A tracking index:

- `docs/plan-a-next-actions.md`

## Pre-Dry-Run Module Freeze

This freeze starts after the current user-approved pre-dry-run infrastructure
slice is verified. Until the first no-order field dry-run is complete and
reviewed, do not add new CLI command groups or broaden the large dry-run
modules. Treat the current `src/zurini/cli.py` and `src/zurini/dry_run.py` size
as an accepted short-lived maintenance risk only for the already-planned
no-order dry-run. New behavior must go through the weekend module split first
unless it fixes a verified dry-run blocker.

KIS auth cooldown state under `.omx/state/kis-auth-cooldown.json` is operational
runtime state, not disposable review metadata. Do not delete or rewrite it
during artifact cleanup unless the active task is explicitly resetting KIS auth
cooldown behavior.

Before broadening operational dry-run behavior, list plausible failure modes and
map existing defenses first. Defer live/read-only chaos-style tests until the
affected modules are split, verified, and the explicit test scope is approved.

## Required References

- `docs/WORKFLOW.md`
- `docs/AUTOMATION_OPERATING_POLICY.md`
- `docs/AI_MODEL_ROUTING.md`
- `docs/SESSION_QUALITY_PLAN.md`
- `docs/DATA_COMPLETION.md`
- `docs/DEPLOYMENT_COMPLETION.md`
- `docs/OBSERVABILITY_COMPLETION.md`
- `docs/PERFORMANCE_COMPLETION.md`
- `docs/SECURITY_COMPLETION.md`
- `docs/UI_COMPLETION.md`
- `docs/phase-1-development.md`
- `docs/phase-1-prd.md`
- `docs/phase-1-test-spec.md`
- `scripts/verify.sh`
- `scripts/review-gate.sh`
- `(old)/` as the phase-1 starting baseline for trading conditions, sequence,
  risk controls, and architecture

## Verification Rule

Before claiming a task is complete, run:

```bash
./scripts/verify.sh
```

Before presenting a commit candidate, run:

```bash
./scripts/review-gate.sh
```

If `./scripts/verify.sh` fails, the task is not complete.
If `./scripts/review-gate.sh` fails or returns a decision other than `proceed`
or `proceed_degraded`, do not present the change as ready to commit.

`proceed_degraded` may continue only when the degraded trust level and missing
reviewer state are reported clearly.

## Automation Template Merge Policy

This repository uses the AI_AUTO automation base as a source for reusable
automation, not as an overwrite authority. Preserve PROJECT_ZURINI rules first.

When refreshing automation:

- inspect existing `AGENTS.md`, `docs/WORKFLOW.md`, and `scripts/verify.sh`
  before changing anything
- do not overwrite project-specific guidance, secret rules, data boundaries,
  trading phase boundaries, or verification commands
- add only missing reusable automation files, helper scripts, or policy
  references that do not conflict with this project
- keep Odoo, branch, or unrelated environment rules out of this repository
  unless they are explicitly PROJECT_ZURINI rules
- deployment, performance, and observability completion packs are in scope as
  interview-backed preparation for field-test-to-live operation; keep them
  subordinate to PROJECT_ZURINI trading, data, and secret boundaries
- UI completion is in scope as an operator dashboard, but implementation must
  start from an AI proposal and user confirmation. Keep live-order controls
  locked unless the user explicitly approves enabling them.
- resolve conflicts in favor of project-local instructions
- run `./scripts/automation-doctor.sh`, `./scripts/verify.sh`, and when a commit
  candidate is involved `./scripts/review-gate.sh`

## Completion Report Format

When reporting completion, include:

- changed files
- diff summary
- verification command
- verification result
- review-gate result when a commit candidate is involved
- known warnings or limitations
