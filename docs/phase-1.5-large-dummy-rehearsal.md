# Phase 1.5 Synthetic Large-Dummy Rehearsal

## Purpose

Phase 1.5 rehearses the future real-data stage with synthetic data. It stress
checks schema, ingestion, quality gates, backtest wiring, and report generation
without claiming strategy profitability.

Future real market-data/API boundary: Korea Investment Securities only. This
rehearsal does not introduce KRX, Naver, alternate vendors, broker API calls,
paper trading, live orders, or server deployment.

## Local Resource Target

Target owner machine:

- CPU: 13th Gen Intel Core i5-13420H
- RAM: 16 GB
- GPU: 128 MB

The rehearsal therefore uses smoke-to-scale profiles, bounded row estimates, and
accelerated logical time instead of unbounded full 24-month materialization.

## Profiles

Profiles live in `src/zurini/data/large_dummy.py`.

| Profile | Logical months | Symbols | Synthetic trading days/month | Minutes/day | Market rows | Index rows | Use |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `smoke` | 24 | 8 | 1 | 12 | 2,304 | 1,152 | Fast tests and local rehearsal |
| `rehearsal` | 24 | 50 | 2 | 60 | 144,000 | 11,520 | Larger local ingestion/backtest check |
| `scale` | 24 | 200 | 3 | 120 | 1,728,000 | 34,560 | Sizing/dry-run or explicit guarded run |

Logical months are represented by configured synthetic sessions. Timestamps are
KST 1-minute bars, but elapsed wall-clock time is accelerated: no command waits
for real time to pass.

## Data Surfaces

- Market bars: `market_bars` via `db.insert_bars`.
- Dummy index bars: `index_bars` via `db.insert_index_bars` for
  `KOSPI`, `KOSDAQ`, `KOSPI200`, and `NASDAQ_FUTURES` dummy series.
- Symbol metadata: `symbol_metadata` via `db.insert_symbol_metadata`.
- Optional quality fixtures: deterministic gap, zero-volume, duplicate
  timestamp, and invalid-OHLC fixtures are reported by the rehearsal summary.
  Duplicate timestamps and invalid OHLC remain strict validator failures.

## CLI

Fast end-to-end smoke:

```bash
.venv/bin/python -m zurini.cli rehearse-large-dummy \
  --profile smoke \
  --include-quality-anomalies \
  --output-dir reports/phase15-large-dummy
```

Scale sizing without DB/backtest materialization:

```bash
.venv/bin/python -m zurini.cli rehearse-large-dummy \
  --profile scale \
  --dry-run \
  --output-dir reports/phase15-scale-dry-run
```

The command writes `rehearsal-summary.json`; non-dry-run profiles also write a
nested backtest report under `backtest/`.

## Guardrails

- Non-dry-run execution refuses profiles above `--max-materialized-market-rows`
  unless the caller explicitly raises the limit.
- Generated outputs stay under ignored `reports/` paths.
- This is not real data and not a strategy validation result.
- The implementation must not inspect `.env`, store secrets, call a broker API,
  or place live/paper orders.
