# KIS Domestic Stock Review Checklist

## Broker Boundary

- No real order/account/balance calls were introduced without explicit approval.
- KIS calls are isolated behind adapter or command boundaries.
- No credentials, account numbers, tokens, or private endpoints are persisted.

## Mode Separation

- No-order, paper, and live modes are explicit and tested.
- Live mode cannot be reached through defaults.
- Paper/live artifacts are distinguishable.

## Strategy Meaning

- Refactors preserve strategy parameters and signal semantics unless a strategy
  validation task explicitly changes them.
- Backtests or replay comparisons cover any proposed strategy-meaning change.
- Reason counts and near-miss diagnostics remain available.

## Required Inputs

- Warm-up/history source is validated before strategy evaluation.
- Market-data freshness is checked per symbol.
- Degraded symbols are classified without stopping unrelated symbols unless the
  input contract itself fails.

## Order Safety

- Duplicate-order prevention is tested before any order-capable path.
- Kill switch blocks new entries and order transmission.
- Maximum loss controls are enforced and fail closed on stale evidence.

## Tooling

- Repomix was read-only if used.
- Aider, if used, had explicit file scope and did not modify strategy meaning or
  broker permissions.
