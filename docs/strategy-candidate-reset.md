# Strategy Candidate Reset

This document resets the phase-2 strategy validation process. Results produced
before this reset are reference evidence only. They are not promoted strategy
approval, field-test approval, or final parameter recommendations.

## Reset Decision

The previous backtest search found useful candidate evidence, but it did not
start from a complete field-test-aligned strategy contract. Some parameters that
matter in field execution are hard to express in the current backtest, while
some backtest parameters are only approximations of live execution behavior.

From this point, strategy validation starts from candidate strategy families,
then derives the required parameters, required data, and feasibility decision
for each candidate before any new performance run is treated as decision
evidence.

Previous results may be reused only as seed inputs for a named candidate. If a
previous candidate is still interesting, rerun it under this reset process.

The executable work order for this reset lives in
[`strategy-validation-plan.md`](strategy-validation-plan.md).

## New Validation Order

1. Define a small set of strategy candidates before running performance tests.
2. For each candidate, list the market hypothesis and expected failure mode.
3. Derive the field-test operating contract for the candidate.
4. Classify each contract rule as backtest-exact, conservative approximation,
   field-only measurement, missing, or different-from-field.
5. Derive required parameters from the candidate logic.
6. Classify each parameter as backtest-exact, backtest-approx, field-only, or
   missing.
7. Derive required data and classify it as available, additionally collectible,
   field-only, or defer/abandon.
8. Decide whether the candidate is testable with current local data.
9. Write the backtest contract for only the testable portion.
10. Run candidates sequentially under the same reporting standard.
11. Continue until at least one day-trade candidate and one swing candidate pass,
    or until the missing class is blocked by documented data, pipeline, or
    safety constraints.
12. If a required class has no passing candidate, rebuild that class's candidate
    set and repeat the decision-record process.
13. Promote only candidates that pass stress, walk-forward, continuity, and
    contract-parity gates.

Do not widen the parameter space after seeing results unless the change is
recorded as a new candidate or a new candidate version.

## Candidate Set

Initial candidate set:

| ID | Candidate | Market hypothesis | Current status |
| --- | --- | --- | --- |
| A | Defensive daily pullback | Liquid names that pull back inside a controlled volatility/risk band can compound while keeping drawdown small. | Seed exists from previous Ralph search; must be rerun. |
| B | Intraday VWAP pullback | Strong intraday impulse followed by a controlled VWAP pullback can support short holding-period entries. | Framework exists; requires parameter/data feasibility review. |
| C | Breakout momentum | Early strength with volume confirmation can outperform in favorable regimes. | Framework exists; requires regime and execution-gap review. |
| D | Index-regime filtered long-only | Long entries should be blocked in index bear regimes to reduce downside. | Requires accepted index/regime data gate. |
| E | Relative-strength long-only | Symbols outperforming the index intraday should be preferred over absolute-price signals. | Requires synchronized symbol/index bars. |
| F | Low-volatility support swing | Pullbacks near trend support with muted selling pressure may be safer for small accounts. | Framework exists; requires carry/overnight contract. |

The candidate set is intentionally small. Add a new candidate only when it has a
distinct market hypothesis or materially different required data.

Candidate A starts in
[`strategy-candidate-a.md`](strategy-candidate-a.md). The approved first path is
`A-DAY`: prior-only overnight universe selection, after-open scouter validation,
and same-day exit. `A-SWING` remains a separate version, not an unrecorded
extension of `A-DAY`, and should be prepared as a swing comparison candidate
after the day-trade path.

## Parameter Feasibility Classes

Use these classes for every candidate parameter:

| Class | Meaning | Decision impact |
| --- | --- | --- |
| backtest-exact | The backtest and field test can apply the parameter with the same practical meaning. | Eligible for candidate selection. |
| backtest-approx | The backtest can model the parameter only with an approximation. | Must be stress-tested and reported as a gap. |
| field-only | The parameter affects field execution but cannot be meaningfully backtested from current data. | Keep out of performance selection; validate in field rehearsal logs. |
| missing | The parameter is required by the candidate but is not currently implemented or available. | Add implementation/data work, or reject/defer the candidate. |

Do not silently assume that field-only safety controls improve backtest
performance. They belong to the execution safety layer, not to the strategy
profitability claim.

## Strategy-Contract Feasibility Classes

Use these classes for every rule that can change trade selection, timing,
sizing, risk, exits, or reporting:

| Class | Meaning | Decision impact |
| --- | --- | --- |
| backtest-exact | The backtest and field test apply the rule with the same practical meaning. | Eligible for candidate selection. |
| backtest-conservative-approx | The backtest approximates the rule pessimistically enough to avoid overstating performance. | Must be stress-tested and reported as a gap. |
| field-only-measurement | The rule can only be measured during field rehearsal, such as latency, order rejection, or cancel/retry behavior. | Exclude from historical PnL attribution and log later. |
| missing | The rule is required but not represented yet. | Implement, defer, or reject before performance testing. |
| different-from-field | The backtest rule differs from what field test will actually run. | Hard reject until corrected or versioned as a different strategy. |

The classification applies to the whole strategy, not only to universe
selection. It includes universe refresh cadence, scan cadence, signal timing,
data staleness, entry and exit timing, stop/take ordering, carry behavior,
position sizing, risk fuses, blacklist behavior, and invalid-trade handling.

## Data Feasibility Classes

Use these classes for every required data input:

| Class | Meaning | Decision impact |
| --- | --- | --- |
| available | The repository already has local data and a loader/validator for this input. | Eligible for current backtest. |
| additionally-collectible | The input can be collected locally within the approved read-only market-data boundary. | Collect or defer explicitly before testing. |
| field-only | The input can only be observed during field rehearsal, such as API latency or order response behavior. | Exclude from historical performance selection. |
| defer-abandon | The input is not realistic for the current phase or creates scope/safety risk. | Reject the candidate or redesign it. |

## Candidate Decision Record

Each candidate must have a compact decision record before a performance run:

```text
Candidate:
Hypothesis:
Trading horizon:
Universe module:
Scouter module:
Field-test operating contract:
Strategy-contract parity checklist:
Required parameters:
Required data:
Field-test decision cadence:
Universe refresh cadence:
Scan cadence:
Intended order/fill model:
Known backtest/field-test gaps:
Alignment score:
Alignment verdict:
Hard reject checks:
Backtest-exact parameters:
Backtest-approx parameters:
Field-only parameters:
Missing/deferred items:
Backtest contract:
Allowed sweep/optimizer boundaries:
Failure criteria:
Promotion criteria:
Report path:
```

Universe and scouter modules are part of the candidate version. They are not
standalone profit claims. If a module variant materially changes trade
selection, record the run as a new version such as `A-DAY-U1-S1` rather than as
an untracked parameter tweak.

## Default Failure Criteria

A candidate should be rejected or redesigned when any of these conditions hold:

- Required data is missing and not additionally collectible within the approved
  phase-2 boundary.
- The main alpha signal depends on field-only inputs.
- Profits rely on continuity-invalid trades or unavailable index/regime data.
- Base result is positive but 2x cost, gap, or stop-first stress erases the
  edge.
- Walk-forward replay fails after parameters are locked.
- Trade count is too small to interpret and the candidate cannot be broadened
  without changing its hypothesis.
- Drawdown or worst-month loss is incompatible with the KRW 1,000,000 seed
  account objective.

## Previous Candidate Evidence

The prior Ralph search produced a defensive daily pullback seed candidate with
the following rough shape:

- liquidity and volatility filters;
- pullback band around moving-average context;
- `stop`, `take`, and fixed-risk sizing;
- favorable universe-robust and locked walk-forward reference results.

That evidence is useful for Candidate A only. It is not a promoted strategy
until Candidate A receives a decision record under this reset process and is
rerun with the agreed backtest contract.

## Field-Test Boundary

This reset does not approve paper trading, live trading, broker order routing,
account actions, credential storage, or production deployment. Field-test
readiness requires a later owner-approved execution safety plan and a separate
field-rehearsal contract.
