# Phase 1 PRD: Local Backtest Foundation

## Purpose

Build the first executable foundation for PROJECT_ZURINI: a local, reproducible
backtest framework for automated-trading strategy iteration.

Phase 1 must prove that the project can load deterministic 1-minute-bar data
into Postgres, validate the data contract, run at least one simple strategy, and
produce a minimal backtest report. It does not need to prove strategy
profitability.

## Users

- Project owner running development on a personal local PC.
- Codex/Ralph executing bounded implementation and verification loops.
- Future strategy work that needs a stable backtest harness.

## Non-Goals

- Real broker integration
- Real orders
- API keys, account numbers, credentials, or secret handling
- Paper trading
- Production server or cloud deployment
- Real historical 1-minute data acquisition
- Final strategy tuning or profitability claims

## Runtime

- Language: Python
- Test runner: pytest
- Database: Docker Compose Postgres
- Execution location: local personal PC

The implementation should keep pure strategy calculations testable without a DB,
but DB schema, loading, and integration behavior must be verified against
Postgres.

## Required Capabilities

### 1. Project Scaffold

The repository must contain a Python application/test layout that can be run from
the repo root. Exact module names may change if the implementation remains clear
and `./scripts/verify.sh` is kept current.

### 2. Postgres Schema

Define a standard 1-minute bar table suitable for later real historical data.

Initial logical fields:

```text
symbol
timestamp
open
high
low
close
volume
value
source
ingested_at
```

Required constraints:

- `symbol + timestamp` unique
- `open`, `high`, `low`, `close` not null
- `volume >= 0`
- `value >= 0`
- `high >= low`
- `high >= open`
- `high >= close`
- `low <= open`
- `low <= close`

Timezone handling must be explicit. Phase 1 uses KST market bars.

### 3. Dummy Data Generator

Generate deterministic dummy 1-minute bars.

Requirements:

- accepts a seed
- produces the same data for the same seed
- supports at least one symbol and one trading day
- produces valid OHLCV/value data
- creates data that can trigger at least one simple strategy signal

The dummy data exists to validate the framework, not to model market realism.

### 4. Data Validator

Validate records before or during insertion.

Positive cases:

- valid dummy bars pass
- generated data can be inserted into Postgres

Negative cases:

- missing required field fails
- negative volume/value fails
- invalid OHLC relationship fails
- duplicate `symbol + timestamp` fails

### 5. Data Loader

Load dummy bars into Postgres.

Requirements:

- creates or migrates the phase-1 schema
- inserts deterministic dummy data
- reports inserted row count
- supports repeatable test setup against a disposable DB

### 6. Backtest Engine

Run at least one simple strategy over loaded dummy data.

Minimum behavior:

- reads bars in `symbol`, `timestamp` order
- emits buy/sell/hold or equivalent decisions
- records trades or positions
- accounts for start equity
- supports configurable fee/slippage assumptions, even if defaults are simple
- produces a report

The strategy may be deliberately simple. The framework is the product of phase
1, not the strategy.

### 7. Report

The minimum report must include:

```text
trade_count
gross_pnl
net_pnl
max_drawdown
start_equity
end_equity
```

The report must be deterministic for the same dummy data and configuration.

### 8. Safety Guardrails

The phase-1 codebase must not contain real broker calls, real order placement,
account identifiers, API keys, or secret files.

## Acceptance Criteria

Phase 1 is complete when:

- `./scripts/verify.sh` starts the required local checks or clearly verifies the
  implemented test suite.
- Postgres schema creation is tested.
- deterministic dummy data generation is tested.
- validator positive and negative cases are tested.
- dummy data insertion into Postgres is tested.
- at least one backtest smoke test runs and produces the minimum report fields.
- safety guardrails reject live-trading/API/secret scope creep.

## Deferred Decisions

- Actual historical data vendor/source
- Adjusted vs raw price storage split
- Trading halt representation
- Corporate action handling
- Partitioning and high-volume ingestion performance
- Paper trading architecture
- Live trading deployment target
