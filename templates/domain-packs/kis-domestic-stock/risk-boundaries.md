# KIS Domestic Stock Risk Boundaries

## Real Orders

Touching order placement, cancellation, correction, liquidation, or live broker
state is strict scope. Require an explicit plan, user approval, tests, and
review gate.

## Credentials

Credential material must not be echoed, persisted, committed, or copied into
context packs. Store only placeholder names such as `KIS_APP_KEY` and
`KIS_APP_SECRET`.

## Paper/Live Separation

Paper and live must not share silent defaults. Require explicit mode selection,
separate endpoints or profiles, separate artifacts, and tests proving that live
calls are unreachable from no-order/paper paths.

## Duplicate Orders

Before any order-capable path, require:

- idempotency key or order-intent id;
- symbol-side-position de-duplication;
- pending order state;
- retry/backoff policy;
- tests for duplicate signal and retry scenarios.

## Kill Switch

Require a kill switch that blocks new orders and can freeze/stop the runner.
Tests must prove it wins over strategy signals.

## Maximum Loss

Require daily, per-position, and portfolio-level maximum loss controls before
paper/live. Missing or stale PnL evidence must fail closed.

## Required Inputs

Missing, stale, degraded, or contract-invalid inputs must block downstream
universe selection, strategy evaluation, or order decisions. Do not silently use
shorter histories, stale snapshots, narrower symbols, or cached data unless the
command is explicitly analysis-only.
