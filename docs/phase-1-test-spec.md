# Phase 1 Test Spec

## Purpose

Define the minimum verification suite for the phase-1 local backtest foundation.
The suite should make the framework reproducible without depending on real
market data.

## Verification Command

The project-level command remains:

```bash
./scripts/verify.sh
```

Once phase-1 implementation begins, this command must run the relevant pytest
suite and Docker Compose Postgres checks.

## Test Groups

### 1. Automation Baseline

Required now and throughout phase 1:

- `scripts/test-review-summary.sh` passes.
- `DOCTOR_SKIP_DIRTY_CHECK=1 ./scripts/automation-doctor.sh` passes without
  failures.
- shell scripts required by the workflow are executable in the working tree and
  git index.

### 2. Documentation Contract

Required now and throughout phase 1:

- `AGENTS.md` defines `(old)/` as historical reference only.
- `docs/WORKFLOW.md` defines the phase-1 target as reproducible local backtest.
- `docs/phase-1-development.md` exists.
- `docs/phase-1-prd.md` exists.
- `docs/phase-1-test-spec.md` exists.
- docs state that phase-1 trading conditions, sequence, risk controls, and
  architecture start from `(old)/`.
- docs state that `(old)/` is a starting baseline, not an absolute constraint.

### 2a. Old-Document Baseline Checks

Required now and throughout phase 1:

- archived strategy plan exists.
- archived final/high-level strategy plan exists.
- archived flow chart exists.
- archived sequence diagram exists.
- archived integrated architecture document exists.
- verification anchors cover representative old-document concepts:
  - trading strategy
  - global beta throttling
  - IOC emergency exit
  - async blacklist sequence
  - Universal Quant Core
- direction changes from old-document assumptions must be documented in current
  docs before implementation depends on them.

### 3. Postgres Availability

Required once implementation starts:

- `docker compose up -d db` starts Postgres.
- DB healthcheck passes.
- tests can connect using local test credentials.
- test setup can reset or recreate disposable schema state.

### 4. Schema Tests

Required once implementation starts:

- schema creation succeeds from a clean DB.
- `symbol + timestamp` uniqueness exists.
- required OHLC columns reject null values.
- check constraints reject invalid OHLC relationships.
- volume and value reject negative values.
- indexes needed by `symbol`, `timestamp` ordered reads exist or are explicitly
  deferred with rationale.

### 5. Dummy Data Tests

Required once implementation starts:

- same seed produces identical bars.
- different seed may produce different bars.
- generated bars satisfy the 1-minute-bar schema.
- generated bars are sorted or sortable by `symbol`, `timestamp`.
- generated bars cover at least one symbol and one trading day.

### 6. Validator Tests

Required once implementation starts:

- valid dummy bars pass.
- missing required fields fail.
- negative volume fails.
- negative value fails.
- `high < low` fails.
- `open` outside low/high fails.
- `close` outside low/high fails.
- duplicate `symbol + timestamp` fails before or during DB insertion.

### 7. Loader Tests

Required once implementation starts:

- dummy bars insert into Postgres.
- inserted row count matches expected count.
- duplicate load behavior is explicit and tested.
- query by symbol/date range returns expected bars.

### 8. Backtest Tests

Required once implementation starts:

- at least one simple strategy runs end to end on dummy data.
- report contains:
  - `trade_count`
  - `gross_pnl`
  - `net_pnl`
  - `max_drawdown`
  - `start_equity`
  - `end_equity`
- same input/config produces same report.
- a small hand-checkable fixture has expected trade count and PnL behavior.

### 9. Safety Tests

Required once implementation starts:

- no broker API package or endpoint is used without explicit plan approval.
- no files matching common secret patterns are required for tests.
- no real order placement function exists in phase-1 code.
- docs continue to state that live trading, paper trading, broker API, and
  server deployment are out of scope.

## Passing Standard

Phase-1 implementation is not complete until:

- `./scripts/verify.sh` exits 0.
- failing tests identify the broken contract clearly.
- no live-trading/API/secret behavior is introduced.
- any degraded review-gate result is reported with reviewer status.
