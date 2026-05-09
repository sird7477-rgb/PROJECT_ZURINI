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

All timestamps are interpreted as Asia/Seoul 1-minute bars. Missing minutes,
duplicate `symbol + timestamp`, invalid OHLC, negative volume/value, and parse
errors must be fixed before DB promotion.

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
gap threshold.

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
report generation. It is not a profitability verdict.

## Stop Conditions

Stop and fix data before full promotion when:

- `acceptance.status` is `rejected`.
- Any CSV path is in `error_paths`.
- Duplicate timestamps are non-zero.
- The symbol or period count is lower than expected.
- Index files and symbol metadata are missing for the intended strategy filter.
- Report generation succeeds but the dataset coverage is visibly incomplete.
