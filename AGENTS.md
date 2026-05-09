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
