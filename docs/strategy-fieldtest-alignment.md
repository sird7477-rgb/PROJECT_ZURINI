# Strategy Field-Test Alignment Assessment

This document estimates how well each initial strategy candidate can be aligned
between historical backtest and a later field-test rehearsal.

The percentages below are not expected returns and not success probabilities.
They are alignment scores: how much confidence the current backtest setup can
support before field-only behavior must be measured separately.

## Scoring Meaning

| Score | Meaning |
| --- | --- |
| 80-100% | Strong alignment. Backtest and field-test contracts are mostly equivalent after normal stress tests. |
| 60-79% | Usable with explicit gaps. Backtest can select/reject the candidate, but field rehearsal must measure known gaps. |
| 40-59% | Analysis-only unless gaps are reduced. Backtest may guide design, but should not drive promotion alone. |
| 0-39% | Poor alignment. Core behavior depends on missing, field-only, or unmodeled execution/data inputs. |

## Alignment Dimensions

Each candidate is judged across these dimensions:

- Data parity: whether historical Daishin data can represent later field data
  semantics.
- Signal observability: whether the signal uses bars/metadata available at the
  simulated decision time.
- Execution model: whether entry, exit, order timing, fills, partial fills, and
  failures can be represented or conservatively approximated.
- Capital/risk model: whether KRW 1,000,000 account sizing, whole-share
  constraints, slot limits, drawdown, and loss stops are modeled.
- Continuity/auditability: whether valid-only trades, source gaps, and report
  evidence can be separated.
- Strategy-contract parity: whether the backtest tests the same operating rules
  that the field-test will actually run, including universe refresh cadence,
  scan cadence, signal timing, exits, holding rules, and safety behavior.

Use a 100-point rubric, with each dimension scored from 0 to 20:

| Dimension | 0 | 10 | 20 |
| --- | --- | --- | --- |
| Data parity | Backtest source cannot represent field source semantics. | Known source gaps exist but can be registered and stressed. | Historical and field data semantics are nearly equivalent for this strategy. |
| Signal observability | Signal uses information unavailable at decision time. | Some stale/missing-data rules need explicit handling. | Signal uses only prior or current observable inputs. |
| Execution model | Entry/exit edge depends on unmodeled fills or queue behavior. | Price/time are approximated with conservative stress, but field-only gaps remain. | Backtest execution contract closely matches field-test order/fill behavior. |
| Capital/risk model | Strategy cannot run under KRW 1,000,000 account constraints. | Account sizing is approximate but conservative. | Cash, whole-share sizing, slots, stops, and loss fuses match field constraints. |
| Continuity/auditability | Invalid or unknown-continuity trades can drive results. | Continuity is reported but some class-specific gaps remain. | Valid-only trade metrics and source gaps are cleanly separated. |

Intermediate values such as 5 or 15 are allowed when evidence falls between the
anchors. The score is a rubric score, not a probability, p-value, confidence
interval, expected return, or field success rate.

## Candidate Scores

| ID | Candidate | Alignment | Current use | Main blockers |
| --- | --- | ---: | --- | --- |
| A | Defensive daily pullback | 72% | Backtest-selection candidate after audit | Daishin/KIS source parity, universe construction, daily gap/stop approximation |
| B | Intraday VWAP pullback | 48% | Analysis-only until sparse-bar and execution gaps are reduced | Sparse stock bars, intrabar fill ambiguity, order timing/partial-fill gap |
| C | Breakout momentum | 43% | Analysis-only until execution model is stricter | Same as B, plus higher slippage and chase-risk sensitivity |
| D | Index-regime filtered long-only | 58% | Analysis-only until index gate and calendar certification pass | Index acceptance, calendar certification, regime lookback timing |
| E | Relative-strength long-only | 52% | Analysis-only until synchronized symbol/index evidence is proven | Timestamp alignment, sparse stock bars, index/source parity |
| F | Low-volatility support swing | 63% | Backtest candidate only after carry contract | Overnight/carry rule, gap risk, daily/sparse aggregation assumptions |

## Alignment Gate

Alignment is a gate, not just a descriptive score. Apply hard reject checks
first, then apply the score gate.

## Plan A Dry-Run Alignment Addendum

The validated Plan A portfolio is eligible for no-order dry-run preparation,
not for live or paper order activation. Its alignment status is conditional on
carrying forward the operating rules documented in
[`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md).

Plan A dry-run alignment requirements:

- the field dry-run must use the same strategy IDs, group caps, slot caps,
  contribution schedule, and Plan B fallback semantics recorded in the
  strategy matrix;
- same-symbol day/swing conflict handling must follow the archived first-in,
  first-served interlock, same-day day-to-swing reuse, 15:15 cooldown, and
  lock-step sequencing rules;
- dry-run reports must separate strategy edge from field-only execution
  behavior such as real spread, order-book depth, queue position, partial fill,
  timeout, cancel, and retry behavior;
- small-seed feasibility must be reported separately for KRW `1,000,000` and
  KRW `2,000,000`, both with weekly KRW `100,000` contributions;
- shared-slot Plan A and 40/60 separated sleeve behavior must be compared as
  field-operating feasibility checks, not as an optimizer search for the best
  ratio;
- no dry-run result may promote capital above the current KRW `70,000,000`
  validated ceiling without a new validation pass.

Dry-run readiness is blocked if order transmission is not hard-blocked, if skip
and cooldown events are not persisted, or if daily reports cannot reconcile
universe, scouter, virtual order, virtual fill, cash, slot, sleeve, and risk
state.

### Hard Reject

Reject or redesign a strategy candidate regardless of its score or backtest PnL
when any of these conditions apply:

- the core alpha signal depends on `field-only` data;
- the expected edge depends on order/queue/fill behavior that historical
  backtests cannot represent or conservatively approximate;
- the universe uses future availability, survivorship, future liquidity, or
  metadata unavailable at the simulated decision time;
- any strategy-contract rule that affects trade selection, timing, sizing, risk,
  or exits differs from the later field-test contract;
- universe refresh cadence, scan cadence, or decision cadence is materially
  faster in backtest than the planned field-test cadence;
- continuity-invalid trades materially drive PnL or parameter selection;
- the candidate assumes a data source that will not exist in the later
  field-test path;
- the candidate cannot be executed under the KRW 1,000,000 account model,
  whole-share sizing, cash, and slot constraints;
- field-only safety controls are credited as historical performance.

### Score Gate

| Alignment | Decision | Allowed action |
| ---: | --- | --- |
| `>= 70%` | testable | Default backtest, allowed coarse survival sweep, and limited optimizer are allowed after the candidate record is complete. |
| `60-69%` | conditional | Default backtest is allowed; coarse survival sweep is allowed only for documented parameters; optimizer is blocked until gap mitigation is complete. |
| `50-59%` | analysis-only | Backtest may inform design, but optimizer and promotion are blocked. |
| `< 50%` | reject/redesign | Redesign, defer, or keep only as a non-promotional research note. |

### Optimizer Entry Gate

Optimization is allowed only when all conditions hold:

- no hard reject condition applies;
- alignment is `>= 70%`;
- the candidate passed default or coarse survival testing;
- field-only parameters are excluded from the optimizer;
- continuity-invalid trades are excluded from selection metrics;
- parameter ranges were documented before the run.

Candidates with `60-69%` alignment may run only default backtests or coarse
survival sweeps until the documented gaps are reduced and the alignment score is
updated. Candidates below `60%` must not enter optimization.

## Candidate A: Defensive Daily Pullback

Alignment score: 72%.

Why it aligns better:

- Uses slower daily-style signals, reducing sensitivity to per-minute execution
  and sparse intraday bars.
- Liquidity, volatility, pullback, stop, take, and fixed-risk parameters can be
  modeled with conservative historical assumptions.
- Existing prior-only walk-forward and cost-stress patterns are reusable as
  reference shapes, though they must be rerun under the reset plan.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Source parity gap | 8-15% | Daishin historical data may differ from later KIS field observations in adjustment, timestamp, and symbol semantics. |
| Universe hindsight | 5-12% | Candidate must prove prior-only universe and metadata availability. |
| Daily OHLC ambiguity | 5-10% | Stop/take order inside a daily bar is approximate; stop-first stress is required. |
| Liquidity-to-fill gap | 3-8% | Daily liquidity does not guarantee field fill quality for a small account, but risk is lower than intraday chase strategies. |

Promotion condition: rerun Candidate A with a written decision record, prior-only
universe construction, exact capital model, stop-first stress, 2x cost stress,
and continuity-valid-only reporting.

## Candidate B: Intraday VWAP Pullback

Alignment score: 48%.

Why alignment is limited:

- The signal relies on intraday path shape and VWAP context.
- Current stock files behave like sparse trade-event bars, not a guaranteed
  every-minute grid.
- Field execution depends on order timing, fill price, partial fills, and
  cancel/retry behavior that historical bars cannot fully represent.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Sparse-bar signal distortion | 15-25% | Missing stock minutes may hide whether VWAP/pullback state was actually observable. |
| Fill model gap | 10-20% | Close-price fills can overstate executable entries/exits. |
| Slippage sensitivity | 8-18% | Pullback entries may be highly sensitive to spread and queue position. |
| Field-only controls | 5-10% | Order timeout/retry/safety behavior cannot be credited to historical PnL. |

Promotion condition: require exact-bar continuity, explicit decision cadence,
fill model stress, and field-only execution controls separated from backtest
performance.

## Candidate C: Breakout Momentum

Alignment score: 43%.

Why alignment is limited:

- Breakout entries are more sensitive to latency and slippage than pullback
  entries.
- Historical minute bars cannot model queue position or whether the breakout
  price was actually executable.
- Sparse bars make impulse volume and breakout timing harder to trust.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Chase slippage | 15-30% | Field entries may occur after the backtest signal price. |
| False impulse from sparse bars | 10-20% | Missing intermediate bars can exaggerate apparent momentum. |
| Stop/target path ambiguity | 8-15% | Fast reversals are difficult to order inside bar data. |
| Trade concentration | 5-15% | Momentum results may depend on a small number of outlier trades. |

Promotion condition: keep as analysis-only until execution stress and sparse-bar
semantics are proven conservative.

## Candidate D: Index-Regime Filtered Long-Only

Alignment score: 58%.

Why alignment is mixed:

- Index bars are closer to a materialized grid than stock bars, which helps
  regime logic.
- However, long-range promotion still requires certified calendar/day-set
  evidence and strict prior-only regime lookbacks.
- This candidate is often a filter layered on another strategy, so its
  alignment depends on the base candidate too.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Calendar certification gap | 8-15% | Seed calendar is rehearsal evidence, not final promotion evidence. |
| Regime lookahead | 5-12% | Regime state must use only completed prior information. |
| Source/index mismatch | 5-10% | Field source may differ from Daishin index semantics. |
| Filter interaction | 5-15% | Regime filter can reduce trades enough to make results unstable. |

Promotion condition: require accepted index coverage, certified calendar for
promoted conclusions, and prior-only regime-state computation.

## Candidate E: Relative-Strength Long-Only

Alignment score: 52%.

Why alignment is mixed:

- The idea is field-testable if symbol and index bars are synchronized.
- Current sparse stock bars create uncertainty about symbol return at the exact
  comparison time.
- Relative strength can be sensitive to timestamp mismatch and opening-price
  definitions.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Timestamp alignment | 10-20% | Symbol and index bars must represent the same decision moment. |
| Opening reference ambiguity | 5-12% | Intraday relative return depends on a consistent session open. |
| Sparse stock data | 10-20% | Missing symbol bars may turn a stale comparison into a false signal. |
| Filter overconstraint | 5-10% | Combined filters can reduce trade count below useful levels. |

Promotion condition: require synchronized index/symbol evidence, exact-bar
stock continuity, and a defined stale-bar rejection rule.

## Candidate F: Low-Volatility Support Swing

Alignment score: 63%.

Why it aligns moderately:

- Uses slower support/volume/RSI-style information that is less sensitive to
  minute-level order timing.
- It can be backtested from daily-like aggregates, but it needs an explicit
  overnight/carry contract.
- Gap risk becomes central because exits may occur after overnight moves.

Expected risks:

| Risk | Estimated alignment drag | Notes |
| --- | ---: | --- |
| Overnight gap | 10-20% | Historical OHLC can approximate but not remove gap-fill uncertainty. |
| Carry policy mismatch | 8-15% | Field behavior must match backtest holding and forced-exit rules. |
| Daily aggregation assumptions | 5-12% | Sparse minute-to-daily conversion must be reproducible and source-valid. |
| Small-account concentration | 5-10% | Longer holds may tie up capital and reduce diversification. |

Promotion condition: require approved carry rules, gap stress, whole-share
capital model, and stable daily aggregation evidence.

## Cross-Candidate Required Controls

Before any candidate can be promoted beyond analysis:

- Every strategy rule that can change trade selection, timing, sizing, risk,
  exits, or reporting must be classified as exact, conservative approximation,
  field-only measurement, missing, or different-from-field.
- The field-test decision cadence must be stated.
- The universe refresh cadence and symbol metadata timing must be stated.
- The scan cadence and stale-data behavior must be stated.
- The intended order/fill model must be stated.
- Field-only controls must be excluded from backtest PnL attribution.
- Backtest uses KRW 1,000,000 account constraints and whole-share sizing unless
  a different field-test account model is explicitly approved.
- Universe construction must be prior-only and metadata availability must be
  recorded.
- Continuity-invalid trades must not drive optimization or promotion.
- Daishin historical data versus later promoted/field data differences must be
  recorded as a source-gap register.

## Current Priority

The current priority remains the minimal pipeline trust audit from
[`strategy-validation-plan.md`](strategy-validation-plan.md). Candidate A and F
have the best initial alignment because they are less dependent on exact
intraday execution. B, C, D, and E should remain analysis-only until their
specific data and execution gaps are reduced or explicitly accepted as
limitations.
