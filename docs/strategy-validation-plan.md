# Strategy Validation Plan

This plan operationalizes the strategy reset. It defines the next work order
before new phase-2 performance results are treated as decision evidence.

## Objective

Build a field-test-aligned backtest selection process for a KRW 1,000,000 seed
account. The goal is not to maximize an in-sample backtest. The goal is to find
or reject strategy candidates under explicit data, parameter, execution, and
risk constraints.

Previous Ralph/backtest results are reference evidence only. They may seed a
candidate, but they do not bypass this plan.

Current Plan A next-action tracking is centralized in
[`plan-a-next-actions.md`](plan-a-next-actions.md). Use that index to find the
active no-order status, strict parameter contract, weekend work queue, next-week
comparison, future work, and backtest fallback trigger.

## Ralph Execution Target

When this plan is executed through Ralph, the completion target is portfolio
integration pass, not merely a passing standalone strategy.

Ralph should continue through the loop until:

- at least one day-trade candidate passes strategy-level validation;
- at least one swing candidate passes strategy-level validation;
- the passing day-trade and swing candidates are combined under the portfolio
  capital contract;
- the integrated portfolio backtest passes the documented stress, continuity,
  source-gap, execution-gap, and report-analysis gates.

If either the day-trade or swing class has no passing candidate, rebuild that
class and repeat strategy-level validation before portfolio integration. Stop
only when the integrated portfolio passes, or when a documented data, pipeline,
safety, or field-test-alignment blocker makes further validation analysis-only.

## Priority Order

1. Run a minimal pipeline trust audit that can change strategy selection.
2. Define and freeze the initial strategy candidate set.
3. For each candidate, derive required parameters and required data.
4. Classify strategy-contract, parameters, and data by field-test feasibility.
5. Write a candidate decision record before each performance run.
6. Run default-value backtests or allowed coarse survival sweeps.
7. Reject or keep candidates before any optimizer step.
8. Continue strategy-level validation until at least one day-trade candidate and
   at least one swing candidate pass, or until the available data/pipeline
   limits force analysis-only status.
9. If no candidate passes in a required class, rebuild the strategy candidate
   set and return to candidate definition.
10. Run limited optimization only for kept candidates.
11. Lock selected parameters and rerun walk-forward, stress, and continuity
   validation.
12. Before portfolio integration, run capacity checks on the surviving
    day-trade and swing candidates:
    - `MAX-SLOT-SEED`: increase starting equity to the maximum deployable
      slot count under the operating slot plan. Current default is `5` slots
      times KRW `10,000,000`, so KRW `50,000,000`.
    - `SLIP-LIMIT-STRESS`: increase seed only to a documented slippage-limit
      assumption. With current historical CSV data this is an OHLCV liquidity
      proxy and fee/slippage-rate stress, not a proof of real fill quality.
13. Run portfolio-level integration only after individual strategies pass their
   own strategy-level validation.
14. Promote a candidate only as a backtest research candidate, not as field-test
    or trading approval.

## Step 1: Minimal Pipeline Trust Audit

Do not perform a full pipeline rewrite before strategy design. Audit only the
pipeline risks that can change which strategy candidates are valid.

Required audit questions:

| Area | Question | Strategy impact | Evidence target |
| --- | --- | --- | --- |
| Sparse stock bars | Can the current sparse 1-minute stock data support intraday signals without false continuity assumptions? | May demote VWAP/breakout candidates or require exact-bar continuity reporting. | Document current sparse-data behavior and valid trade-continuity mode. |
| Index alignment | Are index bars available, accepted, and timestamp-aligned with stock bars for regime/relative-strength candidates? | May keep regime/relative-strength candidates as analysis-only until index gate passes. | Index coverage/acceptance artifact or explicit blocker. |
| Capital model | Does the backtest model the intended KRW 1,000,000 field-test account with whole-share sizing, slot limits, and cash constraints? | May change all candidate results and reject strategies that need unrealistic capital. | Backtest config decision: `shared-slot` or equivalent field-test account model. |
| Trade continuity | Can reports separate continuity-valid trades from invalid trades? | Prevents promoting PnL driven by missing entry/exit windows. | Report field or test evidence. |
| Session/carry rules | Are day-end exit, overnight carry, and max holding time aligned with the candidate horizon? | Determines whether swing candidates are testable. | Candidate-specific carry rule. |
| Cost model | Are fee, slippage, gap, and stop-first assumptions explicit and stressable? | Required for reject/keep decisions before optimizer. | Base and stress assumptions recorded. |
| Data-source parity | Are backtest data sources and later field-test data sources known to differ in timestamp, price, volume, adjustment, or symbol semantics? | Prevents treating Daishin historical behavior as identical to later KIS field observations. | Source-gap register with accepted differences and blockers. |
| Execution contract | Are order timing, order type, fill price model, partial fills, order failures, timeout, and cancel/retry behavior represented or explicitly field-only? | Separates strategy edge from field execution controls that cannot be credited in historical PnL. | Execution-gap register and field-only parameter list. |
| Universe construction | Does the universe avoid survivorship, hindsight, and unavailable-at-trade-time filters? | Prevents selecting symbols using information the field test would not have had. | Prior-only universe rule and metadata availability statement. |
| Strategy-contract parity | Do all strategy rules match the later field-test operating contract, including selection cadence, scan cadence, signal timing, position management, exits, risk fuses, logging, and invalid-data handling? | Prevents a backtest from testing a different strategy than the one field-tested. | Candidate contract parity checklist with any mismatch classified before performance runs. |

Stop condition for this audit: each area is marked `pass`, `analysis-only`,
`needs implementation`, or `blocks candidate class`. The audit does not need to
prove profitability.

The audit must also produce a backtest/field-test gap register. Each gap is
classified as:

- `accepted-approximation`: allowed in backtest but reported as a limitation;
- `field-only-measurement`: excluded from performance selection and measured in
  field rehearsal logs later;
- `implementation-needed`: required before the candidate can be tested;
- `blocks-promotion`: allowed for analysis but blocks field-test promotion.

## Step 2: Candidate Definition

Use the candidate set from
[`strategy-candidate-reset.md`](strategy-candidate-reset.md) as the initial
candidate universe:

- A: Defensive daily pullback
- B: Intraday VWAP pullback
- C: Breakout momentum
- D: Index-regime filtered long-only
- E: Relative-strength long-only
- F: Low-volatility support swing

Each candidate must have one market hypothesis. Do not merge several unrelated
ideas into one candidate to rescue weak results.

Candidate A is now being handled through
[`strategy-candidate-a.md`](strategy-candidate-a.md). Its first approved version
is `A-DAY`: prior-only overnight universe selection, after-open scouter
validation, and same-day exit. `A-SWING` is a separate deferred version and must
not be mixed into `A-DAY` results, but a swing comparison candidate must still
be validated after the day-trade candidate so the process can produce both
day-trade and swing evidence.

## Step 2A: Universe And Scouter Modules

Universe and scouter logic are candidate-specific precondition modules, not
standalone PnL strategies. They may be shared across candidates as code or data
contracts, but performance attribution belongs only to the full strategy
candidate that uses them.

Current Ralph completion condition remains unchanged: Ralph is complete only
after an integrated portfolio candidate passes its final validation gates. The
universe/scouter matrix is a required upstream gate for building a trustworthy
survivor set; it is not a replacement stop condition.

Module rules:

- Universe modules select the prior-only tradeable set before the candidate's
  decision window.
- Scouter modules validate the candidate-specific intraday or near-close setup
  using only information observable at that time.
- A universe or scouter change that materially changes trade selection creates
  a new candidate version, such as `A-DAY-U1-S1`.
- Module variants must pass parity and feasibility checks before any PnL result
  is interpreted.
- Do not score universe/scouter modules by standalone PnL.

Module caps:

- Use at most three universe module candidates per strategy family in the first
  round.
- Use at most two scouter module candidates per strategy version in the first
  round.
- Keep first-round strategy/module combinations to two to four per strategy
  version unless a later decision record justifies a wider search.
- Treat wider module expansion as candidate rebuild or a new version, not as an
  unrecorded optimizer search.

Module evaluation should focus on:

- prior-only construction and metadata availability;
- field-test cadence/API feasibility;
- candidate count coverage that is neither too sparse nor too broad;
- stability across months or market regimes;
- turnover and stale-data rejection;
- contribution to full-candidate robustness after base and stress tests.

### Required Universe/Scouter Matrix Before Strategy Selection

The validation unit is `strategy x universe x scouter`, not strategy alone.
The same strategy can pass or fail depending on universe construction, scout
ranking, and slot contention. Therefore, do not promote a strategy survivor
unless the universe/scouter condition is named and reproducible.

Universe IDs:

| ID | Name | Construction | Field cadence | First use |
| --- | --- | --- | --- | --- |
| `U0` | Observed all Daishin CSV symbols | All collected paths, including non-numeric or non-common symbols | Analysis-only unless field tradeability is later proven | Regression comparison only |
| `U1` | Common numeric stock universe | `A[0-9]{6}` observed CSV paths | Overnight/after-close fixed list before next session | Default field-aligned universe |
| `U2` | U1 plus prior liquidity/volatility gate | U1 plus prior-only average value and ATR-ratio thresholds | Overnight/after-close fixed list | Candidate-specific liquidity/volatility robustness |
| `U3` | U1 plus stricter scout-available liquidity gate | U1 plus prior/session value constraints that can be reproduced during field scouting | Overnight plus after-open scout validation | Slippage-control comparison |

Current Plan A field artifact note: `field-u1-prior-only` is the operational
name for the already-validated Plan A universe contract. It includes common
numeric filtering plus prior-only liquidity, SMA, and ATR gates because those
gates were embedded in the validated strategy defaults before this taxonomy was
split into generic `U1`/`U2` labels. Future new strategy families should use the
table above literally; Plan A revalidation records must preserve the exact
`field-u1-prior-only` construction rule to avoid silently changing the tested
contract.

Scouter IDs:

| ID | Name | Selection rule | Field cadence | Notes |
| --- | --- | --- | --- | --- |
| `S0` | Symbol-order fallback | Eligible signals consume slots by deterministic symbol order | Analysis-only baseline | Kept only to compare pre-scout behavior |
| `S1` | Score-ranked default scout | Eligible same-timestamp signals are sorted by strategy-provided `SignalIntent.score`, then symbol | Default after-open/near-close scout | Current field-aligned default |
| `S2` | Conservative liquidity-pressure scout | `S1` plus stricter bid/ask, liquidity, or stale-data rejection gates | After-open/near-close scout | Use only when the strategy contract can observe all inputs |

Result key format:

`{style}-{strategy}-{derivative}-{universe_id}-{scouter_id}-{cost_id}-{holding_id}-{run_id}`

Every result record must include:

- strategy family and derivative id;
- universe id and exact construction rule;
- scouter id and score formula;
- cost id, including base or 2x cost;
- slot policy, seed policy, and weekly contribution policy;
- holding contract;
- regime or relative-strength filter;
- report path;
- continuity summary;
- pass, reject, or analysis-only verdict.

Execution rule:

- Run `U1-S1` first for field-aligned strategy comparison.
- Use `U0-S0` only as a regression reference for old results.
- Add `U2` or `U3` only when the strategy hypothesis or slippage-control
  requirement justifies the extra gate.
- A strategy that survives only under a non-field-aligned condition is not a
  portfolio candidate.
- Multiple survivors are preferred; final portfolio integration should compare
  survivor combinations, not stop at the first passing day-trade and swing pair.

## Step 3: Strategy-Contract, Parameter, And Data Feasibility

For each candidate, fill the decision record from
[`strategy-candidate-reset.md`](strategy-candidate-reset.md) before performance
testing.

### Current Closed Strategy Matrix For Ralph

The current Ralph run must use this closed strategy matrix before portfolio
integration. New strategy rows may be added only with a decision note that
states the distinct market hypothesis and field execution contract.

Day-trade candidates:

| ID | CLI strategy | Derivative | Hypothesis | Default universe/scouter cases |
| --- | --- | --- | --- | --- |
| `A-DAY-PB` | `a-day-v2` | controlled VWAP/SMA pullback | Historical candidate only for the current Plan A dry-run; not part of `plan-a-idmom-d3-fsup-u1s1`. Healthy prior-only universe names that pull back in a controlled intraday band can mean-revert within the day. | `U1-S1`, then `U2-S1` if coverage is too sparse |
| `A-DAY-CONF` | `confirmed-day-pullback` | pullback then reclaim confirmation | Waiting for reclaim after the pullback filters weak falling entries. | `U1-S1` |
| `A-DAY-SUP` | `day-support-pullback` | late-session support pullback | Low-volume support context can work as same-day defensive entry. | `U1-S1` |
| `B-VWAP` | `vwap` | impulse then VWAP pullback | Intraday impulse names can resume after first VWAP pullback. | `U1-S1` |
| `C-ORB` | `opening-range-breakout` | opening-range breakout | Early range compression followed by breakout can carry in favorable regimes. | `U1-S1`, optional `U3-S2` |
| `C-IDMOM` | `intraday-momentum` | intraday return plus VWAP confirmation | Names already trending intraday and above VWAP can continue. | `U1-S1`, optional `U3-S2` |
| `C-PRMOM` | `prior-momentum` | prior-day momentum continuation | Prior strong names can continue if they confirm above prior close. | `U1-S1` |
| `A-GAPREB` | `gap-rebound` | gap-down reclaim | Healthy names that gap down but reclaim prior close may rebound intraday. | `U1-S1` |

Swing candidates:

| ID | CLI strategy | Derivative | Hypothesis | Default universe/scouter cases |
| --- | --- | --- | --- | --- |
| `F-SUP` | `swing-support` | low-volume support swing | Pullbacks near trend support with muted selling pressure can survive overnight with lower churn. | `U1-S1`, optional `U2-S1` |
| `F-MOM` | `swing-momentum` | trend/volume swing | Strong trend plus volume can persist over several sessions. | `U1-S1` |
| `B-OVN-VWAP` | `vwap` | overnight impulse VWAP carry | Intraday impulse/VWAP setup may work better with overnight carry than same-day exit. | `U1-S1` |

Filter dimensions:

| ID | Filter | Values | Rule |
| --- | --- | --- | --- |
| `D-REGIME` | index regime | `none`, `bull-only`, `non-bear` | Use `bull-only` as the default day-trade risk gate when index data is available; compare `non-bear` only as a predeclared robustness check. |
| `E-RS` | relative strength | deferred | Do not include in the first matrix until synchronized index-relative scoring is represented as a named scouter or wrapper. |

Cost dimensions:

| ID | Fee | Slippage | Use |
| --- | --- | --- | --- |
| `COST-BASE` | `0.00015` | `0.00050` | Required base run |
| `COST-2X` | `0.00030` | `0.00100` | Required stress run for any base survivor |

Holding dimensions:

| ID | Contract | Use |
| --- | --- | --- |
| `DAY-60` | same-day exit, max 60 minutes | Fast day-trade candidates |
| `DAY-90` | same-day exit, max 90 minutes | Momentum/gap variants |
| `DAY-EOD` | same-day exit by 15:15 | Only when the hypothesis requires full-day carry |
| `SWING-10080` | overnight carry, max 10080 minutes | Current swing-support survivor contract |
| `SWING-OPEN` | overnight carry, strategy/stop/take exit without minute cap | Analysis only unless explicitly promoted |

First execution batch:

- Run all rows under `U1-S1-COST-BASE`.
- Any row with positive base PnL, continuity pass, and acceptable drawdown gets
  `COST-2X`.
- Any strategy family that materially improves under `U1-S1` but fails 2x
  cost may receive one documented derivative adjustment before rejection.
- `U2`, `U3`, or `S2` runs are allowed only after the `U1-S1` baseline is
  recorded, so the universe/scouter effect is measurable.

Classify every strategy-contract rule:

- `backtest-exact`
- `backtest-conservative-approx`
- `field-only-measurement`
- `missing`
- `different-from-field`

The contract classification covers all behavior that can change trade
selection, entry, exit, sizing, holding, risk, or report interpretation. At
minimum, classify:

- universe rule, universe refresh cadence, and metadata availability timing;
- scan cadence, decision cadence, and signal timestamp semantics;
- indicator lookbacks, warmup, stale-data, missing-data, and corporate-action
  handling;
- entry trigger, order timing, order type, fill price, partial-fill policy, and
  retry or timeout behavior;
- exit trigger, stop/take ordering, day-end exit, overnight carry, forced exit,
  and gap behavior;
- sizing, cash reservation, whole-share constraints, slot sharing, max exposure,
  and blocked-capital behavior;
- daily loss fuse, stop-loss count, blacklist, halt, suspension, disconnected
  session, and other safety behavior;
- logging, continuity gate, invalid-trade exclusion, and performance metric
  selection.

Any `different-from-field` rule that affects candidate selection, trade timing,
position sizing, risk, or exits changes the strategy meaning. Treat it as a hard
reject until the backtest contract is changed, the field contract is changed, or
the candidate is explicitly versioned as a different strategy.

Classify every parameter:

- `backtest-exact`
- `backtest-approx`
- `field-only`
- `missing`

Classify every data input:

- `available`
- `additionally-collectible`
- `field-only`
- `defer-abandon`

Candidates whose core alpha depends on `field-only` or `missing` inputs should
be rejected, redesigned, or kept as field-rehearsal analysis only.

Each candidate record must also include:

- field-test decision cadence, such as per-minute, near-close, daily, or
  overnight;
- old-plan baseline controls that apply to the candidate, with exact,
  approximate, missing, and field-only classifications;
- universe module ID and scouter module ID, with module-specific parameter
  boundaries and feasibility classification;
- intended order and fill model;
- field-only safety controls that must not be credited to backtest PnL;
- known data-source differences between historical Daishin input and later
  promoted/field data;
- universe construction timing and metadata availability;
- allowed default-only, coarse-sweep, and optimizer parameter boundaries.

## Step 4: Default Backtest Or Coarse Survival Sweep

A candidate does not automatically go to an optimizer.

Run strategy-level tests before portfolio-level tests. Day-trade and swing
strategies must first be evaluated separately so one strategy cannot hide the
weakness of another. In strategy-level tests, capital that belongs to a
different engine is recorded as idle or reserve, not as performance-producing
capital.

Use a default-value backtest when the core parameters are explainable from
market structure, account constraints, or execution rules. Examples:

- KRW 1,000,000 starting equity
- scheduled external capital contributions, such as weekly KRW 100,000 seed
  increases, separated from trading PnL
- variable slot count derived from deployable account equity and per-slot
  capital caps, rather than a fixed slot count chosen after seeing results
- fixed risk per trade
- whole-share or approved quantity step sizing
- per-slot deployed-capital caps when needed for slippage control
- excess day-trade capital recorded as idle/reserve during day-trade-only tests
  until an approved swing strategy is tested separately
- explicit day-end exit or approved overnight carry
- predeclared fee/slippage assumptions
- predeclared field-test decision cadence and order timing

Capacity and slippage-limit seed checks:

- These checks are stress tests, not optimizers.
- `MAX-SLOT-SEED` verifies whether the strategy survives when the account is
  large enough to use the maximum allowed slot count.
- `SLIP-LIMIT-STRESS` verifies whether the strategy survives under a documented
  conservative slippage/capacity assumption. Historical Daishin CSV bars
  currently lack order-book depth, queue position, partial-fill, and real
  bid/ask pressure fields, so this gate cannot prove actual slippage.
- Real slippage, partial fill, timeout, cancel/retry, and order-book pressure
  remain `field-only-measurement` items until field rehearsal logs exist.

Use a coarse survival sweep only when a parameter's useful range cannot be
derived from the hypothesis alone but can be bounded in advance. Examples:

- ATR band
- pullback band
- liquidity threshold
- recent-return threshold
- impulse-volume multiple

The coarse sweep is not an optimizer. It answers whether a broad, explainable
region survives. It must not select a single sharp best point as a candidate.

## Step 5: Reject Or Keep Before Optimization

Apply the alignment gate from
[`strategy-fieldtest-alignment.md`](strategy-fieldtest-alignment.md) before
using performance results. Hard reject conditions override positive backtest
PnL. Candidates below `60%` alignment must not enter optimization. Candidates in
the `60-69%` band require documented gap mitigation before optimizer entry.

Reject or redesign a candidate before optimization when:

- any strategy-contract rule that affects trade selection, timing, sizing, risk,
  or exits is `different-from-field`;
- default/coarse results are negative under base assumptions;
- trade count is too low to interpret;
- performance depends on one or two outlier trades;
- continuity-invalid trades materially drive PnL;
- 2x cost, gap, or stop-first stress erases the edge;
- drawdown, worst day, or worst month is incompatible with the KRW 1,000,000
  seed account;
- the observed trade log does not match the candidate hypothesis;
- required parameters or data cannot be represented in backtest without
  changing the strategy meaning;
- the backtest relies on a data-source behavior that is not expected to exist in
  the later field-test source;
- the strategy requires execution behavior that is only available as a
  field-only safety control;
- the universe is selected using future availability, future liquidity, or
  metadata that would not have been known at the simulated decision time.

Keep a candidate for limited optimization only when:

- no hard reject condition applies;
- alignment is `>= 70%`, or a documented update raises it to that level after
  gap mitigation;
- the hypothesis is still visible in the trade log;
- base and stress results are not fragile;
- the candidate has enough trades for the chosen horizon;
- field-only controls are not being credited for backtest performance;
- the required data and parameter classes are recorded.

If no day-trade candidate or no swing candidate survives the strategy-level
gate, do not proceed to portfolio integration. Rebuild or revise the candidate
set for the missing class and repeat Steps 2 through 5. Candidate rebuilds must
start from a new or versioned market hypothesis, not from unrecorded parameter
expansion.

## Step 6: Limited Optimizer Entry

Optimization is allowed only for kept candidates.

Rules:

- Parameter ranges must be documented before the optimizer runs.
- Ranges must be justified by the hypothesis, data resolution, or execution
  constraints.
- The optimizer may tune only the candidate's declared parameters.
- The decision cannot rely on the single best parameter point.
- A robust neighborhood is more important than peak PnL.
- New parameters discovered after seeing results create a new candidate version,
  not an unrecorded extension of the same run.

## Step 7: Locked Revalidation

After selecting a parameter region, lock the candidate and rerun:

- prior-only walk-forward replay;
- base and 2x cost stress;
- gap/stop-first stress where applicable;
- continuity-valid-only performance review;
- universe or symbol-set robustness check;
- data-source and universe-construction gap review;
- execution-gap review that separates modeled fills from field-only behavior;
- worst day, worst month, and max drawdown review;
- report analysis using
  [`backtest-report-analysis.md`](backtest-report-analysis.md).

Only after this stage may a result be called a backtest research candidate.

## Step 8: Portfolio Integration

Run portfolio-level integration only after at least one day-trade strategy and
at least one swing strategy have passed their own strategy-level validation.
The survivor-level `MAX-SLOT-SEED` and `SLIP-LIMIT-STRESS` checks must be
recorded first. A preliminary portfolio run made before those checks is kept as
reference evidence only.
This stage tests the real operating portfolio, not the standalone edge of one
strategy.

Portfolio integration must include:

- day-trade and swing capital allocation rules;
- day-trade per-slot cap and variable slot-count formula;
- excess day-trade capital routed to idle/reserve unless an approved swing
  strategy is active;
- same-symbol interlock across day-trade and swing engines;
- whole-account daily loss fuse, MDD fuse, and cash accounting;
- separate reporting for external capital contributions, day-trade PnL, swing
  PnL, idle/reserve cash, and total equity.

Do not use portfolio integration to rescue a weak standalone strategy. If a
strategy fails its own validation, it must be rejected, redesigned, or kept as
analysis-only before any combined portfolio run.

## Step 9: Field DB And Periodic Strategy Diversification

The current integrated portfolio is a first operating portfolio, not the final
strategy universe. It is valid only inside the capacity boundary proven by the
current evidence:

- day-trade `C-IDMOM-D3-U1-S1`: up to two concurrent KRW `10,000,000` slots
  after the Plan A exact two-slot check;
- swing `F-SUP-U1-S1`: up to five KRW `10,000,000` slots in the current Plan A
  integration;
- excess capital beyond validated strategy capacity must stay idle/reserve
  until another strategy passes the same validation gates.

Classify operating plans explicitly:

- `Plan B`: the currently validated fallback/safety portfolio. It uses one
  concurrent day-trade slot and up to five swing slots. This plan is available
  for field-test continuation because base, 2x cost, capacity, and continuity
  gates have passed.
- `Plan A`: the preferred target portfolio. It requires at least two concurrent
  day-trade slots plus up to five swing slots, for a target validated operating
  ceiling of KRW `70,000,000`. The current Plan A evidence passes exact
  two-slot day-trade standalone validation and integrated base/2x-cost
  portfolio validation with `day=2`, `swing=5`, and total max slots `7`.

Plan A fallback/rebuild rule:

- Keep Plan B as the conservative validated fallback.
- Treat Plan A as available only while the exact two-slot day-trade leg and the
  combined two-day-slot/five-swing-slot portfolio remain within their latest
  base-cost, 2x-cost, continuity, capacity, and field-alignment gates.
- If future revalidation breaks the two-slot day-trade leg or integrated Plan A,
  fall back to Plan B and restart the day-trade rebuild loop.
- Capital above Plan A's validated capacity remains idle/reserve rather than
  being forced into unvalidated strategies.

When field testing or long-running operation begins, persist the complete
decision and execution database needed for future revalidation. At minimum this
DB must retain:

- universe snapshots and prior-only inputs used at selection time;
- all scouter candidates, not only entered symbols;
- signal score, reason, strategy ID, universe ID, scouter ID, and parameter
  version;
- submitted order, intended price, fill price, partial fill, cancel, timeout,
  rejection, and retry evidence where available;
- configured API call budget, estimated calls, observed calls, and rate-limit
  breach or throttle events;
- expected slippage versus realized slippage;
- bid/ask spread, depth, queue, 체결강도, or other order-book/field-only
  execution-quality fields when available;
- slot assignment, day/swing group, cash reserve, contribution, and realized
  PnL separated by strategy;
- interlock, fuse, stop, cooldown, and invalid-data events.

## Step 10: Plan A Field-Dry-Run Readiness

The next Ralph stage must convert the validated Plan A backtest into a
field-dry-run package. This is still no-order, no-broker-action work. The
purpose is to make the live-like decision process observable before any capital
is placed in the account.

Detailed execution requirements are maintained in
[`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md).
The strict parameter contract, backtest fallback trigger list, and rerun test
matrix are maintained in
[`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md).

Plan A operating baseline:

- day strategy: `C-IDMOM-D3-U1-S1`, max two concurrent KRW `10,000,000` slots;
- swing strategy: `F-SUP-U1-S1`, max five concurrent KRW `10,000,000` slots;
- total validated operating ceiling: KRW `70,000,000`;
- weekly external contribution assumption: KRW `100,000`;
- Plan B remains the conservative fallback: one day slot plus up to five swing
  slots.

Backtest fallback rule:

- If the active package, day/swing strategy IDs, slot caps, cost assumptions,
  continuity evidence, or final-applied `SignalIntent` exits cannot be matched
  to [`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md),
  stop dry-run promotion and rerun the minimum Plan A backtest matrix before
  using any result as operating evidence.
- Do not resolve a parameter mismatch by editing report values or by treating
  `phase2_parameters` as the full final-applied ledger. Rebuild the evidence
  from the strict matrix when doubt remains.

Old-plan interlock rules that must be carried forward:

- First-in, first-served symbol interlock: if a symbol is currently held, every
  new entry signal for that same symbol is skipped, regardless of day/swing
  origin.
- Day-to-swing same-day reuse is allowed only when the morning day position has
  already been fully closed without overnight carry and the symbol later
  appears as a 15:15 swing target.
- If the day time-cut liquidation and the 15:15 swing entry target collide for
  the same symbol, skip the swing entry and place that symbol on a one-trading-
  day cooldown.
- During the 15:15 swing transaction window, apply lock-step sequencing so day
  and swing engines cannot mutate the same symbol or account state
  concurrently.

Old-plan operating rules that must be assessed before dry-run:

- pre-open universe pipeline: prior-day batch filtering, then opening survival
  checks for existing swing positions;
- swing gap-down defense: existing swing positions require opening checks for
  trend-break and hard-stop gap risk before new scans consume slots;
- regime budget switch: bull uses full allocated budget, range reduces new
  entry budget, bear blocks new swing entries and allows only explicitly
  validated defensive day logic;
- day slot reload fuse: a day slot can reload after an exit, but repeated same-
  day stop losses shut that slot down for the rest of the session;
- day and swing exit policies differ and must not be silently merged;
- account-level daily loss and MDD fuses must block new buys, while preserving
  exit monitoring;
- every skip, cooldown, lock-step event, and blocked order decision must be
  persisted to the dry-run DB.
- API calls must be budgeted before field-data dry-run. Local CSV dry-run must
  record a rate-limit contract even though it makes zero external API calls.
- C: drive free space is constrained, so field dry-run must not store full raw
  polling responses continuously. Store strategy-improvement evidence by
  default: scouter decision snapshots, candidate ranks, feature values,
  pass/fail reasons, API metadata, throttle events, virtual orders/fills,
  position/cash/slot/sleeve state, risk fuses, checkpoints, and daily reports.
  Raw burst capture is optional, disabled by default, limited to event windows,
  and governed by short TTL plus size caps.

Storage guardrail defaults:

- dry-run DB and local logs soft cap: 5 GB;
- raw burst hard cap: 500 MB to 1 GB, oldest-first deletion;
- raw burst TTL: 1 to 3 days if enabled;
- C: free space below 20 GB: raise warning;
- C: free space below 10 GB: disable raw burst and keep snapshot/summary logs
  only;
- C: free space below 5 GB: protective mode, blocking nonessential capture.

Field monitor and parallel observation rule:

- Field dry-run must use a single read-only market snapshot stream per polling
  cycle, then fan that stream out to primary and shadow no-order engines.
  Parallel engines must not create parallel API polling load.
- Primary lane: current actual seed plan, KRW `1,000,000` start plus weekly KRW
  `100,000`. This is the only lane eligible for no-order field continuation
  decisions.
- Shadow lanes: KRW `2,000,000`, KRW `50,000,000`, KRW `70,000,000`, and
  slippage-proxy stress observation. These lanes are for future-capital and
  strategy-revalidation evidence only.
- Every monitor cycle must preserve `order_hard_block=true` and
  `ready_for_broker_or_order_transmission=false`; shadow results cannot enable
  orders, account actions, broker readiness, or credential handling.
- Monitor outputs must include `current-status.json`, scenario reports, and a
  post-close daily review artifact so an operator or Codex session can resume
  review without relying on a live AI process.

Capital split and seed-comparison checks:

- The archived plan uses a `40%` day / `60%` swing engine allocation, but the
  validated Plan A backtest used shared slots with group caps. The next Ralph
  stage must explicitly compare these allocation models before treating field
  dry-run behavior as final:
  1. shared-slot baseline with `day=2`, `swing=5`, and KRW `10,000,000` slot
     caps;
  2. 40/60 separated day/swing budget sleeves;
  3. conservative alternatives such as 30/70 or 50/50 only if documented as
     sensitivity checks, not optimizer-selected production parameters.
- Starting seed must be compared at KRW `1,000,000` and KRW `2,000,000`, both
  with the weekly KRW `100,000` contribution schedule. The comparison is not a
  profitability hunt; it answers whether the same Plan A operating rules are
  feasible with small whole-share sizing, cash reserve, and split allocation.
- If KRW `1,000,000` cannot support simultaneous day/swing operation without
  pathological order sizing, document the minimum viable dry-run observation
  capital and keep sub-threshold operation in observation-only mode.

Dry-run success criteria:

- at least 10 trading days of no-order dry-run can run with hard-blocked order
  transmission and complete decision logs;
- 20 trading days remains the recommended stabilization target before writing
  any small-capital field-start decision record;
- daily reports reconcile universe, scouter, interlock, skipped signals,
  virtual orders, virtual fills, cash reserve, and strategy-group exposure;
- UI alert requirements include dry-run day count, 10-day review, 20-day
  stabilization, capital thresholds, cooldown events, and blocked deployment
  above the validated ceiling.

Immediate deliverable status:

- produced and keep current the Plan A dry-run readiness package, including
  operating sequence, old-plan gap mapping, dry-run DB/log contract, capital
  model comparison, success criteria, and implementation work units.
- implemented the first no-order DB ledger increment for Plan A dry-run
  sessions and ordered decision events.
- recorded the bounded Plan A sensitivity decision as a conservative
  baseline-kept artifact, not as a broad optimizer.
- implemented the local multi-session dry-run increment with virtual cash
  reconciliation, opening survival carry evidence, checkpoint events, and
  API rate-limit contract evidence.
- extended the local no-order infrastructure with scouter decision snapshots,
  virtual position close events, realized/unrealized virtual PnL snapshots,
  daily portfolio state, storage guardrail checks, and latest open-position DB
  recovery evidence.

Status-language correction: these bullets mean implemented, verified, or
produced inside the current local/no-order boundary. They do not mean
operational field readiness. In particular, news/DART collection, market-hours
KIS polling, full dry-run resume, UI alerts, real fill/slippage verification,
and live/paper order capability remain incomplete unless a later artifact says
they reached the `Operational` or `Approval-ready` status defined in
[`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md).

Create revalidation checkpoints on both capital and time:

- capital checkpoints: KRW `10,000,000`, KRW `30,000,000`, KRW `50,000,000`,
  KRW `70,000,000`, then every material increase beyond KRW `70,000,000`;
- time checkpoints: monthly execution-quality review, quarterly strategy
  revalidation, and semiannual or data-sufficient candidate rebuild;
- event checkpoints: material slippage drift, drawdown breach, repeated
  continuity/data failures, or field behavior that differs from backtest
  assumptions.

At each checkpoint:

1. rerun current strategy validation on the expanded field DB;
2. compare backtest-estimated and realized slippage/fill quality;
3. reassess whether current slot caps remain valid;
4. test new strategy candidates only with documented hypotheses and the same
   `strategy x universe x scouter` matrix discipline;
5. add a new strategy to the live/field portfolio only after it passes base,
   2x cost, continuity, capacity, and field-alignment gates.

For KRW `70,000,000` and above, do not increase exposure merely because account
equity grew. If no additional strategy survives, keep surplus capital idle or
reserved. Diversification must come from validated strategy evidence, not from
adding failed strategies for appearance of diversification. Plan B still marks
the more conservative KRW `50,000,000` fallback boundary.

UI requirement: when the operator dashboard is built, include visible
checkpoint alerts for capital, time, event, and dry-run triggers. These alerts
must show the trigger reason, required revalidation action, last completed
validation artifact, dry-run day count, order-hard-block status, and whether
excess capital is currently blocked from deployment.

## Stop Conditions

Stop and revise the plan when:

- the pipeline trust audit blocks most candidate classes;
- the required data cannot be collected within the approved read-only market
  data boundary;
- the optimizer is needed to make every candidate look viable;
- field-only assumptions are driving the apparent edge;
- verification or report generation is not reproducible;
- the work starts drifting toward paper trading, live trading, broker orders,
  account actions, or credential handling.

Do not stop merely because the first day-trade or swing candidate fails. A
failed candidate triggers the rebuild/retest loop for that missing strategy
class unless the blocker is a data, pipeline, or safety boundary.

## Immediate Next Deliverables

1. Keep the minimal pipeline trust audit in
   [`strategy-pipeline-trust-audit.md`](strategy-pipeline-trust-audit.md)
   current as implementation and data evidence changes.
2. Maintain the field-test alignment assessment in
   [`strategy-fieldtest-alignment.md`](strategy-fieldtest-alignment.md).
3. Keep the Plan A final-combo sensitivity record current before treating Plan
   A parameters as field-dry-run defaults. This is not a profit-maximizing
   optimizer. Keep `C-IDMOM-D3-U1-S1` and `F-SUP-U1-S1` as the baseline and
   use only narrow, predeclared perturbations for robustness:
   - day: profit target, hard stop, max holding minutes, liquidity/session
     threshold, and VWAP/return confirmation within the documented Plan A
     hypothesis;
   - swing: support band, RSI cap, volume-ratio cap, holding/exit window, and
     universe/scouter threshold within the documented F-SUP hypothesis;
   - portfolio: base and 2x cost, continuity, trade-count collapse/explosion,
     MDD degradation, field-alignment degradation, and exact day/swing group
     caps.
   Current status: default values remain preferred. A perturbation may be
   carried as candidate B only if it improves robustness
   without worsening field alignment, cost stress, continuity, or risk. Record
   the result as `keep default`, `candidate B for dry-run observation`, or
   `reject`. Do not run a broad optimizer unless the sensitivity pass exposes a
   specific predeclared parameter uncertainty that cannot be resolved by the
   narrow sweep.
4. Keep
   [`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md)
   current as the no-order dry-run operating contract.
5. Keep the strict Plan A parameter contract and rerun matrix in
   [`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md)
   current. If backtest consistency is questioned, use that matrix as the
   fallback rerun baseline before trusting the old reports.
6. Keep durable position-state and virtual realized/unrealized PnL
   reconciliation current as the dry-run ledger evolves. The current local
   runner records close events, PnL snapshots, portfolio state, storage
   guardrails, and latest open-position DB recovery evidence; the next field
   dry-run step must replace local CSV polling estimates with measured read-call
   budgeting before any external data loop is allowed.
6. Compare shared-slot Plan A, 40/60 separated sleeves, and documented
   sensitivity cases only for feasibility; do not optimizer-select an
   allocation ratio from the current in-sample data.
7. Compare KRW `1,000,000` and KRW `2,000,000` starting seed with weekly KRW
   `100,000` contributions to determine the minimum viable simultaneous
   day/swing dry-run start.
8. Run at least 10 no-order dry-run trading days before writing any
   small-capital field-start decision record, and keep 20 trading days as the
   recommended stabilization target. A field-start decision record does not
   authorize live trading, paper trading, broker connection, account action,
   credential handling, or order transmission; those require a separate
   user-approved plan.
9. Defer UI implementation until the dry-run DB produces stable checkpoint
   events. The later operator UI must consume these events rather than invent a
   separate alert source.
10. Before any field API dry-run is allowed, replace the local `local-csv`
    API-rate-limit placeholder with measured read-call budgeting and throttle
    evidence. Any breach blocks promotion.
