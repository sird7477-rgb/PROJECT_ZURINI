# Plan A Next Actions

Date: 2026-05-13

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

Primary references:

- Parameter contract and fallback matrix:
  [`plan-a-parameter-contract-matrix.md`](plan-a-parameter-contract-matrix.md)
- Field dry-run readiness and follow-up work:
  [`plan-a-field-dry-run-readiness.md`](plan-a-field-dry-run-readiness.md)
- Strategy validation parent plan:
  [`strategy-validation-plan.md`](strategy-validation-plan.md)
- Operator dashboard proposal:
  [`operator-dashboard-plan.md`](operator-dashboard-plan.md)

## Immediate Next Actions

| Priority | Work item | Status | Source of truth | Stop condition |
| --- | --- | --- | --- | --- |
| 0A | Fix main `field-run` universe-reuse warm-up propagation before the next field session. | implemented-targeted-tests-2026-05-15 | `reports/dry-run/analysis/2026-05-15-dryrun-strategy-analysis.md`, `reports/dry-run/field-run-control.json`, `src/zurini/cli.py` | When `field-run` reuses an accepted universe artifact, it now attaches the accepted prior warm-up path-list to the monitor pass and records `source_path_list` in universe evidence. If the source cannot be resolved, it fails closed before 장중감시 starts. Targeted regressions passed for reused-universe warm-up propagation, missing warm-up fail-closed behavior, stop-guard reuse, and auto source build. Full verify/review-gate remains required before promotion. |
| 0 | Replace today's manual dry-run startup sequence with one main module entrypoint before the next field session. | implemented-pending-review-gate | `zurini.cli field-run`, `plan-a-field-dry-run-readiness.md`, today's field-runner logs | `field-run` owns the normal no-order sequence: KIS auth/token preflight first when network mode is enabled, then automatic prior-only universe preparation when no manual symbols/report/build option is supplied. Automatic universe mode first validates the date-matched stored universe artifact without making source-collection calls. If no valid artifact exists, it builds from stored warm-up CSV sources; if stored source is missing or contract-invalid and `--run-network` is enabled, it refreshes KIS stock-master symbols, collects KIS daily bars, writes the default warm-up path-list, and rebuilds the universe. If no valid artifact/source can be prepared, it fails closed with a control report. Manual `--build-universe` / `--universe-report` remain diagnostic override paths, not the normal operating startup. KIS symbols are derived from the accepted universe; market-session quote-depth collection uses the prewarmed token cache; monitor pass, fail-closed status/control artifacts, and stop guards are owned by the same main entrypoint. The normal operating routine must refresh/prewarm the KIS token at 08:30 KST before the field session. Do not require separate manual KIS quote or monitor commands during normal startup. 장중감시모듈 수집/판단 루프는 AI감시모드 보고 주기와 분리한다. 장중감시모듈은 post-cycle sleep 금지; API throttle and collection duration only. 5분은 사람에게 보고하는 AI감시모드 주기에만 허용한다. 15:10 이후에는 watchlist 기반 swing focus 후보가 있으면 해당 후보만 다음 quote/depth 사이클에 넣고, 15:15 이후 최초 취득 snapshot으로 판단한다. Day leg entry window is exactly `10:00`-`13:30`; `13:30` is included and `13:31` is blocked as `entry-window`. |
| 1 | Collect KIS stock master files and update the local DB / market-wide symbol source. | done-2026-05-14 | `reports/dry-run/kis-stock-master.json`, `reports/dry-run/kis-source-symbols.txt` | Latest run passed: KIS stock master `symbol_count=4349`, candidate list `included_symbols=2301`, duplicate candidates excluded with `duplicate_symbol_count=43`, local DB `symbol_metadata` updated with `source=kis-stock-master` and `row_count=2301`. |
| 2 | Collect or refresh 60 trading days of KIS daily-bar source data for the refreshed local DB / market-wide symbol source. | done-2026-05-14 | `reports/dry-run/kis-daily-bars.json`, `reports/dry-run/kis-dailybar-eligibility-2026-05-14.json`, `plan-a-field-dry-run-readiness.md` | KIS daily-bar eligibility excluded `18` symbols with explicit reasons (`12` repeated missing `output2`, `6` fewer than 60 rows). The accepted eligible list then passed: `2283/2283` included, `api_flags=none`, `source_fresh=true`, `latest_prior_date=2026-05-13`, `csv_file_count=9132`, and no partial operating CSVs were accepted from degraded attempts. |
| 3 | Rebuild the next-session field universe from accepted KIS daily bars. | done-2026-05-14 | `reports/dry-run/field-universe-2026-05-14.json`, `reports/dry-run/field-universe-kis-symbols.txt` | Universe build passed in `prior-only-read-only` mode for target `2026-05-14`: `included_count=80`, `excluded_count=2203`, `loaded_bar_count=152961`, `latest_prior_date=2026-05-13`, `source_fresh=true`, and KIS symbol list has 80 symbols. |
| 4 | Run read-only KIS quote smoke for the accepted KIS symbol list. | scheduled-2026-05-18-market-session | `reports/dry-run/kis-readonly-universe.json`, `plan-a-field-dry-run-readiness.md` | Price quote smoke included `80/80` and stayed within API budget, but both normal and `--include-quote-depth` runs remain `degraded` with `api_flags=["bid_ask_placeholder"]` and `bid_ask_ratio` missing for all members. A raw pre-open depth check showed the expected bid/ask fields exist but all bid/ask quantities are `0`. User direction on 2026-05-15: handle this operating validation on next Monday, 2026-05-18. Rerun `kis-readonly-universe --include-quote-depth` after market data is live before treating it as contract-clean strategy evidence. |
| 5 | Continue no-order dry-run observation. | scheduled-after-2026-05-18-market-session-quote | `reports/dry-run/current-status-2026-05-13.json` and `plan-a-field-dry-run-readiness.md` | Resume only after a market-session quote report is contract-valid. Field monitoring must consume one `kis-readonly-universe --include-quote-depth` artifact as `--market-data-report`; separate live `kis-readonly-depth` / `--quote-depth-report` input is diagnostic-only and cannot be used as operating evidence. |
| 6 | Preserve fail-closed input gates. | active-code-guarded | `docs/AUTOMATION_OPERATING_POLICY.md`, `docs/WORKFLOW.md`, `plan-a-field-dry-run-readiness.md` | Missing/stale/contract-invalid input blocks downstream execution. |
| 7 | Add or verify final-applied parameter ledger evidence before promotion. | active-code-guarded | `plan-a-parameter-contract-matrix.md` | Accepted signals record strategy ID, group, entry/exit rule, final exits, holding, slot, and cost model in fresh dry-run evidence. |
| 8 | Keep backtest fallback matrix ready but do not rerun unless a trigger fires. | standby | `plan-a-parameter-contract-matrix.md` | Rerun only on ambiguity, stale/failed evidence, or missing final-applied manifest. |
| 9 | Keep post-close universe production routine. | recurring | `plan-a-field-dry-run-readiness.md` | After each close, refresh KIS stock master files, update the local DB / market-wide symbol source, then remove the oldest retained prior date only after the new expected prior trading day has been collected from KIS. Rebuild the next-session universe from the rolling 60-trading-day window. |

## Data Timepoint Contract

All operating inputs must distinguish two clocks.

| Input | Availability-check timepoint | Acquisition/execution timepoint | Fail-closed rule |
| --- | --- | --- | --- |
| KIS auth/token | 08:30 KST operating prewarm, plus main `field-run` network-mode startup before any universe or monitor step. | Token issue/reuse stays in process memory; no token value is persisted. | Missing credentials, auth cooldown, timeout, missing token, or immediately expired token blocks downstream universe, quote/depth, and monitor execution. |
| Daily field universe | `target_date` plus expected prior trading date. | Universe build time after source daily bars are produced. | Latest prior date must match the expected completed prior trading session; stale, missing, or self-declared-only artifact freshness blocks reuse. |
| KIS stock master / local DB / market-wide candidate symbols | Master-file collection timestamp and source market (`KOSPI`, `KOSDAQ`). | Before KIS daily-bar collection and before post-close universe rebuild. | Missing, stale, malformed, or unrefreshed stock-master input blocks market-wide daily-bar collection and universe selection. |
| KIS market-data report | Included member `observed_at` per symbol. | KIS read-only quote call/report generation time. | Each included member must be within `market-data-max-age-seconds`; one fresh member cannot mask stale members. |
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
| W9 | Review API reserved-capacity policy before order-capable rehearsal. | Do not change today's no-order dry-run. Keep current scouter/장중감시 호출 속도 unchanged. After the session, evaluate increasing total operating API budget from 12/sec to 15/sec only to expand reserved capacity for future buy/sell, order-precheck, and risk-control calls. Preserve conservative open-burst/15:10 lock-step limits unless evidence supports a separate change. | `src/zurini/api_budget.py`, `tests/test_api_budget.py` |
| W10 | Evaluate bounded parallel quote/depth collection for 장중감시모듈. | Design captured in the 2026-05-15 improvement plan. Full bounded-worker implementation remains blocked until the module split/rebuild instruction because it changes collection architecture. Pre-split guards applied: the default quote/depth pacing now accounts for the per-symbol price+depth pair and the token call, so critical-window defaults do not create self-inflicted `api_rate_limit_risk`; persistent degraded quote/depth cycles now fail closed after a bounded retry limit instead of looping for the whole market window. Required final shape: bounded worker pool, strict rate-limit budget, per-symbol timeout, per-symbol timestamp, paired price/depth freshness checks, deterministic failure classification, and no order/account/balance calls. Do not use unlimited parallel requests. | `reports/dry-run/analysis/2026-05-15-field-ops-strategy-improvement-plan.md`, `src/zurini/api_smoke.py`, `src/zurini/cli.py`, `tests/test_api_smoke.py`, `tests/test_dry_run.py` |
| W11 | Verify KIS WebSocket payload coverage before considering subscription-based 장중감시. | WebSocket is useful only if official KIS real-time trade and quote/depth payloads cover the current monitor inputs in one consistent real-time stream set: price, open/high/low, accumulated volume, accumulated traded value or enough same-stream fields to compute it, previous-day change rate, bid/ask quantities, bid/ask ratio inputs, per-symbol receive timestamps, and price-depth freshness pairing. If any required field is absent, stale, unreliable, or requires separate REST polling to fill the gap, reject WebSocket as the main monitor path because mixed-source recovery can create timestamp mismatch and strategy-meaning drift. No strategy behavior change until full payload parity is proven. | KIS official WebSocket docs/samples, `src/zurini/api_smoke.py`, `src/zurini/field_monitor.py` |
| W12 | Replace coarse pre-open polling wait with local-time alarm scheduling. | Do not change today's running session. After the session, change pre-open waits to compute the exact local KST target timestamp and sleep until that timestamp with a short final correction loop, instead of repeatedly checking every 30 seconds. Apply to 08:30 token prewarm and market-open activation. Market-open activation should wake at 08:59:30 KST, but local time is only the wake-up trigger because KIS server/market-data time may differ from local time. After wake-up, confirm market-open readiness from KIS response/market-data evidence within the API budget; as soon as readiness is confirmed, immediately enter 장중감시모듈 instead of waiting for a fixed local 09:00 timestamp. If KIS still indicates not-open or returns placeholder/stale data, keep waiting within budget. Preserve no external scheduler wrapper; the main module owns the wait. | `src/zurini/cli.py`, `tests/test_dry_run.py` |
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
| Rolling daily-bar backfill after user stop or PC downtime | Review after market close how the rolling 60-trading-day source recovers when the system is intentionally stopped or the PC is offline for one or more business days. The collector must detect all missing completed prior sessions since the last accepted source date, fetch the full gap, and only then remove old dates; a one-day-only refresh is not enough after downtime. | Promote only after gap detection, multi-day backfill, stale-window rejection, and recovery reporting are documented and covered by tests. |
| Chaos/failure-mode inventory before targeted hardening | Build a broad list of likely abnormal conditions before adding more runtime behavior: network outage, KIS timeout/rate-limit/auth cooldown, user stop/restart, PC/WSL/Docker failure, partial file writes, stale cache reuse, clock/date mismatch, missing business days, malformed reports, manual artifact edits, disk pressure, and interrupted review/automation state. Map each case to existing defense, missing defense, required artifact flag, and whether it deserves a targeted test or only an operational runbook check. | Promote only after the inventory identifies critical unguarded paths and prioritizes a small test plan; do not attempt broad chaos execution against live/read-only APIs without explicit scope. |
| News defense ON/OFF dry-run comparison | Compare OFF baseline, ON with healthy heartbeat, and ON with stale/fail-close simulation. | Promote the news path only if it improves risk filtering without API, heartbeat, or false-positive instability. |

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
- full `./scripts/verify.sh`: `402 passed`
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
- Gemini split review: local Gemini CLI/OAuth path restored without API-key
  mode; focused code, test, and documentation/status reviews all returned
  `APPROVE` after the oversized context was split
- official review gate: still not a full clean gate because Claude remains
  disabled by usage limit and the all-in-one review context previously exceeded
  reviewer/tooling limits; keep AI_AUTO criteria unchanged and use split review
  evidence until the official gate can be rerun cleanly
- Plan A index reconciliation rule: active; long-running workflows must update
  this index or explicitly record that it is unchanged before final reporting
