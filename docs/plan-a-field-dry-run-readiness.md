# Plan A Field Dry-Run Readiness

This document converts the validated Plan A backtest into a no-order field
dry-run contract. It does not approve paper trading, broker order calls, account
actions, credentials, or live deployment.

Current Plan A next-action tracking is centralized in
[`plan-a-next-actions.md`](plan-a-next-actions.md). Use that index to find
immediate next actions, weekend work, next-week comparison, future work, and
backtest fallback routing before editing lower-level plan sections.

## Status Language Correction

Do not use "complete" or "ready" as a broad label for this stage. Status must
name the evidence level:

| Status | Meaning |
| --- | --- |
| Planned | Captured in the current plan or document only. |
| Implemented | Code path exists, but it may be local-only or adapter-only. |
| Verified local/no-order only | Targeted tests, smoke checks, or generated artifacts prove the code path inside the current no-order boundary. |
| Produced | A concrete report or data artifact exists for the current run. |
| Operational | Scheduler, real data source, storage policy, recovery, and monitoring are connected. |
| Approval-ready | Operational evidence is sufficient to request the next owner-approved stage. |

Current wording correction:

| Area | Correct status |
| --- | --- |
| News/DART defense | Implemented as an async blacklist input contract plus external read-only JSON/RSS URL fetcher. This is not yet a KIS-provided news feed integration. KIS news/disclosure source details must be confirmed and wired separately, but missing live news does not block a no-order dry-run unless `--require-news-feed` is intentionally enforced. |
| KIS read-only integration | Implemented and smoke-tested for token/quote contract checks. KIS read-only daily-bar collection is the operating source for current 60-trading-day universe input. It is not an order, account, fill, news, or full market-hours polling integration. |
| Field universe | Implemented as a prior-only routine, but the current 2026-05-14 artifact is fail-closed because local daily bars stop at 2026-05-07 while the expected prior trading date is 2026-05-13. The next dry-run needs a fresh accepted universe and KIS symbol list before market-data quote smoke can proceed. The source data standard for universe construction is 60 trading days from KIS daily bars. If that data is missing or incomplete, collect the missing KIS data first rather than running in a restricted mode. CYBOS/Daishin data remains a historical two-year minute-bar exception/reference source only. |
| Scouter | Implemented for local no-order dry-run/backtest paths. Market-hours KIS-backed polling, bottleneck handling, and recovery are validation points during the dry-run session. |
| Dry-run infrastructure | Implemented and locally verified inside the no-order boundary for snapshot monitor, resume/recovery, reports, and session-stop guard. Full market-hours validation is still pending and must prove behavior over the live session rather than only fixture/smoke artifacts. |
| Slippage and fees | Modeled by conservative assumptions only. Dry-run virtual fills and PnL apply fee `0.00030` and slippage `0.00100`, matching the 2x cost-stress boundary. Real order-to-fill slippage cannot be verified before an approved order stage, and is not a no-order dry-run precondition. |
| DB/logging | Implemented for no-order ledgers and selected snapshots. Long-term retention cleanup and operational DB runbook are pending. |
| UI alerts | Planned only. No dashboard implementation is complete. |
| Review gate | Latest recorded full verify passed after the data-timepoint fixes. Review gate is useful before a commit candidate, but the current no-order start blocker is missing accepted universe input, not reviewer availability. |

## Status

Plan A is validated only inside the current historical OHLCV and conservative
cost-assumption boundary:

- day: `C-IDMOM-D3-U1-S1`, max two concurrent KRW `10,000,000` slots;
- swing: `F-SUP-U1-S1`, max five concurrent KRW `10,000,000` slots;
- portfolio: shared-slot, max seven total slots, group caps `day=2` and
  `swing=5`;
- operating ceiling: KRW `70,000,000`;
- contribution plan: weekly KRW `100,000`;
- Plan B fallback: day one slot plus swing up to five slots.

The next stage must prove that the same decision process can run for real
market sessions without sending orders.

## No-Order Dry-Run Gate

Start blockers for the next no-order dry-run:

- an accepted prior-only universe artifact and KIS symbol list for the session;
- read-only KIS credential/profile setup for quote smoke only;
- order, account, balance, and fill endpoints remaining hard-blocked;
- API call-budget policy loaded below the production limit with safety margin;
- local storage above the protective-mode threshold;
- dry-run command path able to write status, ledger, and daily review output.

Not start blockers:

- post-close universe generation for the following session, because this is the
  recurring end-of-day routine after the current session;
- market-hours scouter behavior, bottleneck handling, and recovery evidence,
  because these are observed during the dry-run itself;
- KIS-provided news/disclosure integration, unless the run is deliberately
  launched with `--require-news-feed`;
- review gate, unless a commit candidate is being presented;
- real order-to-fill slippage evidence, because it requires a later
  owner-approved order stage.

## Required Old-Plan Rules

| Rule | Dry-run treatment | Backtest gap |
| --- | --- | --- |
| First-in, first-served symbol interlock | If a symbol is held, every new day or swing entry for that symbol is skipped and logged. | Current backtest prevents duplicate open symbols, but skip-event evidence is not reported as a first-class artifact. |
| Day-to-swing same-day reuse | Allowed only after the day position is fully closed without overnight carry and the 15:15 swing target appears later. | Needs explicit event sequencing and report evidence. |
| 15:15 collision cooldown | If day time-cut exit and swing entry collide for the same symbol, skip swing entry and apply one trading day cooldown. | Not yet represented as a named backtest/dry-run event. |
| 15:15 lock-step | During swing transaction window, day and swing engines cannot mutate the same symbol/account state concurrently. | Needs deterministic sequencing in dry-run orchestration. |
| Swing opening survival check | Existing swing positions are checked at open for gap trend-break/hard-stop risk before new scans consume slots. | Current backtest has gap/carry approximations, but dry-run must persist opening survival evidence. |
| Regime budget switch | Bull full budget, range reduced new-entry budget, bear blocks new swing and allows only separately validated defensive day logic. | Plan A used bull-only validation; range/bear behavior remains dry-run or future validation scope. |
| Correlation concentration cap | Archived enhanced plan limits highly correlated holdings so one theme does not dominate portfolio risk. | Not represented in the current no-order dry-run; needs a future portfolio-risk feed or local proxy before it can be credited. |
| Day slot reload fuse | A day slot can reload after exit; repeated same-day stop losses shut down that slot. | Current backtest has daily stop/loss fuses, but per-slot stop-streak evidence must be logged. |
| Distinct exits | Day and swing exit rules must not be silently merged. | Current portfolio assigns separate exit policies; dry-run must expose the selected policy in logs. |
| Account-level fuse | Daily loss and MDD fuses block new buys while preserving exit monitoring. | Backtest has daily loss controls; MDD shutdown and alert lifecycle need dry-run evidence. |
| Manual panic / operator hard stop | Operator must be able to stop operation immediately; later order stage may require emergency liquidation. | No-order dry-run can only stop monitoring and block new virtual actions. Real liquidation requires the later owner-approved order-stage plan. |
| Operator heartbeat | Archived plan expected regular alive/account-status pings. | Current no-order evidence is status/report files; notification channel and dashboard alerts are UI/observability follow-up, not yet operational heartbeat parity. |

## Operating Sequence

Normal startup must use one main field-run command. The operator should not have
to manually run separate KIS quote collection, field monitor, AI-watch, cooldown
repair, or status-refresh commands during a routine session. The main command
must execute the sequence below, using the approved real-network permission path
for external API calls, and fail closed with status artifacts when a stage cannot
advance.

Current implementation surface:

```bash
.venv/bin/python -m zurini.cli field-run \
  --run-id field-runner-YYYY-MM-DD \
  --symbol-list reports/dry-run/field-universe-kis-symbols.txt \
  --universe-report reports/dry-run/field-universe-YYYY-MM-DD.json \
  --allow-network \
  --run-network \
  --endpoint-profile prod \
  --confirm-prod-readonly \
  --quote-report reports/dry-run/kis-readonly-universe.json \
  --output-dir reports/dry-run/field-runner-YYYY-MM-DD \
  --status-output reports/dry-run/current-status-YYYY-MM-DD.json \
  --control-output reports/dry-run/field-run-control-YYYY-MM-DD.json \
  --enforce-market-session-stop \
  --market-session-date YYYY-MM-DD \
  --market-session-stop-time 15:35
```

The command loops without post-cycle sleep. KIS quote/depth collection time and
the configured API throttle are the only normal pacing mechanism. At or after
15:10, if a current watchlist contains positive intraday swing-focus candidates,
the next quote/depth cycle is narrowed to those candidates; if no focus evidence
exists yet, the cycle stays on the full accepted symbol list.

Readiness principle for every operating parameter:

- Every parameter that affects universe selection, candidate monitoring, risk
  defense, API pacing, storage safety, recovery, or reporting must declare its
  required input data and freshness window.
- At startup, restart, and each stage transition, validate those required
  inputs before advancing.
- If any required input is missing, stale, incomplete, or contract-invalid,
  collect or rebuild that missing input first. Do not continue in a reduced,
  restricted, or best-effort operating mode merely because the input is absent.
- If the missing input cannot be collected, stop at that stage and report the
  specific data-acquisition failure. Treat the stop as an incomplete readiness
  state, not as a valid trading or no-entry decision.
- Reuse existing artifacts only when they satisfy the same parameter-specific
  required-data and freshness checks.

1. **Prior-day batch**
   - Collect KIS stock master files before universe data acquisition and update
     the local DB / market-wide candidate symbol source. The refreshed source must
     record collection time, source files, market classification, symbol count,
     and applied exclusions. If the stock master input is missing, stale,
     malformed, or not refreshed for the run, stop before KIS daily-bar
     collection.
   - Current command:
     `.venv/bin/python -m zurini.cli kis-stock-master-refresh --allow-network --run-network --report-output reports/dry-run/kis-stock-master.json --symbol-list-output reports/dry-run/kis-source-symbols.txt`.
   - Confirm 60 trading days of prior KIS daily-bar source data for universe
     construction. CYBOS/Daishin remains a historical two-year minute-bar
     exception/reference source, not the routine operating source.
   - If the 60-trading-day source data is missing or incomplete, collect the
     missing data first. Do not continue with a reduced-data or restricted
     universe-selection mode.
   - Build the prior-only universe only after the 60-trading-day data standard
     is satisfied.
   - Store universe version, source files, parameter version, and rejected
     symbols with reasons.

2. **Pre-open readiness**
   - Load open swing positions from the dry-run ledger.
   - Run opening survival checks for gap-down, trend-break, and hard-stop risk.
   - Resolve available cash, reserved cash, day sleeve, swing sleeve, group
     caps, and Plan B fallback state.
   - Load the configured field API per-second call budget and block promotion
     if the planned read cadence would exceed it.

3. **Open to intraday day engine**
   - Run the day scouter only on eligible universe symbols.
   - Use an adaptive scouter cadence instead of a fixed polling interval.
   - Do not sleep the 장중감시모듈 between successful collection/decision
     cycles. The quote/depth collection time and API throttle are the pacing
     mechanism. A human-reporting interval such as AI감시모드 5 minutes must
     never throttle the market-data collection or strategy-decision loop.
   - Apply held-symbol interlock before candidate ranking.
   - Rank by documented score; when score ties, use deterministic tie-break.
   - Create virtual orders only; order transmission is hard-blocked.

4. **Intraday monitoring**
   - Track virtual fills, exits, stop events, slot reload state, and fuses.
   - Persist skipped candidates, blocked candidates, cooldowns, and invalid
     data events.

5. **15:15 lock-step window**
   - At 15:10 KST, make a first-pass selection of universe symbols with swing
     entry potential and assign swing buy priority. After this point, focus
     quote/depth scanning on the selected swing candidates and exclude the
     remaining universe members from noncritical swing-entry polling.
   - Slow or pause noncritical day-scouter polling before the swing transaction
     window so exit checks, interlock checks, and swing entry validation keep
     API priority.
   - Freeze concurrent day/swing state mutation.
   - Process required day time-cut exits first.
   - Apply same-symbol collision rule and one-trading-day cooldown.
   - Evaluate swing entries only after interlock and cooldown state is final.
   - The swing decision is not allowed to require an exact `15:15:00`
     timestamp. Use the first accepted market snapshot collected at or after
     15:15 KST for the selected swing candidates.

6. **Daily close**
   - Generate daily decision report.
   - Generate a daily strategy-hints report that separates operational health,
     strategy-signal evidence, relative-strength survivors, spike-and-fade
     cases, data-quality limits, and next-session focus.
   - Reconcile virtual positions, cash, reserved cash, sleeve exposure, and
     strategy PnL.
   - Store source-gap and continuity evidence for future revalidation.
   - Update the cumulative daily analysis index with links to the daily review,
     watchlist summary, strategy-hints report, and headline metrics.

## Dry-Run DB / Log Contract

The dry-run DB must retain enough evidence to replay why each decision happened.

Core tables or equivalent records:

- `dry_run_session`: trading date, strategy package version, data source
  versions, run mode, order-hard-block status.
- `universe_snapshot`: universe ID, prior-only inputs, included symbols,
  excluded symbols, and exclusion reason.
- `scouter_candidate`: timestamp, symbol, strategy group, raw signal state,
  score, candidate rank, pass/fail reason.
- `interlock_event`: timestamp, symbol, event type, source strategy, blocked
  strategy, held position ID, cooldown expiry date.
- `virtual_order`: intended side, quantity, intended price, virtual fill model,
  hard-block evidence, reason code.
- `virtual_position`: symbol, strategy group, entry event, exit policy,
  quantity, cash allocation, slot ID, sleeve ID.
- `virtual_fill`: expected fill, simulated fill, slippage assumption, partial
  fill marker when modeled.
- `risk_event`: daily loss fuse, MDD fuse, slot fuse, invalid data, continuity
  failure, and blocked buy state.
- `daily_report`: summary counts, open positions, closed positions, virtual
  PnL, cash reserve, deployment block status, and next required checkpoint.
- `api_rate_limit_check`: provider, per-second limit, estimated calls, estimated
  peak calls per second, data source, and promotion block status.
- `checkpoint_event`: dry-run day count, capital threshold, cooldown, risk
  fuse, API rate-limit, and deployment-block triggers.

Field-only data such as order-book depth, queue position, real fill quality,
and actual partial fills must be stored when available later, but must not be
credited as historical backtest evidence before it exists.

API call limits are treated the same way: local CSV dry-run makes no API calls,
but it must still record the future API throttle contract. Later field dry-run
promotion must prove that universe refresh, scouter validation, quote reads,
position reads, and order-state reads fit under the provider's per-second and
daily limits before the workflow can run unattended.

Scouter cadence must be time-window aware. The production REST ceiling is
treated as 20 calls/second, but this is a provider hard limit, not a target.
Normal operation must leave reserve capacity because position checks, risk
checks, order-state reads, and emergency exits need immediate headroom. Baseline
dry-run policy:

- normal intraday: total REST call budget target is at most 15 calls/second,
  with the scouter capped at 10 calls/second after reserved calls are allocated;
- open burst window, roughly 09:00-09:10: total REST call budget target is at
  most 7 calls/second, with the scouter capped at 5 calls/second until
  opening-gap, survival, and first-risk checks settle;
- 15:10-15:20 lock-step window: total REST call budget target is at most 7
  calls/second; noncritical day-scouter polling is slowed or paused, and the
  reserved budget goes to day time-cut exits, same-symbol interlocks, and swing
  entry validation;
- loop pacing: 장중감시모듈 must immediately start the next cycle after the
  previous quote/depth collection and monitor pass finishes. A fixed post-cycle
  sleep is forbidden unless it is a documented API cooldown recovery path with
  an `api_degraded` artifact flag. The AI감시모드 user-reporting cadence is a
  separate process and is currently 5 minutes.
- throttle or latency anomaly: widen the scouter interval immediately and log
  `api_degraded`; do not recover to the faster cadence until a full clean
  polling window completes.

This means `--api-rate-limit-per-second 20` is the provider ceiling, not the
operating target. The field runner must derive actual polling intervals from
the lower internal budget after reserved calls are allocated.

## Field Monitor / Shadow Fan-Out Contract

The field dry-run monitor must collect read-only market snapshots once per
polling cycle and fan out the same snapshot stream to multiple no-order engines.
The API polling layer is shared; strategy engines are parallel observation
lanes. This avoids multiplying provider calls while still preserving comparison
data across current and future capital plans.

Default scenario lanes:

- `primary-current-seed-1m`: actual small-seed baseline, KRW `1,000,000` start
  plus weekly KRW `100,000` contribution. Only this lane may inform no-order
  field continuation decisions.
- `shadow-current-seed-2m`: KRW `2,000,000` start plus weekly KRW `100,000`,
  used to judge whether small-seed fragility materially improves.
- `shadow-future-seed-50m`: conservative future-capacity observation around
  the Plan B boundary.
- `shadow-future-seed-70m`: Plan A validated ceiling observation.
- `shadow-slippage-stress-70m`: reserved lane for read-only quote-depth and
  slippage-proxy stress once market-data fields are available.

Shadow lanes are never order authority. They may become later revalidation
candidates only after a separate review confirms the hypothesis, data quality,
cost stress, continuity, capacity, and field-alignment gates.

Monitor status outputs:

- `current-status.json`: latest mode, status, order-hard-block flag, scenario
  list, scenario results, API/storage/slippage flags, and next review action.
- `daily-review/YYYY-MM-DD.md`: post-close review artifact separating primary
  continuation evidence from shadow observation.
- `daily-review/YYYY-MM-DD-strategy-hints.md`: post-close strategy-use report
  for market shape, relative-strength survivors, spike-and-fade cases,
  near-miss evidence, data-quality limits, and next-session hypotheses.
- `watchlist/watchlist-full-YYYY-MM-DD.json`: compact full-universe decision
  evidence. It keeps accumulated observation rows for the monitored universe
  rather than only a Top-N subset, separates latest scored symbol count from
  intraday observation count, records reason counts, per-symbol movement
  summaries, entry-trigger timing, and provisional post-trigger take/stop
  movement proxies.
- `watchlist/watchlist-summary-YYYY-MM-DD.md`: operator-readable summary with
  latest Top30 view, movement leaders, entry-trigger outcomes, and reason
  counts. Top10/20/30/50 cutoffs are derived analysis views only; the first
  dry-run week must keep collecting all 100 monitored symbols before choosing a
  narrower live watchlist policy.
- `reports/dry-run/daily-analysis-index.md`: cumulative management index that
  links the daily review, watchlist summary, strategy-hints report, and headline
  metrics. It is for comparing dry-run days, not for approving trades.
- scenario reports under `scenarios/`: per-lane no-order dry-run reports using
  the same market snapshot input.

KIS report snapshot monitor runs are API wiring and contract smoke only when
they are built from a one-timestamp quote artifact. They are not complete
strategy dry-run evidence for warmup, exit-policy, carry, or time-series
behavior until a real market-hours snapshot sequence has been collected.

If `current-status.json.status` is `api_degraded` or `risk_feed_degraded`, the
scenario reports are observation-only diagnostics. They are not readiness
evidence for field start or broker integration until the degraded input is
cleared and a fresh clean monitor run is produced.

The monitor may wait for market hours in a later long-running mode, but the
safety contract is the same: no broker order, account, balance, credential, or
real-fill action is allowed by this command.

Initial KIS API integration goal:

- First build a sanitized `api-smoke` or `kis-readonly-universe` artifact before
  promoting a monitor run to field-data mode.
- Treat endpoint/TR ID/parameter/schema mistakes as expected early failures.
  They must raise `api_command_error` or `api_schema_mismatch` instead of
  silently becoming empty universes.
- Feed API report flags into the monitor with `--api-report` so
  `current-status.json` can enter `api_degraded` without depending on a live AI
  session.
- Universe construction at this stage is quote-contract smoke from an explicit
  symbol list. It proves read-only API wiring and symbol inclusion/exclusion
  logging; it does not yet prove final prior-only U1 liquidity/ATR/SMA ranking.

## Tomorrow Field Universe Build

For a new next trading day, build the universe after the prior close from
prior-only local market bars, then optionally verify those symbols through KIS
read-only quote smoke. If an accepted prior-day universe artifact already
exists for today's dry-run, do not rebuild it during market hours; consume that
artifact and leave the next-session build to the post-close routine.

Post-close timing rule:

- 15:35 KST: perform the first dry-run close-state check and confirm no-order
  status, API flags, scenario counts, and report freshness;
- 16:10 KST: build the next-session universe. Do not start immediately after
  15:30 close because KIS and market data may still be settling;
- 16:20 KST or later: run the KIS production read-only quote smoke for the
  generated symbol list;
- 16:30 KST or later: consolidate the daily review, universe artifact, KIS
  smoke result, and any degraded-state notes.

KIS prior-only build:

```bash
.venv/bin/python -m zurini.cli build-daily-field-universe \
  --target-date 2026-05-12 \
  --root data/raw/kis/daily-bars \
  --source kis-daily-bars \
  --latest-months 4 \
  --min-average-value 50000000000 \
  --min-atr-ratio 0.03 \
  --kis-symbol-list-output reports/dry-run/field-universe-kis-symbols.txt \
  --output reports/dry-run/field-universe-2026-05-12.json
```

Construction contract:

- use only bars strictly before `--target-date`;
- apply the same data-completion rule to every parameter used by the operating
  path: first identify the required lookback, source, and freshness window;
  then collect missing data until the requirement is satisfied; only then
  advance to the next stage;
- before fetching KIS daily bars, collect KIS stock master files and refresh the
  local DB / market-wide candidate symbol source. Daily-bar collection must use
  this refreshed KIS-derived candidate list, not a hand-entered or stale
  selected universe list;
- use the derived daily-bar root for routine field-universe builds. The minute
  CSV root is valid input, but it is too heavy for a normal pre-open run unless
  a narrow path list or file limit is provided;
- the routine universe source-data standard is 60 trading days before the
  target date. Current strategy parameters consume shorter windows from that
  data, including 5 trading days for recent traded value, 14 trading days for
  ATR/opportunity, and 20 trading days for the moving-average trend check, but
  the collection/readiness gate is still 60 trading days;
- when the root is partitioned by `YYYYMM`, load enough month partitions to
  satisfy the 60-trading-day standard. Do not treat one or two calendar months
  as sufficient unless the actual distinct trading-day count reaches 60;
- if the 60-trading-day standard is not met, collect the missing KIS daily-bar
  data and re-check coverage before building the universe. The fallback is not
  restricted operation; the fallback is data completion. If collection fails,
  stop before universe selection and report source-data collection failure;
- for routine daily-bar maintenance after each close, refresh KIS stock master
  files, update the local DB / market-wide candidate symbol source, collect the
  expected prior trading day from KIS for that refreshed source, verify the
  rolling 60-trading-day window is complete, then clear the oldest retained
  prior date. Do not prune first; the window must never shrink below the
  60-trading-day readiness standard;
- accept common numeric symbols only, stored internally as `A000000` style when
  source files use that convention;
- compute prior average traded value, prior close/SMA relation, and ATR ratio;
- emit included symbols, KIS symbols, excluded symbols, exclusion reasons, and
  parameters;
- mark `ready_for_broker_or_order_transmission=false`.

Optional KIS quote-contract check:

```bash
.venv/bin/python -m zurini.cli kis-readonly-universe \
  --allow-network \
  --run-network \
  --symbol-list reports/dry-run/field-universe-kis-symbols.txt \
  --endpoint-profile prod \
  --confirm-prod-readonly \
  --rate-profile prod \
  --output reports/dry-run/kis-readonly-universe-2026-05-12.json
```

The KIS check confirms quote endpoint compatibility for the generated universe.
It does not authorize field orders, account reads, or live trading.
For market-hours loops, the KIS quote collector must be launched with the
session stop guard. This prevents an outer shell loop from continuing read-only
KIS calls after the intended close-state window:

```bash
.venv/bin/python -m zurini.cli kis-readonly-universe \
  --allow-network \
  --run-network \
  --symbol-list reports/dry-run/field-universe-kis-symbols-2026-05-12.txt \
  --endpoint-profile prod \
  --confirm-prod-readonly \
  --rate-profile prod \
  --enforce-market-session-stop \
  --market-session-date 2026-05-12 \
  --market-session-stop-time 15:35 \
  --output reports/dry-run/kis-readonly-universe-2026-05-12.json
```

If the guard has fired, the command writes `status=stopped`,
`mode=market-session-closed`, `api_flags=["market_session_closed"]`, and
`read_call_count=0`, then exits successfully without calling the KIS network.
For strategy-signal dry-run evidence, the read-only KIS quote artifact must
preserve more than `stck_prpr`/price. The monitor accepts backward-compatible
price-only artifacts for API stability checks, but those artifacts are not valid
evidence for entry-trigger frequency. A strategy-aligned artifact should retain:

- `stck_prpr` as `price`;
- `stck_oprc`, `stck_hgpr`, and `stck_lwpr` as same-session open/high/low;
- `acml_vol` as cumulative volume;
- `acml_tr_pbmn` as cumulative traded value;
- `prdy_ctrt` as previous-day change-rate reference when available;
- `observed_at` as the quote observation timestamp.

If those fields are present, the monitor converts them into the dry-run
`Bar.open`, `Bar.high`, `Bar.low`, `Bar.close`, `Bar.volume`, and `Bar.value`
contract. If `total_bidp_rsqn` / `total_askp_rsqn` style quote-depth fields are
present, the KIS artifact also carries `bid_ask_ratio`; otherwise bid/ask
pressure is explicitly flagged as `bid_ask_placeholder`. Price-only or
timestamp-less rows are not strategy evidence. For monitor runs,
`--market-data-max-age-seconds` defaults to 120 seconds, so replaying an old
KIS artifact for analysis must pass a matching `--now` value; market-hours runs
should omit `--now` and use wall-clock freshness.

Operational live monitoring has one KIS feed path: generate
`kis-readonly-universe --include-quote-depth` and pass that single artifact as
`--market-data-report`. Do not combine a separate `kis-readonly-depth` or
`--quote-depth-report` artifact into field monitoring; depth-only reports are
diagnostic, and every included member must carry price/depth timestamps with a
per-symbol gap not exceeding five seconds. A degraded quote-depth artifact is a
non-zero command result and cannot be promoted as operating evidence.

Current-cycle bid/ask placeholder handling is intentionally narrower than a
general degraded-input bypass. During main `field-run`, if every degraded member
has exactly `bid_ask_placeholder` and at least one clean member remains, the run
may exclude those placeholder symbols from the current cycle and continue with
the clean members only. The quote report must change to `status=passed`, clear
top-level `api_flags`, record the excluded members in
`quote_depth_excluded_symbols`, and set
`input_contract_action=excluded_bid_ask_placeholder_symbols`. A top-level
`api_rate_limit_risk` is not diagnostic for operating continuation; it means the
read-call budget contract was not accepted and the cycle must remain degraded or
fail closed. Placeholder exclusion is valid only because missing bid/ask
pressure for an otherwise excluded member is not strategy evidence. It must not
be used for auth failures, budget/rate-limit pressure, schema errors, stale
timestamps, future timestamps, paired price/depth gaps, missing prices,
timeout-heavy collection, or mixed degraded flags; those remain fail-closed or
degraded-cycle skip conditions.

The 2026-05-18 main run also exposed two pre-split performance constraints that
are now part of the operating path. Daily-bar source classification must scan
stored KIS daily CSV files once and group by symbol; it must not perform a
full filesystem scan per candidate symbol. Reused-universe warm-up validation
must load only the symbols required by the accepted field universe, not the full
market-wide accepted daily source list. Field monitor warm-up loading must also
filter CSV/path-list inputs to the symbols present in the accepted live KIS
snapshot for that cycle. Large scenario JSON writes on `/mnt/c` can still make
each monitor cycle slow; treat that as an I/O latency risk to address in the W14
collection/report split, not as permission to hand-edit artifacts or bypass the
main module.

When both historical CSV input and `--market-data-report` are supplied,
`field-dry-run-monitor` now combines prior CSV warm-up bars, replayable prior
watchlist observations, and the current KIS snapshot stream. This is required
before a same-day KIS snapshot can be treated as strategy-signal evidence rather
than a cold-start quote diagnostic.

장중 scenario execution is primary-only. The main `field-run` monitor loop must
execute `primary-current-seed-1m` only, because that is the operating baseline
for live no-order continuation decisions. Shadow current-capital, future-capital
capacity, and slippage-stress scenarios are post-close validation lanes over the
data acquired during the day. They may run through the analysis/monitor replay
surface after the session, but they must not consume intraday monitor cycle time
or appear as 장중 main `field-run` scenario results. If a live `field-run`
status/control artifact shows shadow scenario results, classify it as an
operating-sequence defect and stop/restart through the corrected primary-only
path.

Market-hours monitor launch must therefore include the accepted prior warm-up
path or path-list and the same stop guard:

```bash
.venv/bin/python -m zurini.cli field-dry-run-monitor \
  --run-id field-runner-2026-05-12 \
  --path-list reports/dry-run/accepted-prior-warmup-paths-2026-05-12.txt \
  --start-date 2026-05-04 \
  --end-date 2026-05-07 \
  --market-data-report reports/dry-run/kis-readonly-universe-2026-05-12.json \
  --watch \
  --enforce-market-session-stop \
  --market-session-date 2026-05-12 \
  --market-session-stop-time 15:35 \
  --output-dir reports/dry-run/field-runner-2026-05-12 \
  --status-output reports/dry-run/current-status.json
```

If the guard has fired, the monitor writes `status=session_closed` with
`market_session_closed` and no scenario reports. That artifact is operational
shutdown evidence, not a no-signal strategy result.
Do not pass the same KIS universe artifact as both `--market-data-report` and
`--api-report`; `--market-data-report` already supplies both bars and budget
evidence, and duplicating the same file would double-count read-call evidence.

### Field-Data Completeness Audit

The 2026-05-12 first market-hours run exposed a contract gap: the quote artifact
was sufficient for API/polling stability, but not sufficient for strategy-signal
validation. Keep the following audit table current before treating a dry-run day
as strategy evidence.

| Area | Required by strategy or field operation | Current acquisition status | Dry-run interpretation / required action |
| --- | --- | --- | --- |
| Current price | Scouter snapshot, virtual mark-to-market, stop/take proxy | Acquired as `stck_prpr` / `price` | Valid for quote stability and rough movement tracking. |
| Same-session open/high/low | Opening gap, opening range, day return, stop/take path proxy | KIS artifact preserves `stck_oprc`, `stck_hgpr`, `stck_lwpr`; monitor stores them in scouter/watchlist rows | Required before using entry-trigger frequency as strategy evidence; missing fields are flagged. |
| Cumulative volume | VWAP, impulse/volume surge, swing/day support volume ratio | KIS artifact preserves `acml_vol`; monitor stores it in scouter/watchlist rows | Required before judging day/swing entry scarcity; missing values are flagged. |
| Cumulative traded value | VWAP numerator, session-liquidity gate, candidate priority | KIS artifact preserves `acml_tr_pbmn`; monitor stores it in scouter/watchlist rows | Required before judging `session-liquidity` or candidate ranking; missing values are flagged. |
| Prior daily OHLCV window | U1 universe, 20-day SMA, ATR, prior average value, swing history | `field-dry-run-monitor` combines CSV warm-up bars with KIS snapshot bars when both are supplied | The launch command must provide the accepted prior data path/list for strategy-valid sessions. |
| Bid/ask pressure ratio | `Bid_Ask_Ratio >= 2.0`, old-plan Sniper VWAP pressure filter | KIS artifact computes bid/ask ratio from quote-depth quantities when present; otherwise flags placeholder | Placeholder rows remain diagnostic only until real quote-depth fields are available. |
| Order-book depth / executable quantity | Slippage proxy, slot cap, IOC feasibility, emergency exit realism | Not acquired in no-order quote runner | Required before paper/live order-stage approval, not required for no-order API stability. |
| Real-time condition-search push | Old plan Tier 2 candidate narrowing and volume-spike alert | Not implemented; current runner polls 100-symbol universe | Can be deferred, but polling-only dry-run must not claim parity with old push design. |
| Nasdaq futures / beta throttle | Risk budget multiplier and all-stop regime throttle | Defaulted in local `RiskState`; no live futures feed in current runner | Must be supplied by an explicit market-risk feed before using risk-throttle evidence. |
| Market regime / index state | Bull/range/bear budget switch and relative-strength filters | Backtest/local regime surfaces exist; live index feed not wired into current runner | Required before range/bear behavior can be credited in field dry-run. |
| News/DART blacklist heartbeat | Async risk defense and fail-closed freshness check | Generic adapter exists; KIS-provided news/disclosure source deferred; baseline week runs news OFF | Missing news is accepted for baseline only. News ON comparison needs a healthy heartbeat source. |
| Account cash/equity/reserved cash | Sleeve allocation, daily loss fuse, high-water MDD, sizing | Virtual ledger only; real account reads are explicitly blocked | Valid for no-order dry-run only. Required before field-start decision with real capital. |
| Existing positions | Same-symbol interlock, swing survival check, exit monitoring | Virtual ledger only; real position reads blocked | Valid for no-order continuation only. Required before any live/paper order stage. |
| Order state and fills | Real slippage, partial fills, IOC/backoff, emergency liquidation | Not acquired; order endpoints hard-blocked | Explicit later order-stage requirement. No-order dry-run must keep using conservative assumptions. |
| API latency / throttling | Polling cadence, critical-window budget, recovery behavior | Budget evidence is collected for read-only quote calls | Valid for API stability; must be expanded when account/order-state reads are introduced. |

Today-review sequencing: perform the daily review after the missing-parameter
collection and monitor input-contract fixes are implemented and verified. The
2026-05-12 review must separate pre-fix quote-stability evidence from post-fix
strategy-signal-readiness evidence.

Minimum condition before a future dry-run day counts as strategy-signal
evidence:

- KIS artifact contains price, same-session OHLC, cumulative volume, cumulative
  traded value, and observation timestamp;
- strategy runner receives the prior daily window needed for SMA/ATR/value and
  swing history warm-up;
- report stores per-symbol feature snapshots and day/swing rejection reasons;
- `Bid_Ask_Ratio` is either backed by real order-book fields or explicitly
  labeled as a placeholder;
- beta throttle and news defense state are marked `baseline-off`,
  `placeholder`, or `live-source-ok` instead of silently defaulting.

If any of these items are missing, entry-trigger count, candidate count, and
Top-N ranking are diagnostic only. They must not be used as proof that the
strategy was inactive or unsuitable.
The endpoint profile is separate from the rate profile. `--endpoint-profile
prod` uses `KIS_LIVE_*` credentials against the production read-only market-data
endpoint only after `--confirm-prod-readonly` is supplied. This production
read-only smoke path is part of the user-approved dry-run infrastructure scope;
it remains outside broker order, balance, account, real-fill, and live-trading
authority. `--endpoint-profile paper` uses the mock-server endpoint and
`KIS_PAPER_*` credentials. `field-run` defaults to `--endpoint-profile prod`
because the main field dry-run is production read-only market-data evidence,
but it still cannot issue production read-only calls unless
`--confirm-prod-readonly` is supplied. The default rate profile is `prod`
because dry-run promotion targets the field environment, not the stricter mock
server. `prod`
uses the lower internal field budget and treats 20 requests/second as the
provider ceiling only. During critical windows, including 09:00-09:10 and
15:10-15:20 KST, the scouter request budget is enforced per read call rather
than per symbol, so price and order-book reads are not allowed to burst as a
pair. `paper` means a 0.5 second quote interval for mock-server checks. If a
`prod` run
returns a throttle message, treat the result as `api_degraded` and classify
whether the response came from account scope, endpoint scope, credential type,
token refresh, or an accidental mock-server route. Do not widen production
polling latency from a mock-server throttle observation alone. Token
issue/refresh must use a separate one-minute cooldown and must not be retried
per symbol.

The cooldown file `.omx/state/kis-auth-cooldown.json` is operational runtime
state for KIS retry safety. It is not a secret file, but it is also not
disposable review metadata; cleanup routines must preserve it unless the active
task is explicitly resetting KIS auth cooldown behavior.

## Async News / Blacklist Contract

The old planning documents require negative news and DART-style defense, but
the entry path must not run real-time NLP directly. The field dry-run therefore
uses an async blacklist contract:

- blacklist artifact fields: `heartbeat_at`, `entries[]`, `symbol`, `reason`,
  `severity`, `source`, `observed_at`, and optional `expires_at`;
- symbols normalize from `A005930` to `005930` for KIS/common-symbol matching;
- if `heartbeat_at` is missing or older than 5 minutes at entry time, all new
  entries are blocked with `blacklist-stale-fail-closed`;
- if a symbol has an active entry, only that symbol is blocked with
  `blacklist-symbol-blocked`;
- expired entries are ignored;
- field monitor promotes blacklist degradation flags such as
  `blacklist_stale` and keeps `ready_for_broker_or_order_transmission=false`.

The collector surface has two layers:

- `collect-news-risk-events` accepts local generic news JSON, DART-style JSON,
  RSS XML, and read-only URL sources via `--news-json-url`, `--dart-json-url`,
  and `--rss-url` when `--allow-network --run-network` is explicit. External
  URL sources must use HTTPS; plaintext HTTP is limited to loopback smoke
  sources such as `localhost` or `127.0.0.1`. It converts matched negative
  keywords into event JSON and never calls KIS, broker, order, account, balance,
  or real-position endpoints. Every source item must carry a timestamp within
  `--source-max-age-minutes` (default 60); missing, future, or stale source
  timestamps fail closed instead of being treated as fresh news evidence.
- `update-news-blacklist` accepts event JSON, merges it into the async blacklist
  artifact, refreshes the heartbeat, and makes no KIS or broker calls.

This can run during market hours as a separate process from the trading engine.
The trading engine reads only the blacklist artifact with `--blacklist`; it does
not call a news API in the order-decision path. The collector requires at least
one event file by default, so a miswired feed cannot create a fresh clear
heartbeat. A deliberate clear heartbeat must use `--allow-empty-heartbeat` and
should be treated as an operator/adapter health assertion, not as implicit news
collection.

## Field Data Retention / Storage Guardrail

The current local machine has limited C: drive headroom. Until a separate
archive disk is explicitly approved, field dry-run storage must preserve
strategy-improvement evidence rather than full raw market-data history.

Default policy:

- Do not store every polling response, every quote tick, or full order-book raw
  data continuously.
- Persist every scouter decision snapshot needed to replay the strategy
  decision: poll timestamp, symbol, strategy group, feature values, score,
  rank, pass/fail reason, risk/interlock state, and selected data source.
- Persist candidate-rank and feature time series for candidates and near-miss
  candidates, even when no virtual order is produced.
- Persist API request metadata, response status, latency bucket,
  rate-limit/throttle evidence, and provider call-budget counters.
- Persist virtual orders, blocked-order reasons, virtual fills, positions, cash,
  slots, sleeves, risk fuses, checkpoints, and daily reports.
- Raw burst capture is optional and disabled by default. If enabled, it is
  limited to important event windows such as signal emergence, blocked order,
  API anomaly, rate-limit breach, sharp price move, or post-session review
  target.

Retention and capacity defaults:

- Universe snapshots and KIS symbol-list artifacts are compact decision
  evidence. Keep at least the latest 60 trading-day artifacts plus every
  month-end snapshot, then delete older non-month-end duplicates after daily
  review is complete.
- KIS-derived daily bars are the normal long-term feature source for operating
  universe construction. Keep them unless storage pressure forces a separate
  archive decision; do not rebuild routine operating universes from full
  CYBOS/Daishin 1-minute bars.
- Intermediate path lists, ad-hoc smoke outputs, interrupted build artifacts,
  and duplicate same-day universe attempts are cleanup candidates after the
  accepted daily universe and KIS read-only plan are written.
- Decision snapshots, feature snapshots, decision ledger, and reports are
  long-term retention data.
- Raw burst data, if enabled, uses a short TTL of 1 to 3 days.
- Dry-run DB and local logs use a soft cap of 5 GB until the storage policy is
  revised.
- Raw burst data uses a hard cap of 500 MB to 1 GB and is deleted oldest-first.
- If C: free space drops below 20 GB, raise a storage warning.
- If C: free space drops below 10 GB, disable raw burst capture and continue
  summary/snapshot logging only.
- If C: free space drops below 5 GB, enter protective mode: block new dry-run
  capture that is not required for shutdown/reconciliation evidence.

Production interpretation:

- Raw data is evidence for exceptional moments, not the primary long-term data
  asset.
- End-of-day universe construction may take several minutes because it is not a
  market-hours polling loop. Market-hours workflows must consume the latest
  accepted universe artifact instead of rebuilding the universe.
- Strategy revalidation should use decision snapshots, feature time series,
  candidate ranks, and decision ledgers as the durable field dataset.
- External archive storage remains optional future scope and must not be assumed
  by the next dry-run implementation.

## Capital Model Comparison

The current Plan A result used a shared-slot model. The archived plan used
separated day/swing engine budgets. The dry-run stage must compare feasibility,
not optimize for in-sample PnL.

Required baseline comparisons:

| Case | Purpose | Production interpretation |
| --- | --- | --- |
| Shared-slot Plan A | Preserve validated backtest contract: `day=2`, `swing=5`, total slots `7`. | Baseline because it is the proven Plan A backtest contract. |
| 40/60 separated sleeves | Test archived operating intent: day 40%, swing 60%. | Candidate field operating model if it does not create cash starvation or missed required exits. |

Optional sensitivity checks:

| Case | Purpose | Production interpretation |
| --- | --- | --- |
| 30/70 sensitivity | Check whether swing-heavy sleeve reduces small-seed fragility. | Sensitivity only, not optimizer-selected production value. |
| 50/50 sensitivity | Check whether simpler equal split materially changes feasibility. | Sensitivity only, not optimizer-selected production value. |

Starting seed comparison:

- KRW `1,000,000` start, weekly KRW `100,000` contribution;
- KRW `2,000,000` start, weekly KRW `100,000` contribution.

Feasibility metrics:

- number of days with insufficient cash for intended virtual orders;
- whole-share sizing rejects;
- average and minimum idle cash;
- day/swing opportunity loss caused by sleeve separation;
- interlock/cooldown counts;
- slot utilization by group;
- dry-run continuity and invalid-data counts.

If KRW `1,000,000` cannot support simultaneous day/swing operation without
pathological sizing, it remains observation-only until contributions raise
capital to the documented minimum viable level. KRW `2,000,000` is a comparison
case, not an automatic deposit recommendation.

## Success Criteria

Minimum readiness:

- order transmission is hard-blocked and logged every session;
- a 10-trading-day dry-run can complete with no unreconciled session failures;
- every day has a daily report that reconciles universe, scouter, interlock,
  virtual orders, virtual fills, cash, sleeves, slots, and risk events;
- Plan B fallback state is visible when Plan A constraints are breached;
- capital comparison reports identify whether KRW `1,000,000` or KRW
  `2,000,000` can support simultaneous day/swing dry-run operation.

Recommended stabilization:

- complete 20 trading days before writing any small-capital field-start decision
  record;
- keep days 10-20 in observation-enhanced mode even if the 10-day review is
  clean;
- do not enable live or paper order transmission in this stage.

Successful dry-run evidence can support a later field-start decision record,
but it does not authorize live trading, paper trading, broker connection,
account action, credential handling, or order transmission. Those require a
separate user-approved plan.

## Implementation Work Units

1. Dry-run ledger schema and migration.
2. Universe/scouter decision logging.
3. Interlock, cooldown, lock-step, and held-symbol event model.
4. Virtual order/fill model with hard-block evidence.
5. Capital sleeve comparison report.
6. Daily report generator.
7. UI checkpoint alert feed for dry-run day count, capital thresholds,
   cooldowns, risk fuses, and deployment blocks.

## TODO Status

Pre-dry-run implementation items are locally verified as no-order
infrastructure. They are not live/paper trading approval, broker-account
approval, or real-fill/slippage evidence.

| Status | Item | Evidence or next gate |
| --- | --- | --- |
| Commit-candidate only | Review gate after latest fixes | Latest recorded `./scripts/verify.sh` passed with `344 passed`; official review gate ended `review_manually` because Claude approved with notes while Gemini/Codex fallback were unusable under local resource pressure. Notes were addressed and native follow-up review approved. Rerun review gate before presenting a commit candidate if reviewer resources are healthy. |
| Done | Measured read-only KIS call budgeting | KIS read-only universe artifacts include timestamp-based `budget_evidence`; monitor consumes request count, latency bucket, and budget status from API reports. |
| Done | No-order field snapshot runner | `field-dry-run-monitor --market-data-report` consumes one KIS read-only quote artifact as a shared snapshot stream and fans out to primary/shadow no-order engines. When CSV input is also supplied, prior bars warm up strategy state before current KIS snapshots. |
| Done | Durable dry-run resume/recovery | `dry-run-resume-state` reconstructs latest session, open positions, cash, portfolio state, checkpoints, and risk events from the DB ledger. |
| Done | Daily post-close universe routine | `build-daily-field-universe` wraps the prior-only universe builder and writes next-session universe plus KIS symbol-list artifacts. |
| Done | News/DART adapter | `collect-news-risk-events` normalizes generic news JSON, DART-style disclosure JSON, RSS XML, and explicit read-only JSON/RSS URL sources into risk events for `update-news-blacklist`. Local HTTP URL smoke produced `event_count=1`. This is adapter evidence, not KIS news-feed integration evidence. |
| Done | News/blacklist health monitoring | `field-dry-run-monitor --require-news-feed` flags missing, stale, or active blacklist/news state and keeps broker/order readiness false. |
| Done | Daily dry-run review report | Field monitor writes `daily-review/YYYY-MM-DD.md` for both local and KIS-report snapshot runs. |
| Done | Full-universe watchlist evidence | Field monitor writes full-universe watchlist JSON/Markdown artifacts with accumulated observations, latest Top-N derived cuts, reason counts, movement summaries, input-quality flag counts, OHLC/volume/value, source labels, and entry-trigger outcome proxies. Top-N is not yet an operating limit. |
| Done | Checkpoint persistence | Existing checkpoint events persist through dry-run ledgers; field monitor supports `--persist-db` for scenario ledger persistence. |
| Done | Market-session stop guard | `kis-readonly-universe` and `field-dry-run-monitor` support `--enforce-market-session-stop`, `--market-session-date`, and `--market-session-stop-time`; after cutoff the KIS command performs zero read calls and the monitor writes `session_closed` instead of treating the loop as a strategy run. |
| Dry-run session validation | Market-hours no-order dry-run session | Run during real market hours, confirm hard-blocked virtual orders, API budget enforcement, scouter behavior, recovery behavior, daily review output, and no account/order endpoints. |
| Done | 2026-05-13 open-burst 1-symbol KIS timeout | Analysis found the one-symbol `api_timeout` was a transient KIS/network/auth-path failure, not a total read-budget breach: the failed recheck measured 2 calls and peak 2/sec, and the later 100-symbol loop recovered. The source budget gate now also enforces the scouter share limit, so a critical-window peak of 6/sec fails against the 5/sec scouter budget even though it is below the 7/sec operating ceiling. Next field launch should retry a failed single symbol with bounded backoff, reduce scouter pressure after timeout, and avoid repeating a full burst immediately. |
| Done | Standby artifact reuse gate | `build-field-universe` and `build-daily-field-universe` now support `--reuse-standby-artifact --standby-artifact`. Reuse is allowed only when the JSON parses, target date matches, mode is `prior-only-read-only`, broker/order readiness is false, safety boundary is read-only, and included/KIS symbol lists are non-empty and aligned. Valid reuse writes the requested report and KIS symbol list with `loaded_bar_count=0`; stale, broker-ready, empty, malformed, or wrong-date artifacts fail closed. Source data readiness remains a 60-trading-day standard: missing data must be collected to completion before universe selection rather than handled as restricted operation. |
| Done | Terminal close-status writer | `field-dry-run-monitor` stop guard now calls a source-level terminal status writer that preserves existing `scenario_results`, `snapshot_contract`, watchlist, and daily-review evidence while forcing `session_closed`, `market_session_closed`, `order_hard_block=true`, and broker/order readiness false. Existing daily reviews are no longer overwritten by after-close repair runs. |
| Done | 100-symbol refresh cadence compression | Post-close analysis identified that the 209.5s average refresh was dominated by full-universe price+depth collection, not the 60s loop sleep. The accepted next policy is an active 20-50 symbol bucket per target cycle, slower backup rotation, staged startup probes, and scouter share enforcement; full 100-symbol scans remain comparable baseline/backup evidence rather than the only intraday cadence. |
| Done | Zero-candidate filter sensitivity audit | The 0-candidate result was not a clean strategy rejection: the launch loaded only 3 prior sessions for 102/102 symbols, while the day-side strategy required at least 5 prior closes before universe gating could pass. Watchlist reports now include `strategy_warmup_diagnostics` and flag `strategy_warmup_insufficient` when zero passes are caused by insufficient prior sessions, preventing this state from being misread as a valid no-entry outcome. |
| This-week baseline | News defense OFF for the first field dry-run week | Keep KIS news/disclosure auto-collection disabled this week so the baseline isolates KIS quote snapshots, no-order monitor stability, API budget, scenario fan-out, storage, and reports. Do not launch with `--require-news-feed`; manual blacklist injection remains allowed for operator-confirmed critical news. |
| Blocked input | Next-session universe production | Current 2026-05-14 universe build is fail-closed: latest prior source date is 2026-05-07, expected prior trading date is 2026-05-13, included symbols are 0, and the KIS symbol list is empty. Collect or refresh 60 trading days of KIS daily bars, then rebuild and verify a non-empty next-session symbol list before the next open. |
| Operational validation pending | Storage retention/cleanup practice | Keep compact field decision data and accepted evidence; cleanup duplicate/intermediate artifacts without touching accepted evidence. |
| Weekend follow-up | Split the growing CLI and dry-run surfaces into command-group/domain modules after this week's dry test. | Accepted short-lived risk for this user-approved pre-dry-run infrastructure slice and the already-planned no-order dry-run only: after this slice is verified, do not add further command groups or broaden `src/zurini/dry_run.py` before the split unless fixing a verified dry-run blocker. Keep all current CLI commands backward compatible while moving API smoke/KIS universe, dry-run monitor, universe build, ops commands, dry-run contracts, persistence, reports, and policy helpers out of the monolithic surfaces; run full verify and review gate after the weekend refactor. |
| Weekend follow-up | KIS news/disclosure subscription collector | Implement the old-plan intended source path after modularization: KIS-provided news/disclosure feed or subscription if available, source heartbeat, event normalization, blacklist update, stale/fail-close behavior, and no-order monitor integration. Keep it separate from quote polling so news defects cannot destabilize the quote snapshot runner. |
| Next-week comparison | News defense ON/OFF dry-run comparison | Run comparable dry-run windows with news defense OFF baseline, news defense ON with healthy heartbeat, and news defense ON with stale/fail-close simulation. Promote the news path only if it improves risk filtering without creating API, heartbeat, or false-positive instability. |
| Future follow-up | Market-risk feed: Nasdaq futures, beta throttle, and index/regime state | The current no-order dry-run defaults these risk inputs locally and must not claim live risk-throttle parity. Define explicit read-only sources, heartbeat/freshness rules, fail-closed or degrade behavior, and report fields before using range/bear or beta-throttle evidence for field-start approval. |
| Future follow-up | Correlation and theme concentration risk | Implement the archived enhanced-plan cap for highly correlated holdings, or document a rejected replacement. It needs a defined data source, lookback, grouping/proxy method, and report fields before it can affect field-start sizing decisions. |
| Future follow-up | KIS condition-search or push candidate feed | The current runner polls the accepted 100-symbol universe and does not implement the old-plan Tier 2 condition-search push or volume-spike push path. After the baseline polling week, evaluate whether KIS condition-search/push is available and useful; if adopted, keep it read-only, source-labeled, rate-budgeted, and comparable against the polling-only baseline. |
| Weekend/UI follow-up | Operator hard-stop and heartbeat alerts | Dashboard/control work must include no-order hard stop, run-state freeze, alert visibility, and periodic heartbeat/status checks. It must not expose discretionary order buttons; real emergency liquidation remains part of the later owner-approved order-stage plan. |
| Weekend follow-up | Start the operator UI alert/dashboard MVP after CLI modularization. | UI consumes persisted checkpoint events and dry-run reports; it does not create a separate source of truth. Initial composition is defined in `docs/operator-dashboard-plan.md`; first UI has no discretionary order buttons or account actions. |
| Future separate plan | Define the later order-stage plan separately. | Separate owner-approved plan covers broker connection, account reads, paper/live order controls, IOC/backoff execution behavior, emergency liquidation, partial fills, and real fill/slippage measurement. |

## Pre-Dry-Run Required TODO Evidence

Ralph run `pre-dry-run-required-todo-ralph-20260511T165432Z` narrows the
pre-dry-run gate to the items that must exist before an operational no-order
field dry-run can start. Evidence status is module-level and no-order only; it
does not approve paper/live orders or account actions.

| Required item | Evidence status | Evidence |
| --- | --- | --- |
| Measured KIS read-call budgeting | Verified local/no-order only | KIS read-only universe artifacts now include timestamp-based `budget_evidence`; monitor consumes read-call count, latency bucket, and budget status from API reports. Target tests: `tests/test_api_budget.py`, `tests/test_api_smoke.py`, `tests/test_dry_run.py`. |
| No-order field snapshot runner | Verified local/no-order only | `field-dry-run-monitor --market-data-report` consumes one KIS read-only quote artifact as a shared snapshot stream and fans out to primary/shadow no-order engines. |
| Dry-run resume/recovery | Verified local/no-order only | `dry-run-resume-state` reconstructs latest session, open positions, cash, portfolio state, checkpoints, and risk events from the DB ledger. |
| Daily post-close universe routine | Verified local/no-order only; current input blocked | `build-daily-field-universe` wraps the prior-only universe builder with a daily routine command and produces universe plus KIS symbol-list artifacts. The current 2026-05-14 run correctly fails closed until daily bars are refreshed through the expected prior trading date. |
| News/DART adapter | Verified local/no-order only | `collect-news-risk-events` normalizes generic news JSON, DART-style disclosure JSON, RSS XML, and explicit read-only JSON/RSS URL sources into risk events for `update-news-blacklist`. URL fetch path produced `event_count=1` in local HTTP smoke. This proves the adapter path only; KIS-provided news feed integration is still separate follow-up. |
| News/blacklist health monitoring | Verified local/no-order only | `field-dry-run-monitor --require-news-feed` flags missing, stale, or active blacklist/news state and keeps broker/order readiness false. |
| This-week news OFF baseline | Operating decision | Keep the first no-order field dry-run week without automatic news collection. This preserves a clean infrastructure baseline. If critical news is manually confirmed, inject it through the existing news event or blacklist artifact path and record the operator source note. |
| Daily dry-run review report | Verified local/no-order only | Field monitor writes `daily-review/YYYY-MM-DD.md` for both local and KIS-report snapshot runs. |
| Checkpoint persistence | Verified local/no-order only | Existing checkpoint events remain persisted through dry-run ledgers; field monitor now supports `--persist-db` for scenario ledger persistence. |
| Market-session stop guard | Verified local/no-order only | `kis-readonly-universe` skips network reads after the configured KST stop time; `field-dry-run-monitor` writes `session_closed` without scenario reports after the same guard fires. Target tests: `tests/test_api_smoke.py`, `tests/test_dry_run.py`. |
| Review gate | Verify passed, commit-candidate only | Latest recorded `./scripts/verify.sh` passed with `344 passed`. Review gate ended `review_manually` because external/fallback reviewer coverage was incomplete; native follow-up review approved the fixes. |

Maintenance risk accepted only for this user-approved pre-dry-run slice and
through the first no-order field dry-run:
`src/zurini/cli.py` and `src/zurini/dry_run.py` are intentionally frozen rather
than expanded further. After the dry-run gate, split them before adding new
command groups, strategy families, or reporting surfaces. Several baseline
strategies still duplicate universe, entry-window, liquidity, and stale-risk
checks; before adding new strategy families, consolidate those shared
eligibility checks or add cross-strategy regression tests so a future
field-alignment rule change cannot be patched in only one strategy.

Smoke artifacts from this Ralph run:

- `reports/dry-run/news-risk-events-smoke-2026-05-12.json`
- `reports/dry-run/news-adapter-report-smoke-2026-05-12.json`
- `reports/dry-run/news-risk-events-url-smoke-2026-05-12.json`
- `reports/dry-run/news-adapter-report-url-smoke-2026-05-12.json`
- `reports/dry-run/news-blacklist-fresh-smoke-2026-05-12.json`
- `reports/dry-run/daily-field-universe-smoke-2026-05-12.json`
- `reports/dry-run/daily-field-universe-kis-symbols-smoke-2026-05-12.txt`
- `reports/dry-run/kis-readonly-universe-plan-smoke-2026-05-12.json`
- `reports/dry-run/field-runner-status-fresh-smoke-2026-05-12.json`
- `reports/dry-run/field-runner-fresh-smoke-2026-05-12/daily-review/2026-05-12.md`
- `reports/dry-run/resume-state-smoke-2026-05-12.json`

## Current Implementation Slice

The first no-order infrastructure slice is a local report and historical
CSV dry-run runner with optional durable DB ledger persistence:

```bash
.venv/bin/python -m zurini.cli plan-a-dry-run \
  --trading-date 2026-05-11 \
  --root data/raw/daishin/minute-bars \
  --start-date 2026-05-11 \
  --end-date 2026-05-11 \
  --max-trading-days 1 \
  --persist-db \
  --output reports/dry-run/plan-a-session.json
```

If no `--path`, `--path-list`, or `--root` is provided, the command writes a
metadata-only scaffold for the requested trading date. With CSV inputs, it
loads Daishin/CYBOS minute bars and writes a no-order historical dry-run report
with:

- no-order mode;
- order transmission hard-block evidence;
- Plan A strategy package and Plan B fallback metadata;
- required capital comparison cases: shared-slot Plan A and 40/60 sleeves;
- optional sensitivity cases: 30/70 and 50/50 sleeves;
- observed universe snapshots from loaded CSV symbols;
- scouter candidates, virtual orders, virtual fills, and virtual positions
  when the Plan A strategy emits entries;
- held-symbol, group-cap, and 15:15 lock-step risk/interlock events;
- seed feasibility checks for KRW `1,000,000` and KRW `2,000,000` against all
  required and sensitivity capital cases;
- daily reconciliation count rows;
- opening survival checks for every observed trading day;
- Plan B fallback state when Plan A slot constraints are breached.

With `--persist-db`, the command applies the local schema and stores the
no-order session plus an ordered ledger event stream in:

- `dry_run_sessions`
- `dry_run_ledger_events`

The persisted session is constrained to `mode = no-order` and
`order_hard_block = true`. The ledger is replay-oriented evidence only; it is
not a broker integration and cannot transmit orders.

CSV input mode fails when the provided paths and date filters produce no bars;
metadata-only output is allowed only when no CSV input was requested.
`trading_day_count` is based on processed bar dates, so no-signal days still
count toward dry-run stabilization evidence.

The bounded sensitivity decision record is generated separately:

```bash
.venv/bin/python -m zurini.cli plan-a-sensitivity \
  --output reports/dry-run/plan-a-sensitivity-decision.json
```

The current decision is to keep Plan A defaults as the dry-run baseline. This
is not a broad optimizer result. Future parameter perturbations that improve
robustness without worsening cost, continuity, risk, or field alignment can be
carried as observation-only candidate B evidence without interrupting the
operator for another approval round.

Capital feasibility in this slice is sizing-only. The `simultaneous_day_swing`
flag requires observed day and swing virtual-order evidence and enough per-slot
budget to buy at least one whole share for the observed intended prices. It does
not yet model occupancy, contributions over time, reserved cash, opportunity
loss, or complete daily cash/PnL reconciliation.

The second no-order infrastructure slice is a multi-session local runner:

```bash
.venv/bin/python -m zurini.cli plan-a-dry-run-multi \
  --run-id plan-a-dry-run-202605 \
  --root data/raw/daishin/minute-bars \
  --start-date 2026-05-11 \
  --end-date 2026-05-29 \
  --starting-seed 1000000 \
  --api-rate-limit-per-second 20 \
  --local-free-space-gb 38 \
  --persist-db \
  --output reports/dry-run/plan-a-multi-session.json
```

This command groups local CSV bars by trading day and writes one no-order
session per day plus an aggregate report with:

- session count and trading-day count;
- virtual cash, reserved cash, idle cash, day exposure, and swing exposure;
- realized and unrealized virtual PnL snapshots;
- daily portfolio state snapshots with cash, slots, sleeves, exposure, and PnL;
- scouter decision snapshots for replaying candidate and no-candidate decisions;
- prior virtual swing positions passed into the next day's opening survival
  check;
- daily order-hard-block checkpoint events;
- day-10 and day-20 review checkpoint events when reached;
- capital starvation and operating-ceiling deployment-block checkpoints;
- API rate-limit evidence for the future field API budget;
- storage guardrail checks for the C: drive policy: full raw polling disabled,
  raw burst disabled below 10 GB free space, and protective mode below 5 GB.

In this slice, `api_rate_limit_check` records `local-csv` as the data source and
uses local bars to estimate future field polling pressure. The runner still
makes zero external API calls. The configured `--api-rate-limit-per-second` is
persisted as a contract so a later field-data runner can fail closed before
exceeding the provider limit.
UI implementation remains outside this dry-run ledger slice.

## Next Ralph Scope

The next Ralph run should move from local infrastructure to field-data dry-run
readiness without changing the no-order boundary:

1. Replace local CSV polling estimates with measured read-call budgeting and
   throttle evidence before any external field-data dry-run is allowed.
2. Expand durable DB state recovery beyond latest open-position snapshots into
   a full dry-run resume command.
3. Produce checkpoint events for cooldowns, risk fuses, and field execution
   quality once field data exists.
4. Keep live trading, paper trading, broker connection, account action,
   credential handling, and order transmission outside the scope.
