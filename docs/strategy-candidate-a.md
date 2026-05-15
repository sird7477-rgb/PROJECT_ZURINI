# Strategy Candidate A Decision Record

This document starts Candidate A under the reset process. It is a strategy
contract, not a performance report. Do not run promotional backtests for
Candidate A until the contract items below are implemented or explicitly marked
as accepted limitations.

## Candidate

Candidate A: Defensive daily pullback.

Market hypothesis: liquid symbols that remain structurally healthy after a
prior-only universe screen, then show a controlled intraday pullback under the
scouter, can produce small-account trades with lower execution sensitivity than
breakout or pure VWAP-chase strategies.

## Operating Contract

Default field-test shape:

1. After market close and before next market open, build the first-stage
   universe from prior-only data.
2. After market open, run the scouter against that fixed universe for final
   eligibility checks.
3. Do not select new symbols from the full market intraday unless the field
   contract later explicitly supports that behavior.
4. Use only information observable at the simulated decision time.

Old-plan anchor: `(old)/# [자동매매 전략 기획서].md` describes a night batch
from 16:00 to 08:30, a 09:00 to 09:01 survival check, and 09:01 to 15:20
intraday monitoring. Candidate A adopts that workflow as the default contract,
with exact parameters to be versioned below.

## Strategy Versions

Candidate A is split by holding and exit contract. These are different
strategy versions because the risk profile and backtest-field-test parity are
different.

| Version | Name | Status | Core difference |
| --- | --- | --- | --- |
| A-DAY | Defensive pullback day-trade | Primary first test | Enter only from the fixed daily universe and exit by the same trading day. |
| A-SWING | Defensive pullback swing | Next swing comparison version | Same universe/scouter concept, but overnight carry and max holding days are allowed. |
| A-REGIME | A with index-regime filter | Deferred filter version | Uses Candidate D-style market-regime gating; blocked until index/calendar gate is accepted. |

Prepare A-DAY first, then prepare a swing comparison candidate. A-SWING is not a
rescue extension of A-DAY; it is a separately versioned candidate whose results
must remain separate from A-DAY until portfolio integration.

## A-DAY Contract

Trading horizon: intraday, same-day exit.

Default module version: `A-DAY-U1-S1`.

Universe refresh cadence: once per trading day, between previous market close
and next market open.

Universe timing rule: use previous completed session data and metadata available
before market open. Do not use same-day future liquidity, same-day close, or
post-entry information for universe selection.

Scouter cadence: run after market open against the fixed universe. The scouter
may validate opening gap, observed liquidity, volatility, stale-data rejection,
and pullback eligibility only from data observed by that time.

Aggression profile: conservative. The first A-DAY contract should prefer fewer,
higher-quality candidates over broad intraday discovery. Universe and scouter
filters should initially emphasize liquidity, trend health, controlled
volatility, opening-gap survival, and stale-data rejection.

Old-plan baseline controls to carry forward:

- prior-only liquidity floor: recent 5-trading-day average traded value of KRW
  50,000,000,000 or higher, unless the candidate version documents a more
  conservative threshold;
- prior-only trend filter: prior close above SMA20;
- prior-only opportunity filter: ATR14 divided by current price around 3% or
  higher, subject to later conservative tuning;
- Tier 1 hard exclusions: administrative issue names, investment caution/warning
  names, preferred shares, SPACs, ETF/ETN, and similar non-common-stock or
  exchange-risk categories when metadata is available;
- blacklist freshness gate: if async blacklist data is older than 5 minutes at
  entry time, new entries are blocked rather than credited as backtest alpha;
- same-symbol interlock: skip new entries when the symbol is already held by
  another engine or version;
- same-timestamp day-trade/swing conflict cooldown: if day-trade time-cut and
  swing-entry timing collide, the swing side yields and the symbol is cooled
  down for one trading day.

Universe/scouter module candidates:

| Module | Role | Initial definition | Status |
| --- | --- | --- | --- |
| U1 | Conservative prior-only universe | 5-day traded value KRW 50B+, prior close above SMA20, ATR14/price around 3%+, Tier 1 exclusions where metadata exists. | Default for A-DAY first run. |
| U2 | Looser liquidity/opportunity universe | Lower liquidity or ATR threshold than U1, bounded before testing. | Optional comparison only if U1 coverage is too sparse. |
| S1 | Conservative after-open scouter | Opening survival, observed liquidity, stale-data rejection, controlled pullback eligibility. | Default for A-DAY first run. |
| S2 | Alternative scouter | A predeclared wider or narrower pullback/gap/liquidity check. | Optional comparison only if S1 is too sparse or too broad. |

First-round A-DAY combinations are capped at `A-DAY-U1-S1` plus at most one
predeclared comparison such as `A-DAY-U2-S1` or `A-DAY-U1-S2`. Additional
universe/scouter combinations require a new candidate version or rebuild note.
Do not evaluate U/S modules by standalone PnL; evaluate them through full
A-DAY results plus coverage, stability, turnover, stale-data, and parity
evidence.

Entry contract:

- Candidate A is not a full-market intraday discovery strategy.
- Entry eligibility must come from the fixed prior-only universe plus scouter
  validation.
- Entry timing and price model must be conservative enough to avoid crediting
  unavailable fill quality.

Exit contract:

- Default A-DAY exits all positions by the same trading day.
- Backtest must model a forced day-end exit at 15:15 Korea time or earlier
  stop/take exit.
- Stop/take ambiguity must use stop-first or an equivalent conservative stress.

Capital contract:

- KRW 1,000,000 starting equity.
- Add KRW 100,000 once per week according to the owner's seed growth plan.
- Whole-share sizing.
- Shared capital pool.
- For day-trade versions, cap deployed capital per slot at KRW 10,000,000 or
  lower to reduce Korea-market slippage and execution footprint risk.
- Recommended slot policy is now accepted:
  - slot count is variable with account equity;
  - use one slot while deployable day-trade capital is less than or equal to
    KRW 10,000,000;
  - add slots mechanically as needed so planned deployed capital per slot does
    not exceed KRW 10,000,000;
  - example: KRW 1,000,000 to KRW 10,000,000 deployable capital uses one slot;
    KRW 10,000,001 to KRW 20,000,000 uses two slots, subject to whole-share
    sizing and available candidates.
- Slot sizing is variable with account equity: trading PnL and weekly
  contributions both increase available equity, but deployed capital per slot
  remains bounded by cash, slot budget, whole-share sizing, and the KRW
  10,000,000 day-trade slot cap.
- Backtest reports must separate trading PnL from external capital
  contributions so returns, drawdown, and ending equity are not overstated.
- If account equity grows above the per-slot cap, excess cash remains idle or is
  allocated only through an owner-approved additional-slot policy.
- Slot expansion is automatic when deployable capital exceeds the per-slot cap,
  but the report must show the slot count used at each point in time.
- In A-DAY standalone validation, excess capital is idle/reserve. It must not be
  counted as swing performance until A-SWING, F, or another swing strategy has
  passed separate strategy-level validation and the portfolio-level integration
  stage is opened.

Risk contract:

- Global beta throttle can reduce deployable budget, but missing external
  futures data must be treated as a conservative approximation or disabled
  sensitivity case, not silently assumed.
- Daily loss fuse and daily stop-loss count must be represented when the engine
  supports them.
- Old-plan risk anchors are daily loss `-4.0%`, strategy MDD shutdown `-15.0%`,
  and per-slot same-day shutdown after two consecutive stop losses.
- Field-only safety controls such as disconnect handling, order rejection,
  timeout, and cancel/retry are not credited to historical PnL.

Continuity contract:

- Sparse Daishin stock runs use exact-bar trade continuity.
- Invalid-continuity trades cannot drive selection metrics.

## A-SWING Contract

Status: next swing comparison candidate.

A-SWING may be tested only after its carry contract is written. It should be
prepared after A-DAY as part of the required day-trade-versus-swing comparison,
regardless of whether A-DAY passes.

Required additional fields:

- overnight carry permission;
- max holding days;
- gap-down and gap-up treatment;
- forced exit rule;
- capital blocking while positions are held;
- interaction with same-day A-DAY entries.

The old plan contains swing concepts, including 15:15 swing targeting and
multi-day final exits. Those ideas may seed A-SWING, but they must not be mixed
into A-DAY results.

## Expected Case Count

Use strategy versions, not parameter combinations, as the case unit.

Expected practical upper bound:

- Candidate A: 2 primary versions, `A-DAY` and `A-SWING`; `A-REGIME` only after
  index-gate acceptance.
- Candidate B/C intraday variants: 2 to 3 versions total if execution gaps are
  reduced.
- Candidate D/E filters: 1 to 2 filter versions, usually attached to another
  base candidate rather than promoted alone.
- Candidate F swing variant: 1 to 2 versions.

Total expected strategy-version count: roughly 8 to 12 if all families remain
interesting. The first controlled tranche should stay at 2 to 4 versions:
`A-DAY`, possibly `A-SWING`, and only then one filter or swing alternative.

Do not expand into a grid of strategy versions. Parameter ranges belong to
coarse survival sweeps after a version passes the alignment gate.

## Current Decision

Proceed with A-DAY first, using the conservative profile and 15:15 forced
day-end exit. Then prepare A-SWING or F as a separate swing comparison candidate
under its own contract.

Before the first A-DAY performance run, write or confirm:

- exact prior-only universe fields;
- universe refresh command or data artifact;
- scouter eligibility fields;
- default `A-DAY-U1-S1` module parameters and, if needed, one predeclared
  comparison combination;
- whether old-plan filters are implemented exactly, approximated, or blocked:
  KRW 50B 5-day traded value, SMA20, ATR14/price, Tier 1 exclusions, blacklist
  freshness, same-symbol interlock, beta throttle, daily loss fuse, MDD fuse,
  and slot stop-loss fuse;
- entry window and 15:15 forced day-end exit;
- base cost, 2x cost, and stop-first stress settings;
- exact capital settings, including weekly KRW 100,000 contribution timing and
  the variable slot-count formula based on deployable capital;
- per-slot capital cap handling, with KRW 10,000,000 as the initial day-trade
  ceiling;
- continuity-valid-only report metric;
- source-gap register for Daishin historical data versus later field data.
