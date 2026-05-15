# Strategy Matrix Results

This file tracks the current Ralph strategy matrix as `strategy x universe x
scouter`. It is the working evidence table for survivor selection before final
integrated portfolio validation.

## Condition IDs

- `U1`: common numeric stock universe, `A[0-9]{6}` observed CSV paths.
- `S1`: score-ranked scout, using strategy-provided `SignalIntent.score` with
  symbol-order fallback.
- `COST-BASE`: fee `0.00015`, slippage `0.00050`.
- `COST-2X`: fee `0.00030`, slippage `0.00100`.

## U1-S1 Results

| Matrix ID | Style | Strategy | Cost | Trades | Net PnL | Report | Verdict |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| `A-DAY-PB-U1-S1-COST-BASE-DAY-60` | Day | `a-day-v2` | base | 186 | -61785.5033252767637500000000 | `reports/phase2/strategy-ralph/a-day-v2-common-regime-bull-hold60-score-ranked-observed/report.json` | Reject |
| `A-DAY-PB-U2-S1-COST-BASE-DAY-60` | Day | `a-day-v2` | base | 185 | -226584.9689561684912500000000 | `reports/phase2/strategy-ralph/a-day-v2-u2-liq1b-range12-regime-bull-hold60-score-ranked-observed/report.json` | Reject |
| `A-DAY-SUP-U1-S1-COST-BASE-DAY-60` | Day | `day-support-pullback` | base | 134 | -685446.1998301163860000000000 | `reports/phase2/strategy-ralph/day-support-pullback-common-regime-bull-1330-1445-pt015hs01-score-ranked-observed/report.json` | Reject |
| `A-DAY-CONF-U1-S1-COST-BASE-DAY-60` | Day | `confirmed-day-pullback` | base | 179 | -412854.8833845166062500000000 | `reports/phase2/strategy-ralph/confirmed-day-pullback-common-regime-bull-entry1000-reclaim002-score-ranked-observed/report.json` | Reject |
| `B-VWAP-U1-S1-COST-BASE-DAY-60` | Day | `vwap` | base | 524 | -564972.1357949872932500000000 | `reports/phase2/strategy-ralph/sniper-vwap-common-regime-bull-vol3x-hold60-score-ranked-observed/report.json` | Reject |
| `C-ORB-U1-S1-COST-BASE-DAY-60` | Day | `opening-range-breakout` | base | 156 | -402218.9802788349112500000000 | `reports/phase2/strategy-ralph/opening-range-breakout-common-regime-bull-r30-buf003-hold60-score-ranked-observed/report.json` | Reject |
| `C-ORB-U3-S2H-COST-BASE-DAY-60` | Day | `opening-range-breakout` | base | 157 | -240466.6507866665825000000000 | `reports/phase2/strategy-ralph/opening-range-breakout-u3s2h-regime-bull-r30-buf003-liq3b-hold60-score-ranked-observed/report.json` | Reject |
| `C-IDMOM-U1-S1-COST-BASE-DAY-90` | Day | `intraday-momentum` | base | 113 | 147719.0473188846200000000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret03-vwap003-hold90-score-ranked-observed/report.json` | Base survivor, failed 2x |
| `C-IDMOM-U1-S1-COST-2X-DAY-90` | Day | `intraday-momentum` | 2x | 113 | -441727.8223308449200000000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret03-vwap003-hold90-score-ranked-cost2x-observed/report.json` | Reject unless derivative improves cost robustness |
| `C-IDMOM-D1-U1-S1-COST-BASE-DAY-120` | Day | `intraday-momentum` | base | 0 | 0 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret04-vwap006-liq5b-ba25-hold120-score-ranked-observed/report.json` | Coverage reject |
| `C-IDMOM-D2-U1-S1-COST-BASE-DAY-120` | Day | `intraday-momentum` | base | 95 | 381745.8470633582162500000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-hold120-score-ranked-observed/report.json` | Base survivor, failed 2x |
| `C-IDMOM-D2-U1-S1-COST-2X-DAY-120` | Day | `intraday-momentum` | 2x | 95 | -173941.7196804126320000000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-hold120-score-ranked-cost2x-observed/report.json` | Reject unless final wider-target derivative improves |
| `C-IDMOM-D3-U1-S1-COST-BASE-DAY-180` | Day | `intraday-momentum` | base | 90 | 1057769.923267116634250000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-observed/report.json` | Survivor |
| `C-IDMOM-D3-U1-S1-COST-2X-DAY-180` | Day | `intraday-momentum` | 2x | 90 | 617923.8267871056960000000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-pt08-hold180-score-ranked-cost2x-observed/report.json` | Survivor |
| `C-IDMOM-D3-U3-S2-COST-BASE-DAY-180` | Day | `intraday-momentum` | base | 0 | 0 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq1b-ba25-pt08-hold180-u3s2-observed/report.json` | Analysis-only coverage reject; historical CSV has no real bid/ask pressure field |
| `C-IDMOM-D3-U3-S2H-COST-BASE-DAY-180` | Day | `intraday-momentum` | base | 90 | 618615.9686349211872500000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq3b-pt08-hold180-u3s2hist-observed/report.json` | Survivor, thin stress margin |
| `C-IDMOM-D3-U3-S2H-COST-2X-DAY-180` | Day | `intraday-momentum` | 2x | 90 | 89979.6539355785760000000000 | `reports/phase2/strategy-ralph/intraday-momentum-common-regime-bull-ret035-vwap004-liq3b-pt08-hold180-u3s2hist-cost2x-observed/report.json` | Survivor with elevated cost risk |
| `C-PRMOM-U1-S1-COST-BASE-DAY-90` | Day | `prior-momentum` | base | 64 | -301113.3516796469875000000000 | `reports/phase2/strategy-ralph/prior-momentum-common-regime-bull-prior04-confirm005-hold90-score-ranked-observed/report.json` | Reject |
| `A-GAPREB-U1-S1-COST-BASE-DAY-90` | Day | `gap-rebound` | base | 61 | -338169.0490264882187500000000 | `reports/phase2/strategy-ralph/gap-rebound-common-regime-bull-gap005-04-reclaim001-hold90-score-ranked-observed/report.json` | Reject |
| `F-SUP-U1-S1-COST-BASE-SWING-10080` | Swing | `swing-support` | base | 24 | 917729.0946416170473750000000 | `reports/phase2/strategy-ralph/f-swing-support-tight-common-score-ranked-contract-observed/report.json` | Survivor |
| `F-SUP-U1-S1-COST-2X-SWING-10080` | Swing | `swing-support` | 2x | 24 | 826255.4709782356100000000000 | `reports/phase2/strategy-ralph/f-swing-support-tight-common-score-ranked-cost2x-observed/report.json` | Survivor |
| `F-SUP-U2-S1-COST-BASE-SWING-10080` | Swing | `swing-support` | base | 11 | 689195.4905178257512500000000 | `reports/phase2/strategy-ralph/f-swing-support-tight-u2-liq1b-range12-score-ranked-contract-observed/report.json` | Survivor with lower coverage |
| `F-SUP-U2-S1-COST-2X-SWING-10080` | Swing | `swing-support` | 2x | 11 | 646640.9891915128220000000000 | `reports/phase2/strategy-ralph/f-swing-support-tight-u2-liq1b-range12-score-ranked-cost2x-observed/report.json` | Survivor with lower coverage |
| `F-MOM-U1-S1-COST-BASE-SWING-10080` | Swing | `swing-momentum` | base | 122 | -1647183.504328558598875000000 | `reports/phase2/strategy-ralph/f-swing-momentum-common-score-ranked-contract-observed/report.json` | Reject |
| `F-MOM-U2-S1-COST-BASE-SWING-10080` | Swing | `swing-momentum` | base | 117 | -1265494.608808448430500000000 | `reports/phase2/strategy-ralph/f-swing-momentum-u2-liq1b-range12-score-ranked-contract-observed/report.json` | Reject |
| `B-OVN-VWAP-U1-S1-COST-BASE-SWING-OPEN` | Swing | `vwap` | base | 344 | -2301464.304907936009500000000 | `reports/phase2/strategy-ralph/swing-overnight-impulse-vwap-common-score-ranked-observed/report.json` | Reject |
| `B-OVN-VWAP-U2-S1-COST-BASE-SWING-OPEN` | Swing | `vwap` | base | 182 | -1022132.793108429185250000000 | `reports/phase2/strategy-ralph/swing-overnight-impulse-vwap-u2-liq1b-range12-score-ranked-observed/report.json` | Reject |

## Pending Matrix Rows

- None for the current closed Ralph matrix.

## Current Survivor Set

- Swing: `F-SUP-U1-S1` passes base and 2x cost. `F-SUP-U2-S1` also passes
  base and 2x cost after applying the `U2` liquidity/volatility universe
  proxy, but coverage drops from `24` to `11` trades. `F-MOM` and
  `B-OVN-VWAP` remain rejected after `U2-S1` comparison.
- Day: `C-IDMOM-D3-U1-S1` passes base and 2x cost with continuity status
  `passed`, `180` checked points, `0` failed points, and `0` missing minutes.
  The historical-data-compatible `U3-S2H` liquidity comparison also stays
  positive under 2x cost, but the stress margin drops to
  `89979.6539355785760000000000`.

## Next Matrix Work

- The current matrix and integrated portfolio gate are complete. Next work is
  field DB design and long-running operation checkpoints: revalidate the current
  portfolio at capital/time/event triggers and add new strategies only after
  they pass the same matrix, cost, continuity, capacity, and alignment gates.

## Survivor Capacity Checks

- `C-IDMOM-D3-U1-S1-MAX-SLOT-SEED-COST-BASE`: KRW `50,000,000` start equity,
  `142` trades, net PnL `1212637.765112924980750000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-maxslot50m-base-observed/report.json`.
- `C-IDMOM-D3-U1-S1-MAX-SLOT-SEED-COST-2X`: KRW `50,000,000` start equity,
  `142` trades, net PnL `-396576.5465457953820000000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-maxslot50m-cost2x-observed/report.json`.
- `C-IDMOM-D3-U1-S1-SLIP-LIMIT-COST-2X-30M`: KRW `30,000,000` start equity,
  `142` trades, net PnL `-419451.4427881950380000000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-sliplimit30m-cost2x-observed/report.json`.
- `C-IDMOM-D3-U1-S1-SLIP-LIMIT-COST-2X-20M`: KRW `20,000,000` start equity,
  `139` trades, net PnL `-250181.8625446476960000000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-sliplimit20m-cost2x-observed/report.json`.
- `C-IDMOM-D3-U1-S1-SLIP-LIMIT-COST-2X-10M`: KRW `10,000,000` start equity,
  `127` trades, net PnL `579123.7508124624920000000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-sliplimit10m-cost2x-observed/report.json`.
- `C-IDMOM-D3-U1-S1-ONE-SLOT-COST-2X-50M`: KRW `50,000,000` start equity,
  one open day slot via `--max-open-positions 1`, `89` trades, net PnL
  `1174150.592622990606000000000`,
  `reports/phase2/strategy-ralph/c-idmom-d3-u1s1-50m-one-slot-cost2x-observed/report.json`.
- `F-SUP-U1-S1-MAX-SLOT-SEED-COST-BASE`: KRW `50,000,000` start equity,
  `30` trades, net PnL `3605192.010921330770375000000`,
  `reports/phase2/strategy-ralph/f-swing-support-tight-u1s1-maxslot50m-base-observed/report.json`.
- `F-SUP-U1-S1-MAX-SLOT-SEED-COST-2X`: KRW `50,000,000` start equity,
  `30` trades, net PnL `3326454.691600313611000000000`,
  `reports/phase2/strategy-ralph/f-swing-support-tight-u1s1-maxslot50m-cost2x-observed/report.json`.

Capacity interpretation:

- Swing `F-SUP` passes max-slot seed and 2x cost stress.
- Day `C-IDMOM-D3` does not pass max-slot 2x cost stress when all available
  deployable capital can expand into three or more day slots. It does pass a
  separate KRW `50,000,000` one-slot run and a later exact two-slot Plan A
  check. Therefore the boundary is a controlled concurrent day-slot limit, not
  an account-size limit.
- The earlier KRW `20,000,000`, `30,000,000`, and `50,000,000` variable-slot
  failures are not clean fixed two-slot failures because weekly contribution
  and the configured max slot cap could expand the run beyond two concurrent
  day slots. Treat those runs as over-expansion stress evidence.

## Integrated Portfolio Validation

Plan B portfolio contract:

- Strategy: `portfolio-idmom-swing-support`, combining day
  `C-IDMOM-D3-U1-S1` and swing `F-SUP-U1-S1`.
- Capital: KRW `50,000,000` start equity plus KRW `100,000` weekly external
  contribution.
- Slot policy: shared-slot, variable slot count, max `5` open positions,
  KRW `10,000,000` slot capital cap.
- Allocation cap: signal group `day=1`; remaining slots remain available to
  swing candidates.
- Execution: conservative intrabar policy, stop-first ambiguous intrabar
  policy, exact-bar continuity audit.

| Matrix ID | Cost | Trades | Net PnL | Max Drawdown | Contributions | Continuity | Report | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `PORT-IDMOM-D3-FSUP-U1-S1-DAYCAP1-50M-COST-BASE` | base | 118 | 3021936.268395406584875000000 | -0.02448811686445398902353164460 | 4800000 | passed; 236 checked, 0 failed, 0 missing | `reports/phase2/strategy-ralph/portfolio-idmom-d3-fsup-u1s1-daycap1-50m-base-observed/report.json` | Pass |
| `PORT-IDMOM-D3-FSUP-U1-S1-DAYCAP1-50M-COST-2X` | 2x | 118 | 1528743.141652713389000000000 | -0.02523472009184628878265898456 | 4800000 | passed; 236 checked, 0 failed, 0 missing | `reports/phase2/strategy-ralph/portfolio-idmom-d3-fsup-u1s1-daycap1-50m-cost2x-observed/report.json` | Pass |

Portfolio interpretation:

- The integrated portfolio passes the current Ralph backtest gate only after
  enforcing the day-leg one-slot cap. Without that cap, the day leg exceeded its
  validated 2x-cost capacity boundary.
- Treat this passing portfolio as `Plan B`: the validated fallback/safety plan.

Plan A standalone day confirmation:

| Matrix ID | Cost | Trades | Net PnL | Max Drawdown | Contributions | Continuity | Report | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `C-IDMOM-D3-U1-S1-70M-EXACT2SLOT-COST-2X` | 2x | 127 | 891223.5614224796360000000000 | -0.03262582970855858591154413330 | 4800000 | passed; 254 checked, 0 failed, 0 missing | `reports/phase2/strategy-ralph/plan-a/c-idmom-d3-u1s1-70m-exact2slot-cost2x-observed/report.json` | Pass |

Plan A portfolio contract:

- Strategy: `portfolio-idmom-swing-support`, combining day
  `C-IDMOM-D3-U1-S1` and swing `F-SUP-U1-S1`.
- Capital: KRW `70,000,000` start equity plus KRW `100,000` weekly external
  contribution.
- Slot policy: shared-slot, variable slot count, max `7` open positions,
  KRW `10,000,000` slot capital cap.
- Allocation cap: signal groups `day=2` and `swing=5`.
- Execution: conservative intrabar policy, stop-first ambiguous intrabar
  policy, exact-bar continuity audit.

| Matrix ID | Cost | Trades | Net PnL | Max Drawdown | Contributions | Continuity | Report | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `PORT-IDMOM-D3-FSUP-U1-S1-DAYCAP2-SWINGCAP5-70M-COST-BASE` | base | 155 | 3113880.235951499359875000000 | -0.02041719768857436654081391471 | 4800000 | passed; 310 checked, 0 failed, 0 missing | `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-base-observed/report.json` | Pass |
| `PORT-IDMOM-D3-FSUP-U1-S1-DAYCAP2-SWINGCAP5-70M-COST-2X` | 2x | 155 | 797425.2753183808390000000000 | -0.02391565633831140121910706709 | 4800000 | passed; 310 checked, 0 failed, 0 missing | `reports/phase2/strategy-ralph/plan-a/portfolio-idmom-d3-fsup-u1s1-daycap2-swingcap5-70m-cost2x-observed/report.json` | Pass |

Plan A interpretation:

- `Plan A` is now the preferred validated target inside the current historical
  data and slippage-assumption boundary: two KRW `10,000,000` day-trade slots
  plus up to five KRW `10,000,000` swing slots, for a KRW `70,000,000`
  validated operating ceiling.
- `Plan B` remains available as a more conservative fallback if field execution
  quality, realized slippage, drawdown, or continuity deviates from the
  assumptions used here.
- This is still a historical OHLCV/slippage-assumption validation, not real
  order-book slippage proof. Strict bid/ask-pressure validation remains a
  field-log requirement.
- Treat KRW `70,000,000` as the current validated operating ceiling for this
  portfolio. Above this boundary, do not deploy additional capital just because
  the account grew. Surplus capital stays idle/reserve until a new strategy
  survives the same validation gates.

## Field Operation Checkpoints

- Capital triggers: KRW `10,000,000`, KRW `30,000,000`, KRW `50,000,000`, then
  every material increase beyond KRW `50,000,000`.
- Time triggers: monthly execution-quality review, quarterly strategy
  revalidation, and semiannual or data-sufficient candidate rebuild.
- Event triggers: realized slippage drift, drawdown breach, repeated
  continuity/data failures, fill-quality degradation, or field behavior that
  differs from backtest assumptions.
- UI requirement: the future operator dashboard must alert on these checkpoint
  triggers and show the trigger reason, required revalidation action, last
  validation artifact, due/overdue state, and whether surplus capital is blocked
  from deployment.

## Field-Only Data Gaps

- Real bid/ask pressure is not present in the historical Daishin CSV bars used
  by these runs. The current CSV-loaded `Bar.bid_ask_ratio` is the default
  value `2.0`, so `min_bid_ask_ratio > 2.0` produces a coverage reject rather
  than a real market-quality result. Treat strict bid/ask-pressure scouter gates
  as field-only measurement until a historical source with that field exists.
