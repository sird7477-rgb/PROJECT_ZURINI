# Strategy Ralph Run 2026-05-10

This record captures the first Ralph execution pass after the reset plan.

## Goal

Ralph completion target is integrated portfolio pass. Portfolio integration can
open only after at least one day-trade strategy and one swing strategy pass
strategy-level validation under the field-test-aligned capital and execution
contract.

## Engine Contract Added

- KRW 1,000,000 start equity can be combined with weekly external
  contributions.
- Backtest reports now separate trading `net_pnl` from
  `external_contributions`.
- Shared-slot runs can derive variable slot count from account equity and a
  per-slot capital cap.
- `backtest-csv` records `variable_slot_count`, `slot_capital_cap`,
  `weekly_contribution`, and `day_end_exit_time` in `phase2_parameters`.
- Intraday candidates can force a same-session day-end exit at a configured KST
  cutoff such as `15:15`.

## Strategy-Level Runs

### A-DAY-U1-S1 Field-Contract Proxy

- Command output:
  `reports/phase2/strategy-ralph/a-day-u1-s1-field-contract-fuse-observed/report.json`
- Dataset: `reports/phase2/observed-session/observed-backtest-paths.txt`
- Capital: KRW 1,000,000 start, KRW 100,000 weekly contribution,
  whole-share sizing, shared-slot, variable slot count, KRW 10,000,000 slot cap.
- Risk fuse: stop new entries after `2` same-day hard stops or KRW `40000`
  realized daily net loss.
- Exit/cost: `15:15` day-end cutoff, conservative intrabar stop-first, base
  fee/slippage.
- Trades: `345`
- Net trading PnL: `-651388.6953824365922500000000`
- External contributions: `4800000`
- Max drawdown: `-0.2658578030596462223240405303`
- Continuity: `345` valid, `0` invalid.
- Verdict: reject/rebuild. The base run is negative and drawdown is
  incompatible with a KRW 1,000,000 seed account.

Note: this is still a proxy run because the exact prior-only U1 universe and S1
scouter modules are not implemented as separate selection artifacts.

### F Swing-Support Field-Contract Proxy

- Command output:
  `reports/phase2/strategy-ralph/f-swing-support-field-contract-fuse-observed/report.json`
- Dataset: `reports/phase2/observed-session/observed-backtest-paths.txt`
- Capital: KRW 1,000,000 start, KRW 100,000 weekly contribution,
  whole-share sizing, shared-slot, variable slot count, KRW 10,000,000 slot cap.
- Risk fuse: stop new entries after `2` same-day hard stops or KRW `40000`
  realized daily net loss.
- Carry: overnight allowed, max holding `10080` minutes.
- Exit/cost: conservative intrabar stop-first, base fee/slippage.
- Trades: `21`
- Net trading PnL: `-108512.2892107299465000000000`
- External contributions: `4800000`
- Max drawdown: `-0.1125639130982953274455417740`
- Continuity: `21` valid, `0` invalid.
- Verdict: reject/rebuild. The base run is negative and trade count is low.

## Superseded Proxy Runs

The following earlier proxy runs are retained as historical reference only
because they did not specify the daily risk fuses:

- `reports/phase2/strategy-ralph/a-day-u1-s1-field-contract-observed/report.json`
- `reports/phase2/strategy-ralph/f-swing-support-field-contract-observed/report.json`

## Ralph Fallback Runs

These runs continue the same Ralph target after the first standalone failures.
They are not portfolio candidates unless explicitly marked as passing.

### A-DAY-v2 Executable U/S Runs

- `reports/phase2/strategy-ralph/a-day-v2-u1-s1-observed/report.json`
  - Trades: `193`
  - Net trading PnL: `-454611.3017081090100000000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/a-day-v2-u1-s2-tight-observed/report.json`
  - Trades: `211`
  - Net trading PnL: `-639944.1180516321984375000000`
  - Verdict: reject/rebuild.

### VWAP/Impulse Day-Trade Family

- `reports/phase2/strategy-ralph/b-vwap-field-contract-observed/report.json`
  - Trades: `392`
  - Net trading PnL: `-908565.1922280844763750000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/c-impulse-vwap-field-contract-observed/report.json`
  - Trades: `456`
  - Net trading PnL: `-2582567.877218617533750000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/day-vwap-entry1000-field-contract-observed/report.json`
  - Trades: `374`
  - Net trading PnL: `-2426239.736399329000500000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/day-vwap-entry1100-field-contract-observed/report.json`
  - Trades: `322`
  - Net trading PnL: `-2006443.818730518210250000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/day-vwap-entry1100-1159-field-contract-observed/report.json`
  - Trades: `235`
  - Net trading PnL: `-1415288.706338446665250000000`
  - Verdict: reject/rebuild.

Loss decomposition showed a large 09:00 entry penalty, but delaying entries did
not rescue the family under the full field contract.

### Universe-Parity Correction

The full observed path list included symbols such as `A0001A0` and `A0007C0`.
That conflicts with the old-plan Tier 1 exclusion intent for preferred shares,
non-common-stock instruments, and similar exchange-risk names. A conservative
numeric common-stock path list was generated as:

- `reports/phase2/strategy-ralph/observed-backtest-paths-common-numeric.txt`
  - Paths: `1032` of `1200`
  - Rule: keep only `A[0-9]{6}.csv`

This is a field-test-alignment correction, not a PnL optimizer.

Filtered-universe reruns:

- `reports/phase2/strategy-ralph/day-vwap-entry1100-1159-common-field-contract-observed/report.json`
  - Trades: `220`
  - Net trading PnL: `-977746.955974307070000000000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/day-vwap-entry1100-1159-common-pt015hs007-field-contract-observed/report.json`
  - Trades: `284`
  - Net trading PnL: `-1000545.373864067269812500000`
  - Verdict: reject/rebuild.
- `reports/phase2/strategy-ralph/day-breakout-entry1100-1159-common-pt015hs007-field-contract-observed/report.json`
  - Trades: `316`
  - Net trading PnL: `-1465536.602524326705637500000`
  - Verdict: reject/rebuild.

Current conclusion: the VWAP/impulse pullback and breakout family has failed
the field-contract day-trade gate after full observed, delayed-entry,
common-stock, and tighter-risk variants. Do not move this family to optimizer
or portfolio integration without a new hypothesis and a new candidate record.

### Overnight/Swing Attempt

- `reports/phase2/strategy-ralph/swing-overnight-impulse-vwap-field-contract-observed/report.json`
  - Trades: `361`
  - Net trading PnL: `-2304735.145549573318500000000`
  - Verdict: reject/rebuild.

## Candidate Survivors And Stress Results

### Swing Survivor: F Swing-Support Tight Common

- Base:
  `reports/phase2/strategy-ralph/f-swing-support-tight-common-field-contract-observed/report.json`
  - Trades: `23`
  - Net trading PnL: `828683.8951287216063750000000`
  - External contributions: `4800000`
  - Max drawdown: `-0.04088198647940216814574131721`
  - Continuity: `23` valid, `0` invalid.
- 2x cost stress:
  `reports/phase2/strategy-ralph/f-swing-support-tight-common-cost2x-observed/report.json`
  - Trades: `23`
  - Net trading PnL: `741482.4530717253390000000000`
  - Verdict: keep as current swing survivor, pending portfolio integration and
    final source-gap review.

### Day-Trade Survivor Attempts

A-DAY-v2 with common-stock universe, bull-only regime, and 60-minute max
holding produced the best basic day-trade result:

- Base:
  `reports/phase2/strategy-ralph/a-day-v2-common-regime-bull-hold60-observed/report.json`
  - Trades: `183`
  - Net trading PnL: `288063.2982411240000000000000`
  - Max drawdown: `-0.09319562181920739280738439763`
  - Continuity: `183` valid, `0` invalid.
- 2x cost stress:
  `reports/phase2/strategy-ralph/a-day-v2-common-regime-bull-hold60-cost2x-observed/report.json`
  - Trades: `183`
  - Net trading PnL: `-415493.0792354102800000000000`
  - Verdict: reject as passing day-trade candidate; basic edge is too
    cost-sensitive.

Additional A-DAY-v2 filter attempts did not survive:

- `a-day-v2-common-regime-bull-hold60-session1b-observed`: base `79936.3206037428712500000000`.
- `a-day-v2-common-regime-bull-hold60-session1b-cost2x-observed`: 2x cost `-568539.1865204997400000000000`.
- `a-day-v2-common-regime-bull-hold60-session5b-observed`: base `-110911.1495854747887500000000`.
- `a-day-v2-common-regime-bull-hold60-ratio3-observed`: `0` trades.
- `a-day-v2-common-regime-bull-hold60-ratio25-observed`: `0` trades.
- `a-day-v2-common-regime-bull-rs005-hold60-observed`: base `62565.6978163147162500000000`.
- `a-day-v2-common-regime-bull-rs005-hold60-cost2x-observed`: 2x cost `-417472.7742985244900000000000`.

Current day-trade conclusion: no implemented day-trade candidate has passed
both base and 2x cost stress under the field contract. The next Ralph branch is
new day-trade candidate implementation or a materially different A-DAY
candidate record, not optimizer or portfolio integration.

## Portfolio Gate

Portfolio integration is still not opened. The run now has one passing
day-trade candidate and one passing swing candidate, but the user corrected the
workflow to require strategy/module matrix evidence before moving to portfolio
integration. Universe/scouter changes can materially alter selected trades, so
the next gate is the declared `U3-S2` comparison for the day survivor and the
declared optional `U2-S1` robustness check for the swing survivor.

## Next Ralph Step

Continue the upstream matrix before portfolio integration:

- Day-trade survivor:
  `C-IDMOM-D3-U1-S1`.
  - Base:
    `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-observed/report.json`
    with `90` trades, net trading PnL
    `1057769.923267116634250000000`, max drawdown about `-8.22%`,
    continuity `passed`, `180` checked points, `0` failed points.
  - 2x cost:
    `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-cost2x-observed/report.json`
    with `90` trades, net trading PnL
    `617923.8267871056960000000000`, max drawdown about `-8.67%`,
    continuity `passed`, `180` checked points, `0` failed points.
- Swing survivor remains `F-SUP-U1-S1` after base and 2x cost stress.
- Required next comparison: `C-IDMOM-D3-U3-S2`, then `F-SUP-U2-S1`.
- Portfolio integration opens only after those module-condition comparisons are
  recorded and no source-gap or execution-gap blocker is found.
- Swing: F swing-support tight common remains the current survivor, pending
  portfolio integration and final source-gap review. The overnight impulse VWAP
  run is rejected.
- Portfolio: implement same-symbol interlock and separate day/swing PnL
  attribution only after both standalone classes pass.

## 2026-05-11 Pullback Continuation

User requested Ralph continuation until a passing candidate exists and asked to
apply the pullback branch. Added a new day-trade implementation:

- `DaySupportPullbackStrategy`: applies the low-volume support/pullback idea as
  an intraday same-day-exit candidate.
- `ConfirmedPullbackDayStrategy`: arms on controlled A-DAY pullback, then waits
  for a later reclaim before entry.
- CLI strategies added: `day-support-pullback` and
  `confirmed-day-pullback`; `confirmed-day-pullback` also records
  `aday_reclaim_threshold`.
- Targeted verification:
  `.venv/bin/python -m pytest tests/test_backtest.py::test_day_support_pullback_strategy_enters_from_prior_support_context tests/test_csv_loader.py::test_backtest_csv_cli_accepts_phase2_parameter_overrides`
  passed.
- Targeted verification:
  `.venv/bin/python -m pytest tests/test_backtest.py::test_confirmed_pullback_day_strategy_waits_for_reclaim_before_entry tests/test_csv_loader.py::test_backtest_csv_cli_accepts_phase2_parameter_overrides`
  passed.

Pullback branch observed results:

- `day-support-pullback-common-regime-bull-1330-1445-pt015hs01-observed`:
  `133` trades, net trading PnL `-658027.4413941037618750000000`,
  continuity invalid `0`. Rejected.
- `day-support-pullback-common-regime-bull-tight-hold30-pt01hs007-observed`:
  `163` trades, net trading PnL `-902043.1303620292235125000000`.
  Rejected.
- `a-day-v2-common-regime-bull-entry1000-hold60-observed`: `197` trades,
  net trading PnL `133203.7053326240462500000000`. 2x cost stress
  `a-day-v2-common-regime-bull-entry1000-hold60-cost2x-observed` produced
  `-588468.0588719468900000000000`. Rejected.
- `confirmed-day-pullback-common-regime-bull-entry1000-reclaim002-observed`:
  `176` trades, net trading PnL `-474749.0028932464000000000000`.
  Rejected.
- `sniper-vwap-common-regime-bull-vol3x-hold60-observed`: old-plan VWAP first
  pullback with common-stock universe, bull-only regime, and 20-bar/3x volume
  impulse; `514` trades, net trading PnL
  `-412581.8383212194381250000000`. Rejected.
- `a-day-v2-common-regime-bull-entry1015-hold60-observed`: delayed A-DAY
  pullback after loss concentration at 10:00; `183` trades, net trading PnL
  `-248021.0439178297162500000000`. Rejected.

Post-pullback day-trade rebuild results:

- Added `OpeningRangeBreakoutDayStrategy`, `IntradayMomentumContinuationStrategy`,
  and `PriorMomentumContinuationStrategy` as materially different field-aligned
  day-trade candidates. They use prior-only daily universe inputs plus
  intraday-observable price, VWAP, value, and bid/ask checks.
- Targeted verification for the new strategy behaviors passed with paired CLI
  regression checks:
  - `test_opening_range_breakout_strategy_waits_for_range_then_breakout`
  - `test_intraday_momentum_strategy_enters_after_day_return_and_vwap_confirmation`
  - `test_prior_momentum_strategy_uses_previous_session_return_before_entry`
- `opening-range-breakout-common-regime-bull-r30-buf003-hold60-observed`:
  `155` trades, net trading PnL `-355770.0106180872712500000000`.
  Rejected.
- `opening-range-breakout-common-regime-bull-strict-r30-buf010-hold90-observed`:
  `0` trades, net trading PnL `0`. Too sparse / analysis-only.
- `intraday-momentum-common-regime-bull-ret03-vwap003-hold90-observed`:
  `111` trades, net trading PnL `-400358.1592407026675000000000`.
  Rejected.
- `prior-momentum-common-regime-bull-prior04-confirm005-hold90-observed`:
  `64` trades, net trading PnL `-238277.6045924766625000000000`.
  Rejected.
- `prior-momentum-common-regime-bull-strict-prior08-confirm010-hold90-observed`:
  `0` trades, net trading PnL `0`. Too sparse / analysis-only.

Current 2026-05-11 state:

- Swing survivor still exists.
- No day-trade survivor exists.
- Portfolio integration is still blocked.
- Continue from day-trade candidate redesign. Current evidence says fast
  same-day long-only strategies on this sparse observed universe are either
  negative after realistic costs or too sparse when filtered aggressively.

## 2026-05-11 Gap-Rebound Rebuild

Ralph continuation added and tested another field-aligned same-day candidate:

- `GapReboundDayStrategy`: prior-only universe gate plus opening gap-down
  context, then intraday reclaim above prior close and VWAP confirmation.
- Targeted verification passed:
  `.venv/bin/python -m pytest tests/test_backtest.py::test_gap_rebound_strategy_enters_after_gap_down_reclaim tests/test_csv_loader.py::test_backtest_csv_cli_accepts_phase2_parameter_overrides`.

Observed full-data results:

- `gap-rebound-common-regime-bull-gap005-04-reclaim001-hold90-observed`:
  `61` trades, net trading PnL `-221107.1812710345737500000000`.
  Rejected.
- `a-day-v2-common-regime-bull-intradaycarry-pt045hs02-observed`: tested
  a longer intraday carry variant of the A-DAY contract; `157` trades, net
  trading PnL `-278546.2168057043643750000000`. Rejected.

Current state after gap-rebound rebuild:

- Swing survivor still exists.
- Passing day-trade survivor still does not exist.
- Portfolio integration remains blocked.
- Next recovery action is a bounded in-memory candidate sweep that loads the
  observed bars once, then promotes any promising candidate to a formal report
  run with cost-stress validation.

## 2026-05-11 Scout-Ranked Revalidation

The shared-slot backtest engine now ranks same-timestamp entry candidates by
`SignalIntent.score` before falling back to symbol order. This is a field
alignment correction for the scout stage: when multiple candidates are
simultaneously eligible, the backtest should approximate scout selection rather
than arbitrary code ordering.

Regression evidence:

- `.venv/bin/python -m pytest tests/test_backtest.py::test_shared_slot_entry_candidates_use_signal_score_before_symbol_order tests/test_backtest.py::test_gap_rebound_strategy_enters_after_gap_down_reclaim tests/test_csv_loader.py::test_backtest_csv_cli_accepts_phase2_parameter_overrides`
  passed.
- `.venv/bin/python -m pytest tests/test_backtest.py::test_shared_slot_entry_candidates_use_signal_score_before_symbol_order tests/test_csv_loader.py::test_backtest_csv_cli_accepts_phase2_parameter_overrides`
  passed after adding swing signal scores.

Revalidation policy:

- Prior pass/fail verdicts that used shared-slot capital are now advisory.
- Re-run the existing swing survivor under the score-ranked scout contract.
- Re-run representative failed day-trade and swing strategy families under the
  same contract.
- Expand only families that materially improve; avoid brute-force rerunning
  every parameter variant on local hardware.

Score-ranked swing survivor revalidation:

- Incorrect parameter rerun
  `f-swing-support-tight-common-score-ranked-observed` produced `0` trades and
  is discarded as an operator replay error. It did not match the survivor
  contract.
- Correct survivor contract:
  `f-swing-support-tight-common-score-ranked-contract-observed`: `24` trades,
  net trading PnL `917729.0946416170473750000000`. Survivor remains valid.
- Correct survivor contract, 2x cost:
  `f-swing-support-tight-common-score-ranked-cost2x-observed`: `24` trades,
  net trading PnL `826255.4709782356100000000000`. Survivor remains valid.

Score-ranked day-trade revalidation started:

- `a-day-v2-common-regime-bull-hold60-score-ranked-observed`: `186` trades,
  net trading PnL `-61785.5033252767637500000000`. This representative A-DAY
  contract is still rejected at base cost under score-ranked scout selection.
- `sniper-vwap-common-regime-bull-vol3x-hold60-score-ranked-observed`: `524`
  trades, net trading PnL `-564972.1357949872932500000000`. VWAP/impulse
  representative remains rejected.
- `day-support-pullback-common-regime-bull-1330-1445-pt015hs01-score-ranked-observed`:
  `134` trades, net trading PnL `-685446.1998301163860000000000`.
  Day-support pullback representative remains rejected.
- `opening-range-breakout-common-regime-bull-r30-buf003-hold60-score-ranked-observed`:
  `156` trades, net trading PnL `-402218.9802788349112500000000`.
  Opening-range representative remains rejected.
- `gap-rebound-common-regime-bull-gap005-04-reclaim001-hold90-score-ranked-observed`:
  `61` trades, net trading PnL `-338169.0490264882187500000000`.
  Gap-rebound representative remains rejected.
- `prior-momentum-common-regime-bull-prior04-confirm005-hold90-score-ranked-observed`:
  `64` trades, net trading PnL `-301113.3516796469875000000000`.
  Prior-momentum representative remains rejected.
- `intraday-momentum-common-regime-bull-ret03-vwap003-hold90-score-ranked-observed`:
  `113` trades, net trading PnL `147719.0473188846200000000000`.
  This row passed base cost but failed 2x cost:
  `intraday-momentum-common-regime-bull-ret03-vwap003-hold90-score-ranked-cost2x-observed`
  produced `-441727.8223308449200000000000`.
- `confirmed-day-pullback-common-regime-bull-entry1000-reclaim002-score-ranked-observed`:
  `179` trades, net trading PnL `-412854.8833845166062500000000`.
  Confirmed pullback representative remains rejected.

Score-ranked failed swing-family revalidation:

- `swing-overnight-impulse-vwap-common-score-ranked-observed`: `344` trades,
  net trading PnL `-2301464.304907936009500000000`. The failed overnight
  VWAP/impulse swing representative remains rejected under the current
  common-stock universe and score-ranked scout contract.
- `f-swing-momentum-common-score-ranked-contract-observed`: `122` trades, net
  trading PnL `-1647183.504328558598875000000`. Swing momentum representative
  remains rejected.

### Ralph Scope Correction: Candidate Matrix Before Final Portfolio

User correction accepted: finding one swing survivor and one day-trade survivor
is only the minimum condition to start portfolio integration, not the final
strategy-selection objective.

Updated Ralph objective:

- Define a closed, field-executable candidate matrix before final selection.
- Include base strategies and their documented derivative cases.
- Include universe/scout variants as first-class strategy dimensions, not
  incidental engine details.
- Revalidate prior pass/fail outcomes whenever universe, scout ranking, cost,
  slot, or holding-contract assumptions change.
- Prefer multiple survivors per style when evidence supports them; portfolio
  integration should compare combinations rather than assume the first survivor
  is optimal.

Boundaries for "all possible cases":

- Exhaustive means exhaustive over the documented, field-executable candidate
  matrix.
- It does not mean unbounded numerical grid search or arbitrary data-mined
  parameter mutation.
- New derivative cases are allowed only when they have a stated market
  hypothesis, field-test execution contract, and measurable pass/fail gate.

Revised execution order:

1. Define strategy-family matrix: day-trade, swing, and later portfolio
   combinations.
2. Define universe/scout matrix: common-stock universe variants, liquidity and
   volatility gates, same-timestamp score ranking, and any scout score formula
   variants that can actually run in the field.
3. Run base strategy cases across the required universe/scout contracts.
4. Run derivative cases for every family that remains plausible or was
   previously materially affected by contract changes.
5. Mark survivors only after base cost, 2x cost, continuity, drawdown, and
   field-alignment gates.
6. Build and validate integrated portfolio combinations from the survivor set.

### Universe/Scout First Principle

User correction accepted: universe and scout selection are not secondary
details. The same strategy can produce materially different results depending
on these gates, so strategy validation must not proceed as if there is only one
implicit universe/scout contract.

Updated order:

1. Define the field-executable universe/scout matrix first.
2. Generate or record a stable dataset/result key for every universe/scout
   case.
3. Run strategy candidates against explicit universe/scout keys.
4. Compare strategy performance only within named universe/scout conditions.
5. Promote survivors only when the strategy edge remains acceptable under the
   selected field-aligned universe/scout contract.

Required result identity for every future report:

- strategy family and derivative id
- universe id
- scout id and score formula
- cost profile
- slot/seed policy
- holding contract
- regime/market filter
- report path and continuity status

Reason:

- Without this separation, a result can mistakenly attribute performance to the
  strategy when the effect actually came from universe construction, scout
  ranking, or slot contention.
- The correct comparison unit is therefore `strategy x universe x scout`, not
  strategy alone.

Ralph stop condition:

- Unchanged: Ralph is complete only after an integrated portfolio candidate
  passes final validation.
- The universe/scout matrix is a required upstream gate for reliable survivor
  selection, not a replacement completion condition.
