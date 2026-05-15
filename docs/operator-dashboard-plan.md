# Operator Dashboard Plan

This plan defines the first operator dashboard for no-order dry-run and later
field operation monitoring. The first dashboard may include manual recovery
controls for dry-run/runtime supervision. The only later broker-action control
currently planned is an operator-confirmed emergency hard-stop that liquidates
all positions and stops operation; it remains locked until a separate
owner-approved order-stage plan exists.

## Scope

- Audience: single operator supervising PROJECT_ZURINI dry-run and later field
  operation.
- Primary workflow: see current system health, market regime, watchlist,
  positions, returns, costs, required actions, and safe manual controls without
  reading raw logs.
- Safety boundary: no discretionary order buttons, no account actions, no broker
  balance reads, and no real-fill/slippage claims during no-order dry-run.
  Manual controls in this phase may affect only local dry-run runtime state,
  virtual/shadow lanes, reports, recovery steps, and operator annotations.
- Source of truth: persisted dry-run ledger, daily review reports, API smoke/KIS
  read-only reports, news/blacklist state, and checkpoint events.

## Visual Direction

- Base palette: black and white with restrained point colors.
- Background: white or near-white main canvas, black text, light gray dividers.
- Dark areas: allowed for top status strip or focused log console only.
- Point colors:
  - green: healthy/pass/positive return;
  - amber: attention/degraded/pending review;
  - red: blocked/breach/negative return;
  - blue: informational/current selection;
  - gray: inactive/no data.
- Shape: rounded corners are allowed, but keep cards compact and operational.
- Density: dashboard-first, not landing-page style. Prioritize scan speed.

## First Screen Layout

1. Top status strip
   - current mode: `no-order`, `read-only`, `order hard-blocked`;
   - KST clock and market phase: pre-open, open-burst, normal, close-burst,
     post-close;
   - post-close universe schedule: 15:35 close-state check, 16:10 next-session
     universe build, 16:20+ KIS read-only smoke, 16:30+ daily review;
   - API budget status and latest report timestamp;
   - news/blacklist heartbeat status;
   - storage guardrail status;
   - next required action.

2. Today's market judgment
   - traffic-light signal: green / amber / red;
   - market regime label: risk-on, neutral, risk-off, data-degraded;
   - reason chips: index trend, volatility, gap risk, liquidity, news risk,
     API health;
   - strategy permission summary: day allowed/blocked, swing allowed/blocked,
     shadow lanes active/inactive.

3. Watchlist status
   - universe size, scouted candidate count, excluded count;
   - table columns: symbol, name when available, strategy group, score,
     trigger reason, liquidity/volatility flags, blacklist state, last checked;
   - filters: all, day, swing, blocked, warning.

4. Position status
   - virtual positions during dry-run; real positions only after a later approved
     order-stage plan;
   - split by day and swing;
   - table columns: symbol, strategy, entry basis, current price, unrealized
     return, stop/take-profit state, max-hold/time-cut state, cooldown/interlock
     flags.

5. Return and cost summary
   - period tabs: cumulative, recent 7 days, recent 30 days;
   - values:
     - cumulative return based on order-decision price;
     - cumulative slippage based on order-fill price when real fills exist;
     - cumulative fee;
     - total cumulative return after slippage and fee;
   - during no-order dry-run, slippage and fee fields must be labelled modeled or
     unavailable, not realized.

6. Capital and return chart
   - tabs: day, week, month;
   - bar series: capital base split into deposited seed and profit-added seed;
   - line series: cumulative return;
   - horizontal line: peak cumulative return;
   - split view/toggle: day strategy, swing strategy, integrated portfolio;
   - annotations: 10-day review, 20-day stabilization, capital threshold,
     strategy revalidation due.

7. Logs and state events
   - event stream, not raw unlimited logs;
   - severity filter: info, review, warning, block;
   - categories: API, universe, scouter, order-hard-block, virtual order/fill,
     interlock/cooldown, blacklist/news, storage, checkpoint;
   - each event shows timestamp, trigger reason, required action, source artifact.

8. Manual operation controls
   - controls must be grouped separately from status panels and labelled by
     effect scope: local runtime, dry-run state, recovery step, report
     generation, or future locked hard-stop action;
   - each non-trivial action must write an operator action event with timestamp,
     actor label, reason, before/after state, and source panel;
   - destructive local actions require confirmation and must be disabled during
     critical market windows unless explicitly safe.

## Additional Required Panels

- Dry-run progress panel:
  - trading day count;
  - 10-day review due/complete;
  - 20-day stabilization due/complete;
  - current session completion state.

- API health panel:
  - read-call count;
  - peak calls per second by market phase;
  - latency buckets;
  - throttled/error count;
  - cooldown state for auth failures;
  - provider profile: paper/prod read-only.

- Data freshness panel:
  - latest KIS snapshot timestamp;
  - latest universe build timestamp;
  - latest news heartbeat timestamp;
  - daily bar source freshness;
  - stale data warnings.

- Capacity panel:
  - active seed plan;
  - weekly contribution tracking;
  - current validated ceiling;
  - surplus capital deployment block;
  - day slot count and swing slot count;
  - per-slot notional limit.

- Manual controls panel:
  - start no-order runner;
  - pause/resume polling;
  - stop runner after writing a checkpoint;
  - run a specific recovery step for mid-session start or abnormal-state
    recovery:
    - load latest session/checkpoint;
    - refresh read-only API smoke status;
    - load or rebuild today's universe;
    - run scouter once;
    - resume polling from current market phase;
    - regenerate daily review;
  - force daily review generation;
  - rebuild next-session universe after market close;
  - mark news heartbeat as operator-forced only with reason;
  - add or remove manual blacklist entries with expiry and reason;
  - mute/unmute a non-critical alert for a fixed duration;
  - trigger storage cleanup preview, then apply cleanup after confirmation;
  - export current dashboard/report bundle;
  - emergency hard-stop placeholder:
    - no-order mode: virtual all-close plus operation stop only;
    - future approved order-stage mode: liquidate all positions and stop
      operation, with multi-step confirmation and persistent incident record.

## Metric Definitions

- Order-decision return: return measured from the intended decision price used
  by the strategy.
- Slippage: realized fill price minus decision price after real order-stage fill
  data exists. Before that, show modeled slippage assumption only.
- Fee: realized fee after real fills exist; modeled fee during no-order dry-run.
- Total cumulative return: decision return minus realized or modeled slippage and
  fee, labelled by data class.
- Deposited seed: external cash contributions, including weekly planned
  deposits.
- Profit-added seed: capital growth from strategy returns, displayed separately
  in the capital bar but combined for total capital.

## States

- Healthy: all required feeds fresh, API within budget, order hard-block active,
  no deployment block.
- Attention: degraded reviewer state, stale non-critical feed, approaching API or
  storage threshold, review due.
- Blocked: order hard-block missing, account/order endpoint detected, API limit
  breach, stale required news feed when required, storage hard limit, data
  quality failure, strategy revalidation overdue.
- No data: panel has no source artifact yet; do not infer pass.

## Manual Control Rules

- All controls default to disabled until the dashboard confirms mode, source
  artifact freshness, and permission state.
- No-order controls must never call broker order, account, balance, or
  real-position endpoints.
- There are no discretionary buy/sell buttons. The only planned future
  broker-action button is emergency hard-stop: all-position liquidation plus
  operation stop.
- In no-order mode, emergency hard-stop performs virtual all-close and stops the
  local runner only.
- In a future approved order-stage mode, emergency hard-stop must require a
  confirmation flow, reason entry, current position preview, and incident event
  persistence before it can send any liquidation orders.
- Start/pause/resume/stop controls affect only the local no-order runner.
- Recovery-step buttons must be idempotent where possible and must show the
  required prerequisite artifact before execution.
- Manual blacklist changes require symbol, reason, expiry, and source note.
- Operator-forced news heartbeat must be visually distinct from adapter-provided
  heartbeat and must not be counted as real news collection evidence.
- This week's dry-run baseline keeps automatic news collection OFF. The UI may
  show that state, but it must not treat the missing feed as abnormal unless the
  run is explicitly configured to require news. After weekend modularization, the
  dashboard should compare news OFF, news ON healthy heartbeat, and news ON
  stale/fail-close dry-run windows.
- Storage cleanup must offer preview first and must not delete accepted evidence
  or latest daily review artifacts.
- Every manual action must be replayable from persisted events so later review can
  distinguish strategy behavior from operator intervention.

## Implementation Notes

- Build the dashboard after this week's dry test produces enough ledger/report
  artifacts to validate the data contract.
- Weekend execution order: first split the CLI into command-group modules, then
  start the operator dashboard MVP against the stabilized CLI/report contracts.
- Keep the first implementation read-only and local.
- Prefer backend-prepared summaries over complex client-side reconstruction.
- The UI must consume checkpoint events instead of inventing separate alert
  logic.
- Do not add enabled discretionary order buttons or account actions in the first
  UI.
- Before implementation, split the UI data contract by domain: status, market
  judgment, watchlist, positions, returns, chart series, and events.
