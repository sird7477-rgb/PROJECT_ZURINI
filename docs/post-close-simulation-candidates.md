# Post-Close Simulation Candidates

This document tracks analysis-only simulation candidates derived from recent
no-order dry-run evidence. These candidates are not live entry rules and are not
wired into `field-run`, monitor entry triggers, order paths, or promotion
evidence.

## Boundary

- Use these candidates only after close, in backtest/replay/research runs.
- Keep the current Plan A live dry-run strategy unchanged until a separate
  reviewed decision promotes a candidate.
- Use the rolling two-year minute dataset as the preferred research baseline
  only when it is available and source-valid. As of 2026-05-16, full historical
  CSV-to-Postgres migration is deferred because the local DB footprint can
  exceed available disk headroom.
- Until that dataset is accepted, post-close simulations remain artifact/replay
  based, for example from stored watchlist and KIS report JSON files. Do not
  imply that these replay reports are DB-backed research evidence.
- Missing source fields must degrade or exclude only the affected candidate,
  not silently substitute normal values.
- Universe construction for date `D` must use only data available through
  `D-1`.

## Candidate Counts

| Category | Count | Current files |
| --- | ---: | --- |
| Day-trade simulation candidates | 8 | `src/zurini/post_close_day_simulation.py` |
| Swing simulation candidates | 2 | `src/zurini/post_close_swing_rebound.py`, `src/zurini/post_close_swing_relative_strength.py` |
| Filter simulation candidates | 1 | `src/zurini/index_trend.py`, `src/zurini/kis_index_feed.py` |
| Universe audit candidates | 1 | `src/zurini/universe_recall_audit.py` |
| Rolling minute dataset refresh | 1 | `src/zurini/research_minute_dataset.py` |

Existing Plan A day and swing strategies remain the control group.

## Day-Trade Candidates

The day-trade set is closer to an execution optimizer than a set of independent
new strategies. It replays current intraday momentum triggers under different
entry timing and defensive filters.

| Candidate | Purpose |
| --- | --- |
| `day-immediate-baseline` | Control case: replay the current immediate trigger. |
| `day-pullback-reentry-005` | Wait for a shallow `-0.5%` pullback and rebound confirmation. |
| `day-pullback-reentry-010` | Main rollback candidate: wait for `-1.0%` pullback and rebound confirmation. |
| `day-pullback-reentry-015` | Stress deeper rollback entry and missed-winner risk. |
| `day-market-defense-filtered` | Replay day triggers only when index/breadth context is not bearish. |
| `day-spike-fade-guard` | Block chase entries when a symbol already shows spike-and-fade structure. |
| `day-window-0930-1330` | Compare earlier entry access against current `10:00-13:30`. |
| `day-window-1000-1400` | Compare later end-window access against current `10:00-13:30`. |

Current implemented evaluator:

- `day_pullback_reentry_candidate(...)`
- returns a reportable candidate only after a trigger-following pullback and
  rebound sequence appears inside the configured entry window.

Runner foundation:

- `src/zurini/post_close_simulation_runner.py`
- lists the current post-close plan;
- compares filter OFF vs ON entry-symbol gaps;
- sorts candidate summaries by category, accepted count, and average return.

## Swing Candidates

| Candidate | Purpose |
| --- | --- |
| `post-close-swing-rebound` | Find late-day 급락 후 종가 반등 setups using low drop, reclaim from low, range position, volume ratio, and RSI. |
| `post-close-swing-relative-strength` | Find market-weakness survivor names with positive relative edge, bounded adverse movement, recovery from low, sufficient traded value, and non-overheated RSI. |

The existing `SwingSupportStrategy` remains the control group and should not be
merged with these candidates until replay evidence shows a reason to promote or
combine them.

## Filter Candidates

| Candidate | Purpose |
| --- | --- |
| `index-trend-filter` | Optional KOSPI/KOSDAQ trend filter. When enabled, missing/stale/warming-up/bearish evidence blocks day entries only. |

This filter must remain on/off switchable and replayable from stored index trend
reports.

Test-structure follow-up: dry-run connection tests for this filter should move
from the broad `tests/test_dry_run.py` module into a dedicated
`tests/test_dry_run_index_filter.py` file. This split is implemented as a
test-structure cleanup only; runtime behavior is unchanged.

## Universe And Dataset Candidates

| Candidate | Purpose |
| --- | --- |
| `universe-recall-audit` | Compare `D-1` universe membership against date `D` full research minute-bar signals to classify missed watch candidates. |
| `rolling-minute-dataset-refresh` | Maintain a rolling two-year minute-bar research baseline where legacy history and new KIS rows form one continuous series with source flags. |

The universe audit is not a live market-wide scanner. It is a post-close or
weekend recall/coverage audit.

Current storage decision:

- the rolling minute dataset module is a research/backtest data-management
  surface, independent of live `field-run`;
- legacy two-year minute CSV bulk import is deferred and must not run during
  field operation;
- source CSV deletion is deferred with the import and may happen only after a
  future accepted full migration plus integrity verification;
- DB hygiene is checked at field-start/preflight, not treated as an immediate
  recurring cleanup task.

Current foundations:

- `src/zurini/universe_recall_audit.py` compares universe variants against
  post-close signal observations and reports captured/missed symbols;
- `src/zurini/research_minute_dataset.py` normalizes source-tagged minute rows,
  preserves missing-field quality flags, keeps current field-monitor columns
  such as `bid_ask_ratio`, `action`, `passed`, `reason`, `score`,
  `strategy_group`, and `input_flags` nullable for legacy data, prefers
  contract-valid KIS for canonical overlap selection, and applies rolling
  two-year retention helpers.
- `src/zurini/data/schema.sql` and `src/zurini/data/db.py` persist
  `research_minute_raw` and `research_minute_canonical` rows with source/vendor
  metadata, `data_origin`, canonical selection refresh, and rolling retention
  reporting;
- KIS index polling is stored as raw 10-second `index_ticks` plus aggregated
  1-minute `index_bars`; session high/low fields from the KIS snapshot stay in
  `index_ticks` and are not reused as minute high/low for trend reclaim logic;
- `python -m zurini.simulation_analysis_cli research-minute-import`,
  `research-minute-retention`, `post-close-simulation-report`,
  `universe-recall-audit`, and `swing-zero-diagnostics` now provide
  analysis-only JSON report scaffolds for post-close evaluation workflows.

These command/report foundations are still no-order and analysis-only. They are
not wired into live entry, field-run candidate selection, broker calls, account
reads, balance reads, or promotion decisions.

Suggested universe comparison axes:

- `U80-current`: current field universe baseline;
- `U30-tight`: tighter watch universe;
- `U50-balanced`: mid-size watch universe;
- `U100-wide`: maximum current cap;
- `U-day-biased`: day-trade-biased liquidity/volatility ranking;
- `U-swing-biased`: swing-biased support/relative-strength ranking.

## Promotion Gate

A candidate can become a strategy or live filter only after:

- replay uses source-valid rolling minute data or an explicitly labeled
  analysis-only dataset;
- results compare against the existing Plan A control group;
- cost, slippage, continuity, and missing-field degradation are reported;
- no-order dry-run evidence confirms the same applied parameters are recorded;
- review-gate/reviewer evidence accepts the change.
