# Plan A Next Actions

Date: 2026-05-18

This is the single tracking index for Plan A after the current no-order dry-run
alignment check. It links to the detailed contract documents instead of
duplicating their full content.

## Current Status

Current no-order dry-run package:

- package: `plan-a-idmom-d3-fsup-u1s1`
- day leg: `C-IDMOM-D3-U1-S1`
- swing leg: `F-SUP-U1-S1`
- order boundary: no-order only, `order_hard_block=true`

Current decision:

- The 2026-05-18 main `field-run` produced useful intermediate no-order
  evidence, including accepted universe reuse, but it is not the final accepted
  operating state for the day. Later 15:10-15:20 KST budget evidence superseded
  the earlier clean cycle and the run ended fail-closed as `api_degraded`.
- Correction from the 2026-05-18 live check: 장중 main `field-run` must execute
  only the primary operating scenario (`primary-current-seed-1m`). Shadow,
  future-capital, and slippage-stress scenarios are post-close validation over
  that day's acquired data, not intraday monitor work. The prior implementation
  reused the full monitor fan-out in `field-run`, which made cycle output slow
  and violated the intended operating sequence; this is now guarded by tests.
- Correction from the 2026-05-18 15:10-15:20 KST budget check: swing focus may
  reduce the symbol set, but it does not relax per-second API request rules.
  The failed cycle narrowed to 30 focused symbols, yet price/depth reads were
  throttled only between symbols and therefore emitted back-to-back KIS read
  calls inside the lock-step critical window. The observed peak was 8/sec
  against the critical scouter budget of 5/sec and operating budget of 7/sec,
  so the run correctly failed closed as `api_degraded`. The fix enforces quote
  pacing per KIS read call, including between price and order-book requests,
  and forbids converting any `api_rate_limit_risk` quote cycle into operating
  `passed` status through placeholder exclusion.
- The 2026-05-15 field run is not valid strategy-frequency evidence because
  the reused universe path did not preserve warm-up source evidence into the
  monitor pass. Treat the zero-entry result as an operating-input defect until
  fixed and rerun.
- Backtest fallback is not required for simply explaining the defective run, but
  a targeted backtest/regression pass is required before changing strategy
  parameters or accepting a new 15:10 focus rule.
- Code-level fail-closed and ledger guards are verified, but operational
  no-order dry-run continuation is blocked until the latest daily-bar source is
  collected and an accepted next-session universe plus KIS symbol list exists.
- It is not sufficient for operating promotion until the final-applied
  parameter ledger is evidenced from a fresh operating dry-run.
- Index trend filtering is now an optional no-order risk gate. It is off by
  default; when enabled, missing/stale/warming-up/bearish KOSPI/KOSDAQ evidence
  blocks day entries only and preserves post-close simulation through index
  trend report artifacts.
- Backtest research-data DB migration is deferred. The local DB is currently
  clean after removing interrupted historical-import residue, and DB hygiene is
  now a field-start preflight item rather than an immediate work item.

Primary references:

- Parameter contract and fallback matrix:
  [`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md)
- Field dry-run readiness and follow-up work:
  [`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md)
- Strategy validation parent plan:
  [`strategy-validation-plan.md`](strategy-validation-plan.md)
- Post-close simulation candidates:
  [`post-close-simulation-candidates.md`](post-close-simulation-candidates.md)
- Operator dashboard proposal:
  [`operator-dashboard-plan.md`](operator-dashboard-plan.md)
- TODO 3-7 post-market review:
  [`plan-a-todo-3-7-review.md`](plan-a-todo-3-7-review.md)

## Immediate Next Actions

| Priority | Work item | Status | Source of truth | Stop condition |
| --- | --- | --- | --- | --- |
| 0A | Fix main `field-run` universe-reuse warm-up propagation before the next field session. | implemented-targeted-tests-2026-05-15 | `reports/dry-run/analysis/2026-05-15-dryrun-strategy-analysis.md`, `reports/dry-run/field-run-control.json`, `src/zurini/cli.py` | When `field-run` reuses an accepted universe artifact, it now attaches the accepted prior warm-up path-list to the monitor pass and records `source_path_list` in universe evidence. If the source cannot be resolved, it fails closed before 장중감시 starts. Targeted regressions passed for reused-universe warm-up propagation, missing warm-up fail-closed behavior, stop-guard reuse, and auto source build. Full verify/review-gate remains required before promotion. |
| 0 | Replace today's manual dry-run startup sequence with one main module entrypoint before the next field session. | implemented-pending-review-gate | `zurini.cli field-run`, `plan-a-field-dry-run-readiness.md`, today's field-runner logs | `field-run` owns the normal no-order sequence: KIS auth/token preflight first when network mode is enabled, then automatic prior-only universe preparation when no manual symbols/report/build option is supplied. Automatic universe mode first validates the date-matched stored universe artifact without making source-collection calls. If no valid artifact exists, it builds from stored warm-up CSV sources; if stored source is missing or contract-invalid and `--run-network` is enabled, it refreshes KIS stock-master symbols, collects KIS daily bars, writes the default warm-up path-list, and rebuilds the universe. If no valid artifact/source can be prepared, it fails closed with a control report. Manual `--build-universe` / `--universe-report` remain diagnostic override paths, not the normal operating startup. KIS symbols are derived from the accepted universe; market-session quote-depth collection uses the prewarmed token cache; monitor pass, fail-closed status/control artifacts, and stop guards are owned by the same main entrypoint. The normal operating routine must refresh/prewarm the KIS token at 08:30 KST before the field session. Do not require separate manual KIS quote or monitor commands during normal startup. 장중감시모듈 수집/판단 루프는 AI감시모드 보고 주기와 분리한다. 장중감시모듈은 post-cycle sleep 금지; API throttle and collection duration only. 5분은 사람에게 보고하는 AI감시모드 주기에만 허용한다. 15:10 이후에는 watchlist 기반 swing focus 후보가 있으면 해당 후보만 다음 quote/depth 사이클에 넣고, 15:15 이후 최초 취득 snapshot으로 판단한다. Day leg entry window is exactly `10:00`-`13:30`; `13:30` is included and `13:31` is blocked as `entry-window`. |
| 1 | Collect KIS stock master files and update the local DB / market-wide symbol source. | done-2026-05-14 | `reports/dry-run/kis-stock-master.json`, `reports/dry-run/kis-source-symbols.txt` | Latest run passed: KIS stock master `symbol_count=4349`, candidate list `included_symbols=2301`, duplicate candidates excluded with `duplicate_symbol_count=43`, local DB `symbol_metadata` updated with `source=kis-stock-master` and `row_count=2301`. |
| 2 | Collect or refresh 60 trading days of KIS daily-bar source data for the refreshed local DB / market-wide symbol source. | done-2026-05-14 | `reports/dry-run/kis-daily-bars.json`, `reports/dry-run/kis-dailybar-eligibility-2026-05-14.json`, `plan-a-field-dry-run-readiness.md` | KIS daily-bar eligibility excluded `18` symbols with explicit reasons (`12` repeated missing `output2`, `6` fewer than 60 rows). The accepted eligible list then passed: `2283/2283` included, `api_flags=none`, `source_fresh=true`, `latest_prior_date=2026-05-13`, `csv_file_count=9132`, and no partial operating CSVs were accepted from degraded attempts. |
| 3 | Rebuild the next-session field universe from accepted KIS daily bars. | done-2026-05-14 | `reports/dry-run/field-universe-2026-05-14.json`, `reports/dry-run/field-universe-kis-symbols.txt` | Universe build passed in `prior-only-read-only` mode for target `2026-05-14`: `included_count=80`, `excluded_count=2203`, `loaded_bar_count=152961`, `latest_prior_date=2026-05-13`, `source_fresh=true`, and KIS symbol list has 80 symbols. |
| 4 | Run read-only KIS quote smoke for the accepted KIS symbol list. | scheduled-2026-05-18-market-session | `reports/dry-run/kis-readonly-universe.json`, `plan-a-field-dry-run-readiness.md` | Price quote smoke included `80/80` and stayed within API budget, but both normal and `--include-quote-depth` runs remain `degraded` with `api_flags=["bid_ask_placeholder"]` and `bid_ask_ratio` missing for all members. A raw pre-open depth check showed the expected bid/ask fields exist but all bid/ask quantities are `0`. User direction on 2026-05-15: handle this operating validation on next Monday, 2026-05-18. Rerun `kis-readonly-universe --include-quote-depth` after market data is live before treating it as contract-clean strategy evidence. |
| 5 | Continue no-order dry-run observation. | blocked-until-next-field-session-after-2026-05-18-api-budget-fix | `reports/dry-run/current-status-2026-05-18.json`, `reports/dry-run/field-run-control-2026-05-18.json`, `plan-a-field-dry-run-readiness.md` | Main `field-run` is the operating path. The last 2026-05-18 run stopped fail-closed after three consecutive degraded quote cycles with `rate_limit_risk`: focused symbols were 30, `read_call_count=61`, and observed peak was 8/sec during the 15:10-15:20 KST lock-step budget window. The code now throttles every KIS read call rather than every symbol, and 장중 monitor execution is primary-only. Because the fix landed after the 15:35 KST stop guard, the next operating proof must come from the next field session without overriding time or hand-editing artifacts. |
| 6 | Preserve fail-closed input gates. | active-code-guarded | `docs/AUTOMATION_OPERATING_POLICY.md`, `docs/WORKFLOW.md`, `plan-a-field-dry-run-readiness.md` | Missing/stale/contract-invalid input blocks downstream execution. |
| 7 | Add or verify final-applied parameter ledger evidence before promotion. | active-code-guarded | `plan-a-parameter-contract-matrix.md` | Accepted signals record strategy ID, group, entry/exit rule, final exits, holding, slot, and cost model in fresh dry-run evidence. |
| 8 | Keep backtest fallback matrix ready but do not rerun unless a trigger fires. | standby | `plan-a-parameter-contract-matrix.md` | Rerun only on ambiguity, stale/failed evidence, or missing final-applied manifest. |
| 9 | Keep post-close universe production routine. | recurring | `plan-a-field-dry-run-readiness.md` | After each close, refresh KIS stock master files, update the local DB / market-wide symbol source, then remove the oldest retained prior date only after the new expected prior trading day has been collected from KIS. Rebuild the next-session universe from the rolling 60-trading-day window. |
| 10 | Simulate optional KOSPI/KOSDAQ trend filter after close. | implemented-verified-2026-05-16 | `src/zurini/index_trend.py`, `src/zurini/kis_index_feed.py`, `src/zurini/cli.py` | User-approved freeze exception for a verified dry-run blocker: the 2026-05-15 dry-run analysis showed day-entry signal interpretation could miss market-wide downside pressure, so `field-run --enable-index-trend-filter` is opt-in, default-off, read-only, and day-entry-only. It writes a KIS index report and passes it into monitor; `plan-a-dry-run`, `plan-a-dry-run-multi`, and `field-dry-run-monitor` can replay `--index-trend-report`. Filter-off leaves day entries unaffected, filter-on blocks only day entries on missing/stale/warming-up/bearish index evidence, and swing entries remain unaffected. |
| 11 | Keep 급락 후 종가 반등 swing 조건식 as post-close simulation only. | implemented-pending-full-verify | `src/zurini/post_close_swing_rebound.py`, `tests/test_post_close_swing_rebound.py` | The condition is stored separately from live `SwingSupportStrategy` entry flow. It can score late-day rebound candidates after close using prior closes/volumes and the 15:10-15:35 bar shape, but it is not wired into `field-run`, monitor entry triggers, orders, or promotion evidence until a later reviewed strategy decision. |
| 12 | Keep relative-strength survivor swing condition as post-close simulation only. | implemented-pending-full-verify | `src/zurini/post_close_swing_relative_strength.py`, `tests/test_post_close_swing_relative_strength.py` | The condition scores resilient names only when the broader market/watch universe is weak. It requires positive relative-return edge, bounded adverse movement, recovery from low, sufficient traded value, and non-overheated RSI. It is not wired into live `field-run`, monitor entry triggers, orders, or promotion evidence. |
| 13 | Keep day-trade simulation candidates separate from live entry. | implemented-pending-full-verify | `src/zurini/post_close_day_simulation.py`, `tests/test_post_close_day_simulation.py` | The candidate recipes cover current immediate replay, pullback-reentry variants, market-defense replay, spike/fade guard, and entry-window comparison. The pullback-reentry evaluator can replay trigger-following bars after close, but none of these candidates are wired into live `field-run`, monitor entry triggers, orders, or promotion evidence. |
| 14 | Track post-close simulation candidate matrix and runner foundation. | implemented-verified-2026-05-16 | `docs/post-close-simulation-candidates.md`, `src/zurini/post_close_simulation_runner.py`, `src/zurini/simulation_analysis_cli.py`, `tests/test_post_close_simulation_runner.py`, `tests/test_simulation_infra_cli.py`, `reports/phase2/post-close-simulation-report-2026-05-15-replay.json` | The current analysis-only matrix is documented as 8 day-trade candidates, 2 swing candidates, 1 filter candidate, plus universe recall audit and rolling two-year minute dataset foundations. The runner foundation now includes an analysis-only report format, separate `post-close-simulation-report` JSON scaffold, optional filter OFF/ON symbol-gap comparison, and `--replay-watchlist` model-level summaries for the 8 day, 2 swing, and 1 filter candidates. The 2026-05-15 replay report is explicitly `analysis-only-replay`, not KIS rolling DB evidence. It stays outside the main dry-run CLI during the pre-dry-run module freeze. Promotion still requires source-valid rolling minute evidence and review. |
| 15 | Split dry-run index-filter connection tests into a dedicated test file. | implemented-verified-2026-05-16 | `tests/test_dry_run_index_filter.py` | Dry-run wiring assertions for `--enable-index-trend-filter`, missing index trend reports, day-only blocking, swing preservation, and index report accumulation now live outside the broad dry-run test module. Runtime behavior is unchanged. Targeted test and full `./scripts/verify.sh` passed. |
| 16 | Keep rolling two-year minute research dataset foundation separate from live dry-run. | deferred-until-field-preflight | `src/zurini/research_minute_dataset.py`, `src/zurini/data/schema.sql`, `src/zurini/data/db.py`, `src/zurini/simulation_analysis_cli.py`, `tests/test_research_minute_dataset.py`, `tests/test_research_minute_db_integration.py`, `tests/test_simulation_infra_cli.py`, `docs/phase-2-real-data-runbook.md`, `reports/phase2/kis-rolling-integrity-2026-05-16.json` | Foundation now separates DB contracts by evidence type. `research_minute_raw` / `research_minute_canonical` are minute-only tables shaped around current field-monitor row fields and constrained to `data_origin` values `legacy-minute-backfill` or `field-observation`, both with `interval='1m'`. Universe-selection prior-close/daily rows live in `universe_daily_raw` / `universe_daily_canonical` with `data_origin='universe-selection-source'` and `trading_date`. Trade evidence lives in `trade_runs`, `trade_signals`, `trade_orders`, and `trade_positions`, with `trade_mode` separating dry-run/field/paper/live history and `strategy_group` separating day/swing history. Source-tagged import, canonical refresh, rolling retention report/apply commands, and fail-closed `kis-rolling-integrity` remain separate analysis CLI paths. Full legacy minute DB migration is deferred because the CSV-to-Postgres footprint can exceed current local disk headroom. Do not run historical bulk import or source-file deletion during field operation. At field-start/preflight, verify DB responsiveness, no long-running historical-import queries, no partial `historical-db-*` residue, and sufficient disk space. |
| 17 | Keep universe recall audit foundation separate from live market scanning. | implemented-targeted-tests-2026-05-16 | `src/zurini/universe_recall_audit.py`, `src/zurini/simulation_analysis_cli.py`, `tests/test_universe_recall_audit.py`, `tests/test_simulation_infra_cli.py` | Foundation now includes the separate `universe-recall-audit` report skeleton that reads universe symbol lists and signal-observation CSV/JSON files, then reports captured/missed recall metrics. This remains a post-close/weekend audit only, not a live market-wide scanner or main dry-run CLI command. |

## Data Timepoint Contract

All operating inputs must distinguish two clocks.

| Input | Availability-check timepoint | Acquisition/execution timepoint | Fail-closed rule |
| --- | --- | --- | --- |
| KIS auth/token | 08:30 KST operating prewarm, plus main `field-run` network-mode startup before any universe or monitor step. | Token issue/reuse stays in process memory; no token value is persisted. | Missing credentials, auth cooldown, timeout, missing token, or immediately expired token blocks downstream universe, quote/depth, and monitor execution. |
| Daily field universe | `target_date` plus expected prior trading date. | Universe build time after source daily bars are produced. | Latest prior date must match the expected completed prior trading session; stale, missing, or self-declared-only artifact freshness blocks reuse. |
| KIS stock master / local DB / market-wide candidate symbols | Master-file collection timestamp and source market (`KOSPI`, `KOSDAQ`). | Before KIS daily-bar collection and before post-close universe rebuild. | Missing, stale, malformed, or unrefreshed stock-master input blocks market-wide daily-bar collection and universe selection. |
| KIS market-data report | Included member `observed_at` per symbol. | KIS read-only quote call/report generation time. | Each included member must be within `market-data-max-age-seconds`; one fresh member cannot mask stale members. |
| KIS index trend report | KOSPI/KOSDAQ raw `index_ticks` timestamps plus aggregated `index_bars` trend evidence. | 10-second read-only KIS index polling during `field-run`, or post-close replay from `--index-trend-report`. | Only enforced when `--enable-index-trend-filter` is set. Raw 10-second KIS snapshots are persisted to `index_ticks`; 1-minute price-derived bars are persisted to `index_bars`. Missing, failed, stale, future, or warming-up evidence blocks day entries and monitor scenario execution; swing entries are not filtered by this gate. |
| News/DART/RSS risk events | Source item timestamp (`observed_at`, `published_at`, `rcept_dt`, `pubDate`). | News adapter collection time. | Missing, future, or stale source item timestamps are rejected; heartbeat alone is not source-content freshness. |
| Async blacklist | Snapshot `heartbeat_at` and entry `observed_at/expires_at`. | Blacklist update time from accepted news events. | Stale heartbeat blocks all symbols; events without `observed_at` are rejected. |
| DB dry-run resume | Requested trading date and `as_of` cutoff. | Latest ledger event evidence time. | Resume state rejects stale, future, missing, or wrong-date evidence. |
| Backtest/ledger parameters | Signal creation and position close. | Backtest/dry-run event persistence. | Strategy ID, group, entry/exit rule, final exits, holding, day-end behavior, slot, and cost model must round-trip in the ledger for promotion evidence. |

## Weekend Work Queue

These are the planned weekend items. They should be handled after the current
no-order dry-run gate and without expanding the frozen monolithic surfaces
first.

| Priority | Work item | Required constraints | Source of truth |
| --- | --- | --- | --- |
| W0 | Build one main no-order field-run entrypoint for tomorrow's session. | Implemented in `zurini.cli field-run`; final completion still requires full verify plus AI reviewer/review-gate ALL PASS. The command owns KIS auth/token preflight first, automatic universe reuse/build/fail-closed selection from time plus stored data, KIS daily-bar collection when source data is missing and network mode is explicitly enabled, KIS symbol derivation, read-only KIS quote-depth collection using the prewarmed token cache, field monitor pass, fail-closed status/control artifacts, stop guards, no-order boundary, no post-cycle sleep, AI reporting cadence separation, and 15:10 swing focus from watchlist candidates. Normal operation must prewarm/reissue the KIS token at 08:30 KST. Keep order/account/balance calls blocked. | `plan-a-field-dry-run-readiness.md`, `src/zurini/cli.py`, `tests/test_dry_run.py` |
| W1 | Split the growing CLI and dry-run surfaces into command-group/domain modules. | Keep current commands backward compatible. Do not add new command groups or broaden `src/zurini/cli.py` / `src/zurini/dry_run.py` before the split unless fixing a verified dry-run blocker. While rebuilding the field-universe source module, replace the current mtime-based "daily source newer than universe" reuse guard with explicit source artifact IDs or generated timestamps so copied/restored artifacts cannot silently bypass regeneration. Run full verify and review gate after the refactor. | `plan-a-field-dry-run-readiness.md`, `src/zurini/cli.py` |
| W2 | Implement KIS news/disclosure subscription collector after modularization. | Confirm KIS-provided source path. Keep heartbeat, event normalization, blacklist update, stale/fail-close behavior, and no-order monitor integration separate from quote polling. | `plan-a-field-dry-run-readiness.md` |
| W3 | Add operator hard-stop and heartbeat alerts. | Dashboard/control work must include no-order hard stop, run-state freeze, alert visibility, and periodic heartbeat/status checks. No discretionary order buttons. | `plan-a-field-dry-run-readiness.md`, `operator-dashboard-plan.md` |
| W4 | Start operator UI alert/dashboard MVP after CLI modularization. | UI consumes persisted checkpoint events and dry-run reports; it does not create a separate source of truth. First UI has no discretionary order buttons or account actions. | `operator-dashboard-plan.md` |
| W5 | Review selected chaos tests after module split and verification. | Do this only after the module-splitting work is verified. Start from the failure-mode inventory, choose a small high-value subset, and keep live/read-only API chaos scoped and explicitly approved. | `plan-a-field-dry-run-readiness.md` |
| W6 | Trim and split oversized agent instructions. | Upstream queue only per user direction on 2026-05-15. Do not directly edit PROJECT_ZURINI `AGENTS.md` or local instruction files for this item during the current Ralph task. AI_AUTO should keep only durable safety, verification, routing, and ownership rules in always-loaded guidance, then move long procedures/examples into linked docs loaded on demand. | `docs/PATCH_NOTES.md`, AI_AUTO template guidance |
| W7 | Add visible main-sequence stage/progress logging. | Pre-split logging implemented for `field-run`: observable, non-secret `field_run_stage` lines now cover auth preflight, universe preparation, cycle start, quote/depth start and completion, degraded quote monitor skip, monitor start and completion, stop/wait state, fail-closed reason, and cycle-limit stop. Logs must not print credentials, tokens, account data, or order-capable payloads. | `src/zurini/cli.py`, `tests/test_dry_run.py`, `docs/plan-a-field-dry-run-readiness.md` |
| W8 | Add reusable AI_AUTO domain pack for domestic-stock KIS automated-trading projects. | Completed as `templates/domain-packs/kis-domestic-stock/`; the exact user request is preserved below. Keep this as reusable AI_AUTO guidance only; it must not overwrite PROJECT_ZURINI local rules. | `docs/DOMAIN_PACKS.md`, `templates/domain-packs/kis-domestic-stock/` |
| W9 | Review API reserved-capacity policy before order-capable rehearsal. | Implemented as a narrow policy change: normal total operating API budget is 15/sec, scouter/장중감시 read speed remains 10/sec, reserve increases to 5/sec, and critical windows remain 7/sec total with 5/sec scouter. This does not permit faster no-order polling. | `src/zurini/api_budget.py`, `tests/test_api_budget.py`, `plan-a-todo-3-7-review.md` |
| W10 | Evaluate bounded parallel quote/depth collection for 장중감시모듈. | Design captured in the 2026-05-15 improvement plan. Full bounded-worker implementation remains blocked until the module split/rebuild instruction because it changes collection architecture. Pre-split guards applied: the default quote/depth pacing now accounts for each KIS read call, including the price/depth pair boundary, so critical-window defaults do not create self-inflicted `api_rate_limit_risk`; persistent degraded quote/depth cycles now fail closed after a bounded retry limit instead of looping for the whole market window. Required final shape: bounded worker pool, strict rate-limit budget, per-symbol timeout, per-symbol timestamp, paired price/depth freshness checks, deterministic failure classification, and no order/account/balance calls. Do not use unlimited parallel requests. | `reports/dry-run/analysis/2026-05-15-field-ops-strategy-improvement-plan.md`, `src/zurini/api_smoke.py`, `src/zurini/cli.py`, `tests/test_api_smoke.py`, `tests/test_dry_run.py` |
| W10A | Keep current-cycle quote/depth placeholder exclusion explicit and narrow. | implemented-targeted-tests-2026-05-18 | `src/zurini/cli.py`, `tests/test_dry_run.py`, `plan-a-field-dry-run-readiness.md` | `field-run` may pass a quote/depth cycle after excluding only symbols whose sole degradation is `bid_ask_placeholder`, only when at least one clean member remains. The report must record `quote_depth_excluded_symbols` and `input_contract_action`. Any top-level `api_rate_limit_risk` or over-budget evidence keeps the quote cycle degraded and blocks monitor execution. Auth, member-level rate-limit, stale timestamp, paired price/depth gap, schema, timeout, or mixed degradation still fail closed or skip according to the existing degraded-cycle limit. |
| W10B | Reduce pre-split main-run I/O and source-scan latency. | implemented-targeted-tests-2026-05-18 | `src/zurini/cli.py`, `tests/test_dry_run.py` | Daily-bar scope classification now scans existing KIS daily CSV files once instead of per symbol, reused-universe warm-up validation loads only universe-required symbols, and field monitor warm-up loading is filtered to the symbols present in the accepted live KIS snapshot. Remaining latency risk is large per-scenario JSON output on `/mnt/c`; defer report compaction or async writer split to W14/module split unless it blocks the current field session. |
| W10C | Keep intraday and post-close scenario lanes separate. | implemented-targeted-tests-2026-05-18 | `src/zurini/cli.py`, `src/zurini/field_monitor.py`, `tests/test_dry_run.py` | Main `field-run` now runs only `primary-current-seed-1m` during the market session. The five-scenario fan-out remains available through the monitor/post-close analysis path for validating the day with acquired data after the close. Treat any intraday `field-run` status containing shadow scenario results as an operating-sequence defect. |
| W11 | Verify KIS WebSocket payload coverage before considering subscription-based 장중감시. | Reviewed against official KIS sample surface and kept as a candidate only. WebSocket cannot replace REST polling until payload parity is proven for all current monitor inputs, receive timestamps, price-depth freshness pairing, reconnect/stale-heartbeat behavior, and deterministic degraded-symbol reporting. If any field must be filled by separate REST polling, reject it as the main monitor path because timestamp mismatch can change strategy meaning. | KIS official WebSocket docs/samples, `src/zurini/api_smoke.py`, `src/zurini/field_monitor.py`, `plan-a-todo-3-7-review.md` |
| W12 | Replace coarse pre-open polling wait with local-time alarm scheduling. | Implemented for the main `field-run` wait path. Token prewarm now sleeps to the exact local KST `08:30` target. Market-open waiting now targets `08:59:30` first, then the local market-open boundary. Local time remains only the wake trigger; accepted operating evidence still depends on KIS quote/depth freshness and non-placeholder payloads. | `src/zurini/cli.py`, `tests/test_dry_run.py`, `plan-a-todo-3-7-review.md` |
| W13 | Review intraday monitor target-reduction logic. | Design captured in the 2026-05-15 improvement plan. Implementation remains blocked until the module split/rebuild instruction. The 15:10 compression must select an actionable swing subset from audit-visible watchlist fields while preserving data-integrity gates and without changing strategy meaning. | `reports/dry-run/analysis/2026-05-15-field-ops-strategy-improvement-plan.md`, `src/zurini/field_monitor.py`, `src/zurini/field_universe.py`, `src/zurini/strategies/baseline.py`, `tests/test_field_monitor.py`, `tests/test_field_universe.py` |
| W14 | Split intraday collection from monitor/report writing. | Design captured in the 2026-05-15 improvement plan. Implementation remains blocked until the module split/rebuild instruction. Pre-split observability is now improved through explicit `field_run_stage` logs for cycle start, quote/depth start and completion, degraded quote skip, monitor start and completion, and cycle-limit stop. Target architecture is a bounded producer/consumer pipeline: the collector immediately starts the next KIS quote/depth cycle after persisting the raw snapshot, while judgment/report writing consumes the prior accepted snapshot asynchronously. Preserve per-snapshot timestamps, API budget throttling, no-order boundary, deterministic degraded-symbol classification, and crash-safe artifact handoff. | `reports/dry-run/analysis/2026-05-15-field-ops-strategy-improvement-plan.md`, `src/zurini/cli.py`, `src/zurini/api_smoke.py`, `src/zurini/field_monitor.py`, `tests/test_dry_run.py`, `tests/test_field_monitor.py` |

### W8 Exact User Request

```text
국내주식 KIS 기반 자동매매 프로젝트용 AI_AUTO 도메인팩을 만들어줘.
  목표는 모듈 분리 리팩터링이고, 실거래 API 호출/credential 유출/전략 의미 변경은 금지.
  Repomix는 읽기 전용 context pack, Aider는 제한된 파일 수정 보조로만 허용.
  paper/live 분리, 중복 주문 방지, kill switch, 최대 손실 제한 검증 체크리스트를 포함해줘.
  AI_AUTO 템플릿에 재사용 가능한 domain pack 형태로 추가해줘.
```

## Next-Week Comparison

| Work item | Required constraints | Promotion rule |
| --- | --- | --- |
| Universe/scout data-completion exception rules for new listings and trading halts | Review after market close how to handle symbols that cannot meet uniform business-day coverage because of IPO/new listing timing, suspensions, or indicator-specific lookback needs such as moving averages. Separate universe 60-trading-day requirements from scout indicator-specific data windows, define explicit ineligible/degraded/fail-closed states, and forbid silent fallback to shorter histories. | Promote only after the rule is documented, tests cover insufficient-history and suspension-shaped gaps, and operating artifacts report the exact exclusion/degradation reason per symbol. |
| Rolling two-year minute research dataset | Maintain one continuous research/backtest minute-bar timeline from existing legacy history plus newly collected KIS data. KIS rows must carry source identifiers, legacy gaps must remain null/flagged instead of defaulted, raw/source rows should be distinguishable from canonical backtest rows, and retention keeps only the latest two-year research window unless archive is explicitly approved. | Promote only after import, raw/canonical selection, quality flags, source-overlap handling, and cutoff discipline are implemented and verified. See `phase-2-real-data-runbook.md` and `post-close-simulation-candidates.md`. |
| Field-start DB hygiene preflight | Before field operation, verify Postgres is responsive, no historical bulk import/cleanup is running, `research_minute_*`, `universe_daily_*`, and `index_bars` contain no unintended partial backfill residue, and local disk headroom is sufficient. This replaces immediate DB cleanup work; historical research-data migration remains deferred. | Promote only after the preflight records clean DB state or an explicit blocker. Do not delete source CSVs or run bulk historical import as part of market-session startup. |
| Rolling daily-bar backfill after user stop or PC downtime | Review after market close how the rolling 60-trading-day source recovers when the system is intentionally stopped or the PC is offline for one or more business days. The collector must detect all missing completed prior sessions since the last accepted source date, fetch the full gap, and only then remove old dates; a one-day-only refresh is not enough after downtime. | Promote only after gap detection, multi-day backfill, stale-window rejection, and recovery reporting are documented and covered by tests. |
| Chaos/failure-mode inventory before targeted hardening | Build a broad list of likely abnormal conditions before adding more runtime behavior: network outage, KIS timeout/rate-limit/auth cooldown, user stop/restart, PC/WSL/Docker failure, partial file writes, stale cache reuse, clock/date mismatch, missing business days, malformed reports, manual artifact edits, disk pressure, and interrupted review/automation state. Map each case to existing defense, missing defense, required artifact flag, and whether it deserves a targeted test or only an operational runbook check. | Promote only after the inventory identifies critical unguarded paths and prioritizes a small test plan; do not attempt broad chaos execution against live/read-only APIs without explicit scope. |
| News defense ON/OFF dry-run comparison | Compare OFF baseline, ON with healthy heartbeat, and ON with stale/fail-close simulation. | Promote the news path only if it improves risk filtering without API, heartbeat, or false-positive instability. |
| Session traceability during module split | Add module-level run IDs, linked stage logs, and one recovery trace per main-entry execution. This is queued for the module separation rebuild, not for the current frozen monolith. | Promote only after a failed or interrupted run can be traced from main entry to token, universe, quote/depth, monitor, and control artifact without manual log guessing. |

## Future Work

| Work item | Required constraints | Promotion rule |
| --- | --- | --- |
| Market-risk feed: Nasdaq futures, beta throttle, index/regime state | Define explicit read-only sources, heartbeat/freshness rules, fail-closed or degrade behavior, and report fields. | Do not credit live risk-throttle parity before source and heartbeat evidence exist. |
| Correlation and theme concentration risk | Define source, lookback, grouping/proxy method, and report fields. | Cannot affect field-start sizing before the data contract exists. |
| KIS condition-search or push candidate feed | Evaluate after baseline polling week. Keep read-only, source-labeled, rate-budgeted, and comparable against polling-only baseline. | Adopt only if it improves field observation without destabilizing the polling baseline. |
| Later order-stage plan | Separate owner-approved plan only. | Must cover broker connection, account reads, paper/live order controls, IOC/backoff, emergency liquidation, partial fills, and real fill/slippage measurement. |

## Backtest Fallback Rule

Do not return to backtesting now.

Return to the strict backtest matrix only if a trigger in
[`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md)
fires, including:

- active package, day leg, or swing leg mismatch;
- slot/capital/cost model mismatch;
- continuity failure or missing exact-bar evidence;
- final-applied parameter evidence required for promotion but no ledger or
  manifest exists;
- `A-DAY-v2` reappears in active Plan A evidence.

When fallback triggers, old report values must not be edited manually. Rebuild
the matrix and record commands, datasets, config overrides, report paths, and
parameter manifests.

## Verification Status

Latest completed verification before this index:

- targeted KIS stock master / DB integration tests: passed
- targeted `field-run` tests: `20 passed`
- main-entry auto-universe smoke: passed with no universe/symbol/build option;
  `field-run` reused `reports/dry-run/field-universe-2026-05-14.json`,
  preserved `included_count=80`, `latest_prior_date=2026-05-13`, and stopped at
  the inferred market-session guard with `quote_status=skipped`
- main-entry missing-source network path: passed in mocked read-only network
  mode; after auth preflight, `field-run` collected stock-master symbols,
  collected KIS daily bars through the expected prior date, wrote the default
  warm-up path-list, built the date-matched universe, then stopped at the market
  session guard without quote/order activity
- main-entry invalid stored-source recovery: passed in mocked read-only network
  mode; valid stored universe is checked before network source collection, and
  invalid stored warm-up sources force stock-master refresh before daily-bar
  collection even when a stale `kis-source-symbols.txt` already exists
- closed-market `field-run --build-universe --enforce-market-session-stop`
  smoke: passed; universe built first, control report stopped at the market
  session guard with `quote_status=skipped`, `cycle_count=0`, and universe
  evidence preserved
- full `./scripts/verify.sh`: `483 passed` on 2026-05-16 after post-close
  simulation runner, research-minute dataset, universe recall audit,
  index-filter test split, optional research CSV field, and index poll budget
  rounding/current-session freshness updates
- full `./scripts/verify.sh`: `492 passed` on 2026-05-16 after adding
  fail-closed KIS rolling integrity reporting, model-level
  `analysis-only-replay` summaries for the 8 day, 2 swing, and 1 filter
  post-close simulation candidates, stricter replay input validation, and
  conservative KIS index snapshot high/low minute-bar handling
- full `./scripts/verify.sh`: `496 passed` on 2026-05-16 after aligning the
  research-minute DB schema with current field-monitor operating fields,
  preserving legacy backfill gaps as nullable/flagged fields, and adding raw
  10-second KIS index polling storage in `index_ticks` beside 1-minute
  `index_bars`; schema apply was also verified against the local Postgres DB
- KIS rolling minute DB integrity: blocked on 2026-05-16;
  `research_minute_raw` and `research_minute_canonical` each had only 1 KIS row,
  1 symbol, and no usable time span, so KIS rolling DB data was not accepted as
  simulation evidence
- Post-close candidate simulation report:
  `reports/phase2/post-close-simulation-report-2026-05-15-replay.json` generated
  11 model summaries from the 2026-05-15 replay artifact and is explicitly
  labeled `analysis-only-replay`, not field-start or promotion evidence
- KIS daily-bar operating input: accepted after eligible-list rerun; `2283/2283`
  included, `api_flags=none`, `source_fresh=true`, `csv_file_count=9132`;
  no partial CSVs were accepted from degraded attempts
- field universe build: accepted for target `2026-05-14`; `included_count=80`,
  `source_fresh=true`, and 80-symbol KIS list written
- KIS quote smoke: scheduled for next Monday, 2026-05-18, during market-session
  quote/depth availability; pre-open
  runs include 80/80 prices but remain `bid_ask_placeholder`; the operating
  path is now single-feed `kis-readonly-universe --include-quote-depth` with
  per-symbol price/depth timestamp gap enforcement
- DB hygiene cleanup: completed on 2026-05-16 after deferring full legacy
  backtest-data migration; `research_minute_raw`,
  `research_minute_canonical`, `universe_daily_raw`,
  `universe_daily_canonical`, and `index_bars` were verified at 0 rows, and
  table sizes returned to small empty-table footprints
- full `./scripts/verify.sh`: `509 passed` on 2026-05-16 after DB cleanup and
  schema re-application
- Gemini split review: local Gemini CLI/OAuth path restored without API-key
  mode; focused code, test, and documentation/status reviews all returned
  `APPROVE` after the oversized context was split
- official review gate: still not a full clean gate because Claude remains
  disabled by usage limit and the all-in-one review context previously exceeded
  reviewer/tooling limits; keep AI_AUTO criteria unchanged and use split review
  evidence until the official gate can be rerun cleanly
- Plan A index reconciliation rule: active; long-running workflows must update
  this index or explicitly record that it is unchanged before final reporting
