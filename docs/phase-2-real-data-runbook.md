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
  --limit-symbols 100
```

The plan excludes the current collecting month by default, selects the latest
contiguous completed-month range, finds symbols common to every selected month,
writes `monthly-plan.json`, and writes `backtest-paths.txt`. Use repeated
`--month YYYYMM` arguments for a narrower contiguous range. The command rejects
current/future months and non-contiguous explicit month selections.

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
