# Phase 1 Completion Evidence: Dummy-Data Local Backtest

## Status

Phase 1 is ready to treat as a reproducible local dummy-data backtest
foundation. This is framework evidence only; it is not profitability evidence.

## Executable Evidence

Primary command:

```bash
.venv/bin/python -m zurini.cli backtest --output-dir reports/phase1-dummy-backtest
```

Latest known output from the Ralph handoff:

```text
symbols=ZRN001,ZRN002,ZRN003
inserted_rows=90
trade_count=3
net_pnl=295885.6148505115702374418000
```

Expected generated artifacts, ignored by git under `reports/`:

- `reports/phase1-dummy-backtest/report.json`
- `reports/phase1-dummy-backtest/trades.csv`
- `reports/phase1-dummy-backtest/summary.txt`

## Acceptance-Criteria Mapping

| Phase-1 criterion | Evidence |
| --- | --- |
| Python application/test layout from repo root | `pyproject.toml`, `src/zurini/`, `tests/`, `./scripts/verify.sh` |
| Old-document baseline extracted without editing `(old)/` | `docs/phase-1-baseline.md`; verify anchors in `scripts/verify.sh` |
| Docker Compose Postgres local DB | `docker-compose.yml`; integration tests in `tests/test_db_integration.py` |
| Standard 1-minute bar schema | `src/zurini/data/schema.sql` table `market_bars` with key/shape constraints |
| Deterministic dummy bars | `src/zurini/data/dummy.py`; `tests/test_dummy_data.py` |
| Validator positive/negative cases | `src/zurini/data/validation.py`; `tests/test_validation.py` |
| Loader inserts and fetches DB bars | `src/zurini/data/db.py`; `tests/test_db_integration.py` |
| Simple strategy runs through backtest | `src/zurini/strategies/baseline.py`; `src/zurini/backtest/engine.py`; `tests/test_backtest.py` |
| Multi-symbol dummy flow | `config/phase1-backtest.toml`; `tests/test_cli_e2e.py` |
| Minimal deterministic report | `src/zurini/reports/files.py`; JSON/CSV/TXT assertions in `tests/test_cli_e2e.py` |
| Safety guardrails | Non-goals in `docs/phase-1-prd.md`; safety checks in `docs/phase-1-test-spec.md` and `scripts/verify.sh` |

## Current Verification Standard

Phase 1 is complete only when the full project command exits 0:

```bash
./scripts/verify.sh
```

The verification script checks workflow/docs anchors, old-document baseline
anchors, secret-literal absence, Docker Compose Postgres readiness, and pytest.

## Boundaries

- No broker API integration.
- No paper trading or live trading.
- No order placement.
- No credentials or account identifiers in the repository.
- Real historical-data validation starts after this dummy-data target and uses
  Korea Investment Securities only unless the owner explicitly changes that
  decision.
