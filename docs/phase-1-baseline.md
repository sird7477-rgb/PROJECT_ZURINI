# Phase 1 Active Baseline

This file extracts the phase-1 implementation baseline from `(old)/`.
The archived files remain preserved history. This baseline is the starting point,
not an immutable specification; deliberate changes must be recorded here or in
the PRD/test spec before implementation depends on them.

When old documents conflict, use the most recently saved old document as the
default source. An AI reviewer or implementer may make an exception only when it
has high confidence and records the reasoning in current docs before depending
on the exception.
If saved-time evidence is unavailable or tied, choose the more conservative
interpretation until the user or a documented high-confidence AI judgment
overrides it.

## Strategy Baseline

- Primary phase-1 strategy shape: day-trading VWAP first-pullback.
- Entry signal: price returns near VWAP within a 0.5% band after an earlier
  volume/price impulse.
- Conservative simplification for phase 1: use a deterministic bar sequence and
  a minimum bid/ask pressure field in memory, but persist only standard 1-minute
  OHLCV/value data in Postgres.
- Exit signal: start with full-position exits for profit target, hard stop, and
  end-of-test close. Partial profit taking and IOC order spraying are deferred
  until execution simulation is richer.

## Risk Baseline

- Global beta throttle is represented as a multiplier clamped from 0.0 to 1.0:
  `1.0 + nasdaq_future_return * 20`.
- If market-risk data is unavailable, phase 1 uses conservative half sizing
  (`0.50`) instead of normal sizing.
- Day-loss circuit breaker and MDD fuse are represented as configuration and
  report metrics in phase 1; no live liquidation code is allowed.
- Blacklist behavior is conservative: stale blacklist heartbeat or a listed
  symbol blocks new entry.

## Data And Sequence Baseline

- Postgres is the source of 1-minute historical bars for backtest execution.
- Phase 1 uses deterministic dummy 1-minute bars until the dummy-data backtest
  target is complete. Real historical 1-minute data acquisition starts after
  that point.
- `symbol + timestamp` is the stable identity for a bar.
- Timestamps are timezone-aware and phase 1 uses KST market bars.
- Schema and inserts must be repeatable against a disposable local DB.
- DB changes are explicit and transaction-oriented; live broker/API calls stay
  outside phase 1.

## Architecture Baseline

- Keep strategy logic pure enough to run without a DB.
- Keep data access behind loader/fetch functions so later real historical data
  can use the same schema.
- Phase 1 is complete only after the backtest supports multi-symbol execution.
  Initial multi-symbol accounting may keep one independent strategy/position
  state per symbol and aggregate the report deterministically.
- Rationale for adding multi-symbol support to phase 1: the user clarified on
  2026-05-09 that first-phase backtesting should naturally finish at
  multi-symbol coverage. A single-symbol-only backtest is useful as an
  intermediate scaffold, but it is not sufficient as the phase-1 destination for
  an automated trading system.
- Keep a friction layer in the backtest engine through fee/slippage settings.
- Produce deterministic reports with `trade_count`, `gross_pnl`, `net_pnl`,
  `max_drawdown`, `start_equity`, and `end_equity`.
- Provide a CLI path for the phase-1 dummy multi-symbol backtest that writes
  JSON, CSV, and text reports after loading and reading bars through Postgres.
