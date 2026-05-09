# Phase 2 Data Continuity Criteria

Phase 2 must separate data quality validation from strategy optimization.
Promotion gates are class-specific: index bars are treated as a strict session
grid, while stock bars are currently treated as sparse trade-event bars unless a
source contract proves otherwise. A strategy result is usable only after the
applicable source-bar gate, index regime gate, and trade-level continuity gate
all pass.

## Current Evidence

- Index scan: `reports/phase2/index-scan-current.json`
  - `file_count=45`
  - `period_count=15`
  - `error_count=0`
  - `duplicate_timestamp_count=0`
  - `gap_count=0`
  - `missing_minutes_count=0`
  - `max_gap_minutes=0`
  - `zero_volume_count=7068`
- Stock scan: `reports/phase2/realdata-rehearsal-20260509/scan-all.json`
  - `file_count=15014`
  - `period_count=6`
  - `error_count=0`
  - `duplicate_timestamp_count=0`
  - `gap_count=10363324`
  - `missing_minutes_count=31910878`
  - `max_gap_minutes=388`
  - `zero_volume_count=0`

Interpretation: the current index files behave like a materialized session grid.
The current stock files behave like trade-event bars, because they have many
missing minutes but no explicit zero-volume bars.

## Continuity Classes

### Class A: Index And Market Regime Bars

Index/regime data drives market-wide filters, so it must be strict.

Required before use:

- parse success rate: `100%`
- duplicate `index_code + timestamp`: `0`
- expected session minutes are derived from a named exchange calendar version
- observed session minutes equal expected session minutes
- intraday gap count: `0`, after weekends, holidays, and shortened sessions are
  excluded by the calendar
- missing open/close edge minutes: `0`
- zero-volume bars: allowed only if OHLC is valid and the timestamp exists in
  the expected grid

Stop condition: if index bars have gaps, do not run market-regime filters for
that interval. A strategy run using a broken index interval is analysis-only.

### Class B: Stock Trade-Event Bars

Individual stock files may be sparse. Missing stock bars are not automatically a
data defect because the source may omit minutes with no trade.

Required before DB promotion:

- parse success rate: `100%`
- duplicate `symbol + timestamp`: `0`
- valid OHLC shape: positive prices with `high >= low`, `high >= open`,
  `high >= close`, `low <= open`, and `low <= close`
- nonnegative volume
- nonnegative derived value, where value is computed from accepted
  `close * volume`
- timestamps inside the expected KST market session after an explicit
  session-calendar gate exists

Class B stock gaps are profile metrics by default. Do not fail DB promotion only
because `gap_count` or `missing_minutes_count` is high unless the source is
proved to be a materialized every-minute grid or the strategy declares an
every-minute fill policy.

Default strategy policy:

- do not forward-fill stock prices for signal generation
- treat a missing stock bar as `no fresh quote/no signal`
- do not infer a tradable price from a missing minute
- allow a signal only on an observed bar

Stop condition: if a strategy requires every-minute stock state, it must declare
a fill policy first. Without that policy, sparse stock bars cannot support that
strategy.

### Class C: Trade-Level Continuity

Every generated trade must prove that both the entry and exit happened on
acceptable source evidence. The audit mode must match the source class.

Sparse trade-event stock audit:

- require the exact entry bar to exist for the traded symbol
- require the exact exit bar to exist for the traded symbol
- report previous and next observed-bar distance around entry and exit
- mark the trade invalid if either exact bar is absent

Dense-grid audit:

- use only for Class A grids or strategies that explicitly require every-minute
  stock state
- check entry timestamp and exit timestamp
- inspect the nearby `+/- 5` minute session window for the same symbol
- mark the trade invalid if either point has missing nearby bars

Current implementation note: the existing `trade_continuity` code performs the
dense-window audit. Before it is used for sparse Daishin stock optimization, it
must either support an exact-bar trade-event mode or clearly label dense-window
invalid trades as grid-continuity findings rather than source defects.

Strategy evaluation rule:

- optimization and performance claims must use continuity-valid trades only
- aggregate PnL that includes invalid trades is operational evidence only
- summary generation may exit successfully while carrying
  `continuity_status=review-required`
- optimization is blocked when either:
  - `invalid_trade_ratio > 0`
  - `abs(invalid_net_pnl) / max(abs(total_net_pnl), 1) > 0`

The initial optimization gate is deliberately strict: any invalid trade blocks
parameter comparison. Threshold relaxation requires a later documented decision,
not an implicit code change.

## Volume-Based Interpretation

Volume is useful, but it cannot solve continuity alone.

- A present bar with `volume=0` means the source explicitly emitted a no-volume
  minute. If OHLC is valid, it may preserve the time grid.
- A missing bar is different. It may mean no trade, source omission, API failure,
  or collection interruption.
- For the current Daishin stock files, `zero_volume_count=0` while gaps are very
  high. That pattern suggests the stock feed is not a fully materialized
  every-minute grid.
- For index files, zero-volume bars exist while gaps are zero. That pattern is
  acceptable for regime data as long as the full session grid remains present.

Practical rule: volume helps distinguish explicit no-trade bars from missing
bars only when the source is known to materialize every session minute. Until
that contract is proven for stock data, absent stock minutes remain `unknown/no
fresh quote`, not confirmed zero-volume minutes.

## Phase 2 Promotion Gates

1. Raw intake gate:
   - all files parse
   - duplicate timestamps are zero
   - invalid OHLC, negative volume, and negative derived value are enforced by
     validation errors until categorized counters exist
2. Index gate:
   - index files pass Class A
   - regime filters may use only passed index intervals
   - before an index acceptance command exists, regime-filtered backtests are
     analysis-only; baseline runs may continue with regime filters disabled
3. Stock strategy gate:
   - no forward-fill by default
   - signals use observed stock bars only
   - stock gaps are profiled by symbol and month, not used as automatic DB
     promotion failures
4. Trade continuity gate:
   - trade reports include `trade_continuity`
   - summaries split valid and invalid trades
   - invalid trades are excluded from optimization metrics
5. Optimization gate:
   - run only on completed months
   - use a stable common symbol set
   - require `invalid_trade_ratio=0` for the initial strict gate
   - require `invalid_net_pnl_ratio=0` for the initial strict gate
   - require completed-month eligibility to be based on coverage, not only
     directory date

## Required Next Implementation Work

- Add an exchange-session calendar so expected minute grids exclude weekends,
  holidays, and shortened sessions.
- Add `out_of_session_count`, `allowed_session_exception_count`, calendar
  version, expected session minutes, observed session minutes, and missing edge
  minutes to acceptance outputs.
- Add a coverage profiler that reports per-month and per-symbol:
  - observed minutes
  - expected session minutes
  - coverage ratio
  - longest missing run
  - zero-volume count
  - first and last timestamp
- Add a strict index acceptance command using the session calendar.
- Add exact-bar trade-event mode to trade continuity checks.
- Add a trade-continuity threshold to batch summaries, so runs can fail the
  optimization gate while still writing operational artifacts.
- Add a strategy-metric view that reports valid-only PnL, invalid-only PnL, and
  invalid-trade ratio separately.
