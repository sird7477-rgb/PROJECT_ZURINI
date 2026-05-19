# Phase 2 Real-Data Runbook

This runbook starts after the owner has placed the two-year 1-minute dataset on
the local PC. Phase 2 is the first real-data backtest stage, not live trading.

Promoted stage/API data source boundary: Korea Investment Securities only.
Two-year historical raw acquisition has one owner-approved exception: Daishin
Securities CYBOS may be used because it is the available source for this history
window. That exception is limited to unpromoted read-only raw intake; it does
not allow orders, account actions, paper trading, live trading, credential
storage, or treating raw files as accepted backtest data before the intake gate
passes.

## Intake Order

1. Keep raw files outside git.
2. Scan the raw minute-bar tree without touching Postgres.
3. Write an acceptance report with explicit thresholds.
4. Fix file/schema/time issues until the acceptance report is `accepted`.
5. Load a small smoke subset into Postgres.
6. Run a limited real-data backtest and compare report shape.
7. Promote the full dataset only after the smoke path is reproducible.

## Expected File Shape

The target structure for phase-2 intake is:

```text
data/raw/daishin/
  minute-bars/YYYYMM/<symbol>.csv
  index-bars/YYYYMM/<index_code>.csv
  symbols/*.csv
  manifests/*.jsonl
```

Current CSV commands accept the established minute-bar column contract:

```text
date,time,open,high,low,close,volume
```

All timestamps are interpreted as Asia/Seoul 1-minute bars. Duplicate
`symbol + timestamp`, invalid OHLC, negative volume/value, and parse errors must
be fixed before DB promotion. Missing minutes are class-specific: index/regime
bars must satisfy a strict session grid, while stock bars are treated as sparse
trade-event evidence unless the source is proven to emit a fully materialized
every-minute grid.

## Rolling Two-Year Minute Dataset

The research/backtest dataset should become a rolling two-year minute-bar
baseline. It is not a live-entry data source and must not widen the no-order
field monitor during the market session.

Current decision as of 2026-05-16: full legacy CSV-to-Postgres migration is
deferred because the estimated Postgres footprint can exceed current local disk
headroom. The code/schema foundation remains analysis-only. Do not run full
historical bulk import, do not delete legacy source CSVs, and do not make this
dataset a field-start dependency until a later accepted storage plan and
integrity gate exist.

Purpose:

- refresh the historical backtest dataset with the newest completed market data;
- preserve a continuous research timeline across the existing two-year legacy
  data and newly collected KIS data;
- support universe recall audit, U30/U50/U80/U100 comparison, day/swing
  simulation candidates, and market/filter replay after close;
- keep 장중 field-run monitoring limited to the selected operating universe.

Storage contract:

- store legacy two-year data and newly collected KIS minute data in the same
  logical time series;
- add row-level source identifiers such as `source`, `vendor`,
  `source_run_id`, `import_batch_id`, and `schema_version`;
- KIS-collected rows must be distinguishable from legacy rows in every report
  and query path;
- retain only the latest rolling two-year research window unless an explicit
  archive task is approved;
- keep raw source files outside git.
- preserve raw source CSVs until a future full migration is accepted, verified,
  and explicitly designated as safe for source-file deletion.

Raw/canonical split:

- raw minute bars preserve source-specific rows and may contain overlapping
  legacy/KIS rows for the same `symbol + timestamp`;
- canonical minute bars are the default backtest/research view and expose one
  selected row per `symbol + timestamp + interval`;
- when sources overlap, canonical priority is KIS over legacy only if the KIS
  row is contract-valid; otherwise keep the accepted legacy row and flag the KIS
  row as degraded in raw evidence;
- do not silently merge conflicting OHLCV values. Conflicts need an import
  report with source, timestamp, field, and selected canonical reason.

Legacy-data compatibility:

- required fields are `symbol`, `timestamp`, `open`, `high`, `low`, and
  `close`; rows missing any required field are rejected;
- `volume` should be loaded when present; if missing, mark the row degraded for
  volume-dependent strategies;
- `value`/`traded_value` may be loaded when present. If computed from
  `close * volume`, mark it as estimated rather than native source data;
- fields used by the current field monitor, including `bid_ask_ratio`, `action`,
  `passed`, `rank`, `reason`, `score`, `strategy_group`, and `input_flags`, are
  part of the research-minute raw/canonical contract. They may be null for
  legacy rows and should be populated by field/replay/KIS-derived rows when
  available;
- `research_minute_raw` / `research_minute_canonical` are minute-data tables
  only. `data_origin` is closed to `legacy-minute-backfill` for the historical
  two-year minute backfill and `field-observation` for intraday field-monitor
  collection. Both origins must use `interval='1m'`;
- universe-selection daily rows are stored separately in
  `universe_daily_raw` / `universe_daily_canonical` with
  `data_origin='universe-selection-source'` and `trading_date`, not a fake
  minute timestamp;
- trade history is stored separately in `trade_runs`, `trade_signals`,
  `trade_orders`, and `trade_positions`. These tables carry `trade_mode`
  (`dry_run`, `field_shadow`, `paper`, `live`) and `strategy_group`
  (`day`, `swing`) so virtual dry-run history, future field/live history, and
  day/swing strategy evidence cannot be collapsed into one ambiguous ledger;
- quote/depth fields, order-book pressure, live `observed_at`, freshness report
  IDs, and KIS payload metadata may be null for legacy rows;
- nullable fields must never be treated as normal defaults. Strategy/filter
  replay that depends on a missing field must be marked degraded or excluded.

Index polling storage:

- The current operating contract is 10-second KIS index polling, not 5-second
  polling.
- Raw KOSPI/KOSDAQ poll snapshots are stored in `index_ticks` with
  `price`, KIS session open/high/low fields, `poll_interval_seconds`,
  `source_run_id`, source/vendor, quality flags, and raw payload metadata.
- Minute-level trend calculations consume `index_bars`, which is the 1-minute
  aggregation of observed tick `price`. KIS session high/low fields are retained
  in `index_ticks` for traceability but are not used as minute-bar high/low.

Recommended quality flags include:

- `value_missing`
- `value_estimated`
- `volume_missing`
- `bid_ask_ratio_missing`
- `legacy_operating_field_missing`
- `quote_depth_missing`
- `observed_at_missing`
- `corporate_action_unknown`
- `source_overlap_conflict`
- `kis_row_degraded`

Cutoff discipline:

- universe construction for date `D` may use only data available through `D-1`;
- day/swing replay for date `D` may use date `D` minute/quote/depth data only
  after the simulated decision timestamp;
- universe recall audit combines the `D-1` universe with the date `D` full
  research minute dataset to classify missed watch candidates;
- no report may present rolling research data as field-start promotion evidence
  unless its source, freshness, continuity, and strategy-specific data contract
  pass the relevant gates.

Implemented analysis-only command foundations (2026-05-16):

```bash
.venv/bin/python -m zurini.simulation_analysis_cli research-minute-import \
  --path sample/research-minute-bars.csv \
  --source legacy-daishin \
  --vendor daishin \
  --source-run-id historical-seed \
  --import-batch-id research-20260516 \
  --output reports/phase2/research-minute-import.json

.venv/bin/python -m zurini.simulation_analysis_cli research-minute-retention \
  --retention-days 730 \
  --output reports/phase2/research-minute-retention.json
```

`research-minute-import` inserts raw rows and refreshes canonical selection for
imported keys. `research-minute-retention` reports or applies rolling-window
deletes. Both remain analysis-only/no-order workflow components.

Field-start DB hygiene:

- verify Postgres is responsive before field operation;
- verify no historical bulk import or cleanup query is running;
- verify `research_minute_*`, `universe_daily_*`, and `index_bars` have no
  unintended `historical-db-*` partial residue;
- verify local disk headroom is sufficient;
- treat historical research-data migration as deferred. This preflight must not
  trigger bulk import or source CSV deletion during market-session startup.

## Bar Continuity Policy

Detailed promotion rules live in
[`phase-2-data-continuity-criteria.md`](phase-2-data-continuity-criteria.md).

Do not reject raw Daishin files only because `gap_count` is high. The collector
may receive trade-event bars rather than a fully materialized every-minute grid,
and sparse/illiquid symbols, suspensions, holidays, and non-session time can
create legitimate gaps.

Phase-2 uses three continuity layers:

1. Raw intake: require parse success, no duplicate `symbol + timestamp`, and
   record `gap_count`, `missing_minutes_count`, and `max_gap_minutes`.
2. Strategy promotion: do not forward-fill individual stock prices for signal
   generation by default. Missing stock bars mean "no fresh quote/no signal" for
   that symbol until a later strategy explicitly opts into a fill policy.
3. Trade audit: every backtest report records `trade_continuity` for entry and
   exit timestamps. A trade whose entry or exit window has missing nearby bars is
   evidence to review before using the result for strategy decisions.

For the phase-2 short-term baseline, positions must not silently carry across
sessions. The backtest engine liquidates open positions on the previous
available bar before the next KST trading date and records the exit reason as
`day-end`. Optional `max_holding_minutes` may be added in the backtest config
when a stricter intraday holding cap is needed.

Backtest reports also include `trade_continuity_summary`, which separates
continuity-valid trades from continuity-invalid trades. Strategy conclusions
must be based on the continuity-valid segment, not on aggregate PnL inflated by
trades whose entry/exit windows failed the continuity audit.

Index/regime data is stricter than stock data. It drives market-wide filters, so
it must pass a session-grid gate before use. Current collected index files show
`gap_count=0` and `missing_minutes_count=0` across the scanned 15-month set,
while stock files show large gaps and no explicit zero-volume bars. Treat stock
gaps as sparse trade-event evidence until the source contract proves a fully
materialized stock grid.

Until the index acceptance command exists, regime-filtered backtests are
analysis-only. Baseline backtests may continue only with regime filters disabled
or with a report that explicitly marks the missing index gate.

## Gate Command

Use the scan gate before loading Postgres:

```bash
.venv/bin/python -m zurini.cli scan-csv \
  --root data/raw/daishin/minute-bars \
  --source daishin-historical \
  --output reports/phase2/scan.json \
  --acceptance-report reports/phase2/intake-acceptance.json \
  --min-success-rate 1.0 \
  --max-error-count 0 \
  --max-duplicate-timestamps 0 \
  --min-periods 24
```

Start without `--max-gap-count` until the exact Korean market session calendar
is encoded for the acquired source. Once the calendar is explicit, add a strict
gap threshold for index/regime data first, then a strategy-specific threshold
for stock data. Use `--max-missing-minutes` and `--max-gap-minutes` only after
deciding whether the target source represents every session minute or only
trade-event bars.

Use the phase-2 coverage profiler to apply the class-specific gate:

```bash
.venv/bin/python -m zurini.cli phase2-coverage \
  --root data/raw/daishin/index-bars \
  --class-mode index-grid \
  --source daishin-historical \
  --require-day-set \
  --output reports/phase2/index-coverage.json
```

For sparse stock bars, the same command profiles coverage without failing only
because gaps exist:

```bash
.venv/bin/python -m zurini.cli phase2-coverage \
  --root data/raw/daishin/minute-bars \
  --class-mode stock-sparse \
  --period 202604 \
  --source daishin-historical \
  --progress-every 100 \
  --output reports/phase2/stock-coverage-202604.json
```

Use `--require-day-set` when a stock month is being treated as a completed
month for rehearsal planning. Without that flag, stock sparse coverage remains
profiling evidence only and must not be used as a full month-completion proof.

Backtest trade continuity keeps the legacy `dense-window` default for old
artifacts. For sparse Phase 2 stock trade-event data, pass
`--trade-continuity-mode exact-bar` explicitly; use `dense-window` only for
materialized grids or a strategy that explicitly requires every-minute stock
state.

Do not run stock coverage against the full raw tree as the primary workflow.
Profile completed months separately with `--period YYYYMM`; use `--limit-files`
for smoke checks before full monthly profiling, and use `--progress-every` for
long-running monthly profiles so the log proves active progress.

For large local datasets, prefer monthly scan jobs with durable logs instead of
a full-root scan as the primary workflow. A full-root scan may be kept as a
final reconciliation step, but progress tracking should be based on per-month
start time, end time, exit code, and output artifact path.

When several months have already been collected, prepare a stable completed
month rehearsal set before running heavier DB backtests:

```bash
.venv/bin/python -m zurini.cli phase2-monthly-plan \
  --root data/raw/daishin/minute-bars \
  --output-dir reports/phase2/monthly-rehearsal \
  --limit-symbols 100 \
  --coverage-report reports/phase2/stock-coverage-202604.json
```

The plan excludes the current collecting month by default, selects the latest
contiguous completed-month range, finds symbols common to every selected month,
writes `monthly-plan.json`, and writes `backtest-paths.txt`. Use repeated
`--month YYYYMM` arguments for a narrower contiguous range. The command rejects
current/future months and non-contiguous explicit month selections. When
coverage reports are supplied, directory existence is not enough: a month must
have `acceptance_status=accepted`, `day_set_evaluated=true`, and
`day_set_complete=true` to be selected for local rehearsal. Reports generated
from the project-managed seed still carry `calendar_certified=false`, so they
are not field-test promotable without a certified KRX/KIS-derived calendar.

When a seed calendar would falsely reject whole months, build an observed index
session block instead. This preserves continuous tradable ranges without
promoting unknown calendar assumptions:

```bash
.venv/bin/python -m zurini.cli phase2-observed-plan \
  --index-root data/raw/daishin/index-bars \
  --stock-root data/raw/daishin/minute-bars \
  --output-dir reports/phase2/observed-session \
  --limit-symbols 100 \
  --min-trading-days 20
```

The observed-session plan uses matching index minute grids to define tradable
blocks, then selects a deterministic sparse stock universe for those block
periods. The output is analysis/optimization rehearsal evidence only; official
KRX/KIS calendar certification is still required before field-test promotion.

Local operating evidence can be recorded without network, broker, account, or
order side effects:

```bash
.venv/bin/python -m zurini.cli ops-status \
  --report reports/phase2/monthly-rehearsal/monthly-plan.json \
  --output reports/ops/status.json

.venv/bin/python -m zurini.cli chaos-plan \
  --output reports/ops/chaos-plan.json
```

## Smoke Backtest

After the intake report is accepted, run a small DB smoke:

```bash
.venv/bin/python -m zurini.cli backtest-csv \
  --root data/raw/daishin/minute-bars \
  --source daishin-historical \
  --limit-files 10 \
  --output-dir reports/phase2/smoke-backtest
```

The smoke run proves file parsing, DB insert, DB fetch, strategy wiring, and
report generation. It also writes `trade_continuity` into `report.json` so
entry/exit windows can be audited. It is not a profitability verdict.

Historical DB import remains dry-run by default. Use `historical-db-import
--apply` only for a bounded local DB insert, and keep `--limit-files` present
until the full storage migration plan is accepted.

For real-data rehearsal beyond smoke size, select a contiguous completed month
range and a stable common symbol set. Do not mix actively collecting partial
months into strategy-performance interpretation.

For a completed-month rehearsal generated by the monthly planner, run:

```bash
.venv/bin/python -m zurini.cli backtest-csv \
  --source daishin-historical \
  --path-list reports/phase2/monthly-rehearsal/backtest-paths.txt \
  --output-dir reports/phase2/monthly-rehearsal/backtest
```

After one or more phase-2 backtests complete, write an operational batch
summary:

```bash
.venv/bin/python -m zurini.cli phase2-summarize-runs \
  --root reports/phase2/monthly-rehearsal \
  --output-json reports/phase2/monthly-rehearsal/batch-summary.json \
  --output-md reports/phase2/monthly-rehearsal/batch-summary.md
```

The batch summary aggregates inserted rows, trades, net PnL, exit reasons, and
continuity-valid versus continuity-invalid trades. Treat
`continuity_status=review-required` as an analysis gate, not as a strategy
verdict. This summary is operational evidence that the pipeline ran and that
continuity risks are visible; it is not profitability evidence.

## Stop Conditions

Stop and fix data before full promotion when:

- `acceptance.status` is `rejected`.
- Any CSV path is in `error_paths`.
- Duplicate timestamps are non-zero.
- The symbol or period count is lower than expected.
- Index files and symbol metadata are missing for the intended strategy filter.
- `trade_continuity.status` is `failed` for trades used in a strategy decision.
- `trade_continuity_summary.invalid_trades` materially drives aggregate PnL.
- Any trade meant to represent the short-term baseline exits after the entry
  KST trading date without an explicit approved carry rule.
- Report generation succeeds but the dataset coverage is visibly incomplete.
