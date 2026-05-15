# Plan A Parameter Contract Matrix

Date: 2026-05-13

This document is the strict parameter contract for the current no-order dry-run
candidate. It exists so that any backtest consistency doubt causes a controlled
backtest rerun instead of reuse of ambiguous reports.

Core principle:

- No inferred parity. Strategy, code, report, and dry-run state must match by
  explicit evidence.
- A positive historical report is not enough for promotion when final-applied
  parameters are only inferred from code.
- `phase2_parameters` is not the final parameter ledger for strategies that
  apply per-signal `SignalIntent` overrides.
- If exact evidence is missing, classify the item as `rerun-required` or
  `ledger-required`; do not classify it as pass.

## Active Package

Active dry-run package: `plan-a-idmom-d3-fsup-u1s1`

Source of truth:

- Package wiring: `src/zurini/dry_run.py`
- Current dry-run status: `reports/dry-run/current-status-2026-05-13.json`
- Backtest result matrix: `docs/strategy-matrix-results.md`
- Plan A run notes: `docs/strategy-plan-a-ralph-run-20260511.md`

Do not treat `A-DAY-v2` as part of this package. It is an older/rejected
candidate family for the current dry-run context.

## Strategy Contract

| Layer | Contract value | Source | Acquisition time | Backtest treatment | Dry-run treatment | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Package ID | `plan-a-idmom-d3-fsup-u1s1` | `PLAN_A_PACKAGE_ID` | dry-run startup | represented by Plan A portfolio reports | required scenario package ID | evidence-pass |
| Day leg | `C-IDMOM-D3-U1-S1` | `build_plan_a_strategy_package()` | package build | `intraday-momentum` reports | portfolio day signal group | evidence-pass |
| Swing leg | `F-SUP-U1-S1` | `build_plan_a_strategy_package()` | package build | `swing-support` reports | portfolio swing signal group | evidence-pass |
| Fallback package | `plan-b-idmom-d3-fsup-u1s1` | `build_plan_a_strategy_package()` | package build | fallback analysis only | fallback activation path only | evidence-pass |
| Total slots | `7` | `build_plan_a_strategy_package()` | package build | Plan A portfolio `max_open_positions=7` | `_DryRunState.has_slot()` | evidence-pass |
| Day slots | `2` | `build_plan_a_strategy_package()` | package build | `signal_group_max_open_positions.day=2` | group cap `day` | evidence-pass |
| Swing slots | `5` | `build_plan_a_strategy_package()` | package build | `signal_group_max_open_positions.swing=5` | group cap `swing` | evidence-pass |
| Slot capital cap | KRW `10,000,000` | package/config | run config load | `slot_capital_cap=10000000` | virtual capital feasibility | evidence-pass |
| Operating ceiling | KRW `70,000,000` | package | package build | Plan A 70M reports | shadow 70M scenarios | evidence-pass |
| Weekly contribution | KRW `100,000` | package/config | run config load | `weekly_contribution=100000` | multi-session week boundary | evidence-pass |
| Capital mode | `shared-slot` | backtest config | backtest startup | shared-slot portfolio reports | shared-slot budget case | evidence-pass |
| Intrabar policy | `conservative` | backtest config | backtest startup | all gate reports | dry-run does not prove fills | evidence-pass |
| Ambiguous intrabar policy | `stop-first` | backtest config | backtest startup | all gate reports | dry-run does not prove fills | evidence-pass |
| Order authority | no-order only | field monitor status | dry-run status build | not applicable | `order_hard_block=true` | evidence-pass |

## Leg Parameters

The portfolio strategy applies final per-leg exit parameters through
`SignalIntent`, so `phase2_parameters` is a run-level snapshot, not a complete
per-signal final-applied ledger.

| Parameter | Day `C-IDMOM-D3-U1-S1` | Swing `F-SUP-U1-S1` | Source | Acquisition time | Consistency rule |
| --- | --- | --- | --- | --- | --- |
| Strategy class | `IntradayMomentumContinuationStrategy` | `SwingSupportStrategy` | `IntradayMomentumSwingSupportPortfolioStrategy` | strategy construction | must match package leg IDs |
| Entry window | `10:00`-`13:30` | first accepted snapshot at or after `15:15` | strategy constructor | strategy construction | rerun if report/default obscures the final value |
| Universe/liquidity | avg value `50,000,000,000`; ATR ratio `0.03`; session value `1,000,000,000`; bid/ask ratio `2.0` | SMA window `20`; volume window `5` | strategy constructor | strategy construction | rerun if data feed cannot support required fields |
| Momentum/support trigger | day return `0.035` to `0.12`; VWAP distance `0.004` | support band `0.018`; volume ratio `0.2`; RSI `<58` | strategy constructor | strategy construction | rerun if reports do not encode or code changes these values |
| Profit target | `0.08` | `0.03` | `SignalIntent` exit policy | signal creation | final applied value overrides run-level config |
| Hard stop | `-0.018` | `-0.03` | `SignalIntent` exit policy | signal creation | final applied value overrides run-level config |
| Max holding | `180` minutes | `10080` minutes | `SignalIntent` exit policy | signal creation | final applied value overrides run-level config |
| Day-end exit | `true` | `false` | `SignalIntent` exit policy | signal creation | final applied value overrides run-level config |
| Signal group | `day` | `swing` | `SignalIntent` exit policy | signal creation | required for group caps |
| Score ordering | strategy-provided `SignalIntent.score` | strategy-provided `SignalIntent.score` | strategy signal | same timestamp signal selection | must remain `S1` score-ranked behavior |

Day entry-window interpretation:

- The `10:00`-`13:30` day window is accepted evidence for the current
  `C-IDMOM-D3-U1-S1` Plan A package, not isolated proof that this is the
  universally optimal day-trade time window.
- The archived old strategy documents support broad intraday monitoring from
  the open through the afternoon, but they do not independently justify the
  exact `10:00`-`13:30` boundary.
- If the Plan A day leg sees an otherwise valid day-entry condition before
  `10:00`, the intended result is `hold` with reason `entry-window`. Broadening
  this window is a strategy-parameter change and requires rerunning the strict
  Plan A matrix before promotion.
- The boundary is inclusive through `13:30`; an otherwise valid `13:30` signal
  may enter, while the same signal at `13:31` is blocked as `entry-window`.

## Backtest Gate Evidence

These are the current accepted reports. They are evidence, not mutable state.

| Gate | Report | Cost | Trades | Net PnL | Max drawdown | Continuity | Verdict |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| Day standalone | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-observed/report.json` | base | 90 | `1057769.923267116634250000000` | `-0.08222504637558371408521137252` | `passed; 180 checked, 0 failed, 0 missing` | pass |
| Day standalone | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-cost2x-observed/report.json` | 2x | 90 | `617923.8267871056960000000000` | `-0.08669863366460501452749652873` | `passed; 180 checked, 0 failed, 0 missing` | pass |
| Swing standalone | `reports/phase2/strategy-ralph/f-swing-support-tight-common-score-ranked-contract-observed/report.json` | base | 24 | `917729.0946416170473750000000` | `-0.04082690498506922882026179563` | `passed; 48 checked, 0 failed, 0 missing` | pass |
| Swing standalone | `reports/phase2/strategy-ralph/f-swing-support-tight-common-score-ranked-cost2x-observed/report.json` | 2x | 24 | `826255.4709782356100000000000` | `-0.04097607039368592122288754183` | `passed; 48 checked, 0 failed, 0 missing` | pass |
| Day Plan A capacity | `reports/phase2/strategy-ralph/plan-a/c-idmom-d3-u1s1-70m-exact2slot-cost2x-observed/report.json` | 2x | 127 | `891223.5614224796360000000000` | `-0.03262582970855858591154413330` | `passed; 254 checked, 0 failed, 0 missing` | pass |
| Plan A portfolio | `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-base-observed/report.json` | base | 155 | `3113880.235951499359875000000` | `-0.02041719768857436654081391471` | `passed; 310 checked, 0 failed, 0 missing` | pass |
| Plan A portfolio | `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-cost2x-observed/report.json` | 2x | 155 | `797425.2753183808390000000000` | `-0.02391565633831140121910706709` | `passed; 310 checked, 0 failed, 0 missing` | pass |

## Evidence Classification

Use only these classifications:

| Classification | Meaning | Allowed use |
| --- | --- | --- |
| `evidence-pass` | Exact code/report/status evidence matches this contract. | May support no-order observation. |
| `ledger-required` | Code evidence exists, but final-applied runtime values are not recorded in a replayable parameter ledger. | Blocks operating promotion until ledger is added or backtest is rerun with manifest evidence. |
| `rerun-required` | Required evidence is missing, ambiguous, stale, or contradictory. | Stop promotion and rerun the strict matrix. |
| `analysis-only` | Useful comparison, but not a validated operating input. | Cannot justify promotion. |
| `reject` | Negative, failed, or out-of-contract evidence. | Remove from current Plan A evidence set. |

## Consistency Verdict

Current verdict: `evidence-pass-for-no-order-observation`, with
`fresh-ledger-evidence-required-before-promotion`.

Meaning:

- The active dry-run package matches the validated Plan A package.
- The accepted Plan A backtest reports are positive under base and 2x cost.
- Continuity passes on the Plan A capacity and portfolio reports.
- There is no evidence that `A-DAY-v2` is active in the dry-run package.
- The remaining promotion requirement is fresh ledger evidence from the current
  operating run: final per-leg exits are applied through `SignalIntent`, so
  promotion must cite replayable event payloads rather than only
  `phase2_parameters`.

This does not invalidate no-order observation. It does block any operating
promotion until one of these is true:

1. A final-applied parameter ledger records each accepted signal's strategy ID,
   group, entry rule, exit rule, profit target, hard stop, max holding, day-end
   behavior, slot cap, and cost model.
2. The minimum rerun matrix below is rebuilt with a parameter manifest that
   records the final-applied values, not only `phase2_parameters`.

## Fallback To Backtest Rerun

Fallback is mandatory if any of these conditions occurs:

1. Active package is not exactly `plan-a-idmom-d3-fsup-u1s1`.
2. Day leg is not exactly `C-IDMOM-D3-U1-S1`.
3. Swing leg is not exactly `F-SUP-U1-S1`.
4. `A-DAY-v2` appears in the active dry-run package, current Plan A report set,
   or operating contract.
5. `phase2_parameters` and `SignalIntent` final-applied values cannot be
   reconciled to the matrix above.
6. Final-applied parameter evidence is required for operating promotion but no
   replayable ledger or manifest exists.
7. Any accepted report has non-positive net PnL under 2x cost.
8. Continuity status is missing, failed, or approximate where exact-bar is
   required.
9. Slot caps differ from day `2`, swing `5`, total `7`.
10. Cost assumptions differ from base `fee=0.00015`, `slippage=0.00050`, or 2x
   `fee=0.00030`, `slippage=0.00100` without a new plan.
11. A report has strategy-critical `default` fields that can no longer be
    resolved to exact constructor/config values.
12. The exact command, input dataset, config overrides, or generated report path
    cannot be reconstructed.
13. Dry-run data freshness, universe history, blacklist/risk-defense input, or
    snapshot contract fails closed.

If fallback triggers, do not patch the report values manually. Rebuild the
backtest result set from the strict matrix below and update
`docs/strategy-matrix-results.md` only after the rerun outputs are inspected.

## Rerun Test Matrix

Minimum rerun matrix:

| Matrix ID | Strategy | Scope | Cost | Capital | Caps | Required pass condition |
| --- | --- | --- | --- | --- | --- | --- |
| `PLAN-A-DAY-D3-U1-S1-BASE` | `intraday-momentum` | day standalone | base | KRW `1,000,000` seed and original common-universe setup | `max_open_positions=5` unless capacity test | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-DAY-D3-U1-S1-2X` | `intraday-momentum` | day standalone | 2x | KRW `1,000,000` seed and original common-universe setup | `max_open_positions=5` unless capacity test | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-SWING-FSUP-U1-S1-BASE` | `swing-support` | swing standalone | base | KRW `1,000,000` seed and original common-universe setup | `max_open_positions=5` | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-SWING-FSUP-U1-S1-2X` | `swing-support` | swing standalone | 2x | KRW `1,000,000` seed and original common-universe setup | `max_open_positions=5` | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-DAY-D3-70M-2SLOT-2X` | `intraday-momentum` | day capacity | 2x | KRW `70,000,000` plus KRW `100,000` weekly contribution | day `2` slots, KRW `10,000,000` slot cap | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-PORT-DAY2-SWING5-70M-BASE` | `portfolio-idmom-swing-support` | integrated portfolio | base | KRW `70,000,000` plus KRW `100,000` weekly contribution | day `2`, swing `5`, total `7`, KRW `10,000,000` slot cap | positive PnL, exact continuity, command recorded, parameter manifest recorded |
| `PLAN-A-PORT-DAY2-SWING5-70M-2X` | `portfolio-idmom-swing-support` | integrated portfolio | 2x | KRW `70,000,000` plus KRW `100,000` weekly contribution | day `2`, swing `5`, total `7`, KRW `10,000,000` slot cap | positive PnL, exact continuity, command recorded, parameter manifest recorded |

Each rerun output must include or be accompanied by a manifest with:

- exact command and working directory;
- input dataset root and date range;
- strategy ID and strategy class;
- all strategy thresholds listed in the leg parameter table;
- final-applied exit parameters from `SignalIntent`;
- slot/capital/risk controls;
- fee and slippage model;
- continuity audit mode and result;
- report output path and content hash.

Optional robustness checks may be run only after the minimum matrix passes:

- day one-slot fallback;
- Plan B one-day-slot portfolio;
- slippage-limit 10M/20M/30M sensitivity;
- U2/U3 field-alignment proxies, clearly labeled analysis-only when the
  historical dataset lacks true field values.

## Update Rule

After a rerun:

1. Record exact command, input dataset, config overrides, and report path.
2. Update `docs/strategy-matrix-results.md` with the new result row.
3. Update this document if any strict parameter changed.
4. Keep the old report path as historical evidence; do not overwrite it unless
   the report generator itself owns the target output directory.
5. Do not resume dry-run promotion if any required row is missing, negative,
   continuity-failed, command-missing, or manifest-missing.
