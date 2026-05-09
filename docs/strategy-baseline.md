# Strategy Baseline

This file is the current working baseline for strategy discussions. The archived
`(old)/` files remain the starting reference, but they are not edited in place.

Phase 1 and 1.5 proved framework behavior only. They do not prove strategy
profitability.

## Initial Decision Rules

- Use `(old)/` trading conditions, sequence, risk controls, and architecture as
  the first source when implementing a strategy rule.
- If old files conflict, prefer the newest saved file unless implementation
  evidence strongly supports a different interpretation.
- Record any AI-chosen exception in current docs before coding it.
- Keep thresholds flexible until the real two-year Daishin CYBOS raw minute
  dataset has passed the intake gate and been tested.

## Current Minimum Inputs

The real-data strategy validation stage should expect:

- per-symbol 1-minute bars
- index 1-minute bars for market regime filters
- symbol metadata for market/status/control/supervision filters
- fee and slippage assumptions
- deterministic reports that can compare strategy variants

News and disclosure signals are deferred to a later field-test stage because
their source reliability, latency, and normalization rules are materially harder
than minute-bar data.

## Non-Goals

- No live trading.
- No paper order routing.
- No final profitability claim from dummy or sample data.
- No hardcoded final trading recommendation before real-data validation.
