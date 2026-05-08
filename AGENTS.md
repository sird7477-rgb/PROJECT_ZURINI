# Project ZURINI Agent Instructions

PROJECT_ZURINI is a development repository for rebuilding an automated trading
system from the strategy stage.

The `(old)/` directory is preserved as past-history reference material only. Do
not treat those files as the current specification, and do not rewrite or delete
them unless the user explicitly asks for archival cleanup.

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

Not allowed without an explicit new plan:

- live trading code that can place real orders
- broker API integration
- API keys, account numbers, credentials, or secret handling
- paper trading that connects to an external broker
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

## Required References

- `docs/WORKFLOW.md`
- `docs/phase-1-development.md`
- `docs/phase-1-prd.md`
- `docs/phase-1-test-spec.md`
- `scripts/verify.sh`
- `scripts/review-gate.sh`
- `(old)/` for historical reference only

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

## Completion Report Format

When reporting completion, include:

- changed files
- diff summary
- verification command
- verification result
- review-gate result when a commit candidate is involved
- known warnings or limitations
