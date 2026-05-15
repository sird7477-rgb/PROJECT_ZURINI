# Strategy Pipeline Trust Audit

This audit checks whether the current phase-2 backtest pipeline is reliable
enough to begin candidate strategy decision records. It does not validate
profitability. It only decides which candidate classes can be tested, which
remain analysis-only, and which need implementation or data work first.

## Summary Verdict

Overall status: **conditional pass for slow/daily-style candidates; analysis-only
for intraday execution-sensitive candidates**.

Current pipeline is strong enough to proceed with decision records for Candidate
A and conditional work on Candidate F. Candidates B, C, D, and E should not move
to optimizer or promotion until their specific data/execution gates are cleared.

| Area | Status | Candidate impact |
| --- | --- | --- |
| Sparse stock bars | pass with constraint | A/F can proceed with observed-bar or daily-style contracts; B/C/E remain analysis-only until stale/missing-bar rules are explicit. |
| Index alignment | analysis-only | D/E can be designed, but regime/relative-strength promotion waits for accepted index coverage and calendar certification. |
| Capital model | pass with constraint | Candidate records must use KRW 1,000,000, whole-share sizing, `shared-slot` or an explicitly approved equivalent. |
| Trade continuity | pass | Exact-bar sparse audit and valid/invalid trade summaries exist and must be used for sparse Daishin stock runs. |
| Session/carry rules | needs candidate contract | Intraday day-end exits are supported; overnight/swing candidates need explicit carry and gap rules. |
| Cost model | pass with approximation | Fee/slippage and stop-first stress are representable; field fill quality remains an accepted approximation or field-only measurement. |
| Data-source parity | blocks promotion | Daishin historical data may differ from later KIS/field data; record a source-gap register before promotion. |
| Execution contract | blocks intraday promotion | Order type, queue position, partial fills, failures, timeout, and cancel/retry are not fully backtest-representable. |
| Universe construction | needs candidate contract | Prior-only universe rules must be written before Candidate A or any optimizer run. |
| Strategy-contract parity | needs candidate contract | Every rule that can change trade selection, timing, sizing, risk, exits, or reporting must match the field-test contract or block the run. |

## Evidence Reviewed

- `docs/phase-2-data-continuity-criteria.md` defines strict index-grid and sparse
  stock trade-event classes.
- `src/zurini/data/continuity.py` supports `dense-window` and `exact-bar` trade
  continuity audit modes.
- `src/zurini/cli.py` writes `trade_continuity` and
  `trade_continuity_summary` into backtest reports.
- `src/zurini/backtest/engine.py` supports `quantity_step`, `capital_mode`,
  `shared-slot`, `max_open_positions`, daily stop-loss count, and daily loss
  fuse controls.
- `src/zurini/backtest/engine.py` now supports weekly external contributions,
  variable shared-slot count from account equity, per-slot capital caps, and a
  configured KST day-end exit cutoff.
- `src/zurini/cli.py` records phase-2 backtest parameters, including cost,
  capital, strategy, regime, relative-strength, and execution-path settings.
- `src/zurini/cli.py` exposes `phase2-coverage` with class-specific coverage
  profiling and day-set reporting.
- `src/zurini/strategies/regime.py` builds regime state from prior daily closes,
  which is structurally compatible with no-lookahead regime computation.

## Audit Results

### Sparse Stock Bars

Status: **pass with constraint**.

Current stock data should be treated as sparse trade-event bars, not as a
materialized every-minute grid. This is acceptable for strategies that signal
only on observed bars or daily aggregates. It is not enough for strategies that
need continuous intraday state unless they define stale-bar and fill policies.

Required rule:

- sparse stock backtests must use exact-bar continuity;
- missing stock bars mean no fresh quote/no signal unless a candidate explicitly
  defines a fill policy;
- intraday candidates must reject stale comparisons.

Candidate impact:

- A: testable after prior-only universe contract.
- F: conditional, because daily aggregation must be reproducible.
- B/C/E: analysis-only until stale/missing-bar handling is explicit.

### Index Alignment

Status: **analysis-only**.

Index data has stronger grid assumptions than stock data, and the pipeline has
coverage profiling for index grids. However, promotion still needs accepted
index coverage for the tested periods and calendar certification for long-range
field-test claims.

Required rule:

- D/E may be designed and used for analysis;
- optimizer and promotion using index filters require accepted index coverage;
- field-test promotion requires certified calendar/day-set evidence.

Candidate impact:

- D: analysis-only until index gate and calendar requirements pass.
- E: analysis-only until symbol/index synchronization is proven.

### Capital Model

Status: **pass with constraint**.

The backtest engine supports `quantity_step`, `shared-slot`, fixed or variable
slot limits, per-slot capital caps, weekly external contributions, daily
stop-loss count, and daily realized-loss fuse. That is enough to model the
intended KRW 1,000,000 small-account constraint at a first pass.

Required rule:

- candidate records must specify start equity, quantity step, capital mode,
  max open positions or variable slot-count formula, per-slot cap, weekly
  contribution schedule, daily loss fuses, and whether whole-share sizing is
  used;
- default candidate tests should use a field-test-like shared capital pool
  unless the candidate explicitly requires another model.

Candidate impact:

- All candidates must use the same small-account capital contract before
  performance comparison.

### Trade Continuity

Status: **pass**.

The pipeline can emit both point-level continuity and trade-level valid/invalid
summaries. This is sufficient to block optimization on invalid trades if the
candidate run uses the correct audit mode.

Required rule:

- sparse Daishin stock strategy runs must pass `--trade-continuity-mode
  exact-bar`;
- optimization metrics must use continuity-valid trades only;
- any invalid trade in the selection segment blocks optimizer comparison unless
  a later documented threshold replaces the strict initial rule.

Candidate impact:

- All candidates can use continuity gating.
- B/C/E remain sensitive because their signals are intraday and stale-bar risk
  can exist even when exact entry/exit bars exist.

### Session And Carry Rules

Status: **needs candidate contract**.

Intraday day-end exits are representable as either session-boundary liquidation
or a configured same-session KST cutoff such as `15:15`. Max holding minutes are
representable. Overnight and swing behavior still require a candidate-specific
carry rule, gap treatment, and forced-exit policy before backtesting can be
interpreted.

Required rule:

- every candidate must declare decision cadence and max holding behavior;
- F cannot move beyond conditional until overnight/carry and gap rules are
  written;
- day-end behavior in backtest must match the intended field-test behavior.

Candidate impact:

- A: likely manageable if daily/near-close contract is written.
- F: conditional until carry contract exists.
- B/C: likely intraday only unless separately redesigned.

### Cost Model

Status: **pass with approximation**.

The pipeline can model fees, slippage, hard stop, profit target, intrabar policy,
and ambiguous stop-first behavior. This is sufficient for conservative stress
tests, but not for proving exact field fills.

Required rule:

- every candidate must define base cost, 2x cost stress, and stop-first or gap
  stress where applicable;
- slippage assumptions are backtest approximations, not field execution proof.

Candidate impact:

- A/F can proceed with explicit stress.
- B/C need heavier execution stress because their edge is more fill-sensitive.

### Data-Source Parity

Status: **blocks promotion**.

The current historical raw source is Daishin CYBOS under an owner-approved
read-only exception. Later promoted/field boundaries are KIS-oriented. Timestamp
semantics, adjusted price behavior, symbol status metadata, and volume/quote
semantics may differ.

Required rule:

- each candidate must include a source-gap register;
- backtest may select research candidates, but data-source gaps block field-test
  promotion until accepted or measured.

Candidate impact:

- All candidates are limited to backtest research until source gaps are
  documented.

### Execution Contract

Status: **blocks intraday promotion**.

The backtest can approximate fills with price, slippage, and pessimistic
intrabar policies. It does not fully represent field order type, queue position,
partial fills, order rejection, API latency, timeout, cancel/retry, or session
disconnects.

Required rule:

- field-only execution controls must not be credited to historical PnL;
- B/C cannot be promoted until execution-gap stress and field rehearsal logging
  are defined;
- A/F still need order/fill assumptions, but their slower cadence reduces this
  gap.

Candidate impact:

- B/C remain analysis-only.
- A/F remain the preferred first candidates.

### Universe Construction

Status: **needs candidate contract**.

The pipeline can run selected symbols, but candidate-specific universe selection
must be prior-only. A strategy must not use future survivorship, future
liquidity, or metadata that would not have existed at the simulated decision
time.

Required rule:

- Candidate A must define prior-only universe construction before rerun;
- optimizer runs must not compare candidates over hindsight-selected universes;
- metadata availability timing must be recorded.

Candidate impact:

- A is not ready to rerun until its universe contract is written.
- All optimizer work is blocked until universe selection is documented.

### Strategy-Contract Parity

Status: **needs candidate contract**.

Universe construction is only one example of a wider risk: the backtest can
quietly test a different strategy than the one that will later run in field
test. This happens when any operating rule differs, even if the parameter name
looks similar.

Required rule:

- each candidate must classify every strategy rule that can affect trade
  selection, timing, sizing, risk, exits, or reporting;
- rules must be marked as `backtest-exact`, `backtest-conservative-approx`,
  `field-only-measurement`, `missing`, or `different-from-field`;
- `different-from-field` blocks the run when it changes candidate selection,
  signal timing, entry, exit, sizing, or risk behavior;
- conservative approximations must be explicitly pessimistic and stress-tested;
- field-only measurements must be excluded from historical PnL attribution and
  measured later in field rehearsal logs.

Examples of strategy-contract mismatch:

- daily universe refresh in backtest when the field test refreshes monthly or
  less often;
- full-market per-minute scan in backtest when field infrastructure can scan
  only a restricted symbol set or slower cadence;
- same-day data used to construct the tradeable universe before the simulated
  decision time;
- backtest exits at a bar price while the field contract uses order timeout,
  cancel/retry, partial fill, or next-observable-price behavior;
- backtest position sizing assumes independent capital per symbol while field
  execution uses shared KRW 1,000,000 cash and blocked capital;
- backtest allows re-entry or stop/take behavior that field safety rules would
  suppress.

Candidate impact:

- All candidates need a parity checklist before performance tests.
- Candidate A remains blocked until its universe refresh cadence, scan cadence,
  and prior-only metadata timing are written.
- B/C need stricter scan, stale-data, and fill-parity definitions before they
  can leave analysis-only status.

## Candidate Routing After Audit

| Candidate | Audit routing | Reason |
| --- | --- | --- |
| A Defensive daily pullback | next decision-record candidate | Best current alignment, but needs prior-only universe and source-gap register. |
| F Low-volatility support swing | conditional second candidate | Slower cadence helps, but carry/gap contract is not written. |
| D Index-regime filtered long-only | analysis-only | Needs index acceptance and calendar certification; useful as a filter design. |
| E Relative-strength long-only | analysis-only | Needs synchronized symbol/index and stale-bar rules. |
| B Intraday VWAP pullback | analysis-only/rewrite | Sparse bars and execution gaps are material. |
| C Breakout momentum | analysis-only/rewrite | Highest execution/slippage sensitivity among current candidates. |

## Backtest/Field-Test Gap Register

| Gap | Class | Applies to | Required action |
| --- | --- | --- | --- |
| Daishin historical vs later KIS/field semantics | blocks-promotion | all | Record source-gap register before promotion. |
| Sparse stock bars are not materialized every-minute grids | accepted-approximation / implementation-needed | B/C/E, partially A/F | Use exact-bar continuity; define stale-bar or aggregation rules. |
| Queue position, partial fills, order failures, timeout, cancel/retry | field-only-measurement | all, especially B/C | Keep out of PnL attribution; measure in later field rehearsal. |
| Seed calendar not final certified calendar | blocks-promotion | D/E and long-range conclusions | Certify KRX/KIS day set before promotion. |
| Prior-only universe not yet written for Candidate A | implementation-needed | A | Write candidate decision record and universe contract before rerun. |
| Overnight/carry policy not written for swing behavior | implementation-needed | F | Write carry/gap/forced-exit contract before test interpretation. |
| Any strategy rule differs between backtest and field-test contract | blocks-promotion / implementation-needed | all | Rewrite the backtest, rewrite the field contract, or version the candidate as a different strategy before performance testing. |

## Next Decision

Proceed to Candidate A decision record only after writing:

- prior-only universe construction;
- KRW 1,000,000 shared-capital contract;
- source-gap register;
- base and stress cost model;
- exact-bar continuity requirement;
- full strategy-contract parity checklist;
- default/coarse parameter boundary;
- alignment verdict using the documented 100-point rubric.

Do not run Candidate A performance tests before those items are written.
