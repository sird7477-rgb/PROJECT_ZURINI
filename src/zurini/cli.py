from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
import tomllib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.api_smoke import (
    KisTokenCache,
    build_api_smoke_plan,
    build_kis_holiday_calendar,
    build_kis_daily_bars,
    build_kis_daily_bars_plan,
    build_kis_read_only_depth,
    build_kis_read_only_depth_plan,
    build_kis_read_only_universe,
    build_kis_read_only_universe_plan,
    prewarm_kis_token_cache,
    run_api_smoke_network,
)
from zurini.api_budget import FieldApiBudgetPolicy, KST, normalize_to_kst
from zurini.blacklist import load_async_blacklist, write_async_blacklist
from zurini.chaos import build_safe_chaos_plan, write_safe_chaos_plan
from zurini.data import db
from zurini.data.acceptance import CsvAcceptanceCriteria, assess_csv_scan
from zurini.data.continuity import assess_trade_continuity, summarize_trades_by_continuity
from zurini.data.coverage import profile_csv_coverage
from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv
from zurini.data.csv_quality import CsvScanSummary, discover_daishin_csv_paths, scan_daishin_csv_tree
from zurini.data.dummy import generate_dummy_bars
from zurini.data.large_dummy import (
    PROFILES,
    SymbolMetadata,
    generate_symbol_metadata,
    get_large_dummy_profile,
    iter_large_dummy_index_bars,
    iter_large_dummy_market_bars,
    summarize_large_dummy_profile,
)
from zurini.dry_run import (
    build_empty_plan_a_dry_run_report,
    build_plan_a_limited_sensitivity_decision,
    persist_multi_session_dry_run_report,
    persist_dry_run_report,
    run_plan_a_multi_session_dry_run,
    run_plan_a_historical_dry_run,
    write_dry_run_report,
    write_multi_session_dry_run_report,
    write_plan_a_sensitivity_decision,
)
from zurini.field_monitor import (
    build_default_field_dry_run_scenarios,
    build_field_monitor_status,
    build_primary_field_dry_run_scenarios,
    write_field_daily_review,
    write_field_monitor_status,
    write_terminal_field_monitor_status,
    write_watchlist_full_report,
)
from zurini.field_universe import (
    build_prior_only_field_universe,
    load_reusable_field_universe_artifact,
    load_prior_daily_bars_from_minute_csvs,
    write_field_universe_report,
    write_kis_symbol_list,
    write_reused_field_universe_artifact,
    write_reused_kis_symbol_list,
)
from zurini.index_trend import provider_from_index_bars
from zurini.kis_index_feed import (
    build_kis_index_poll_plan,
    build_kis_index_poll_snapshot,
    index_bars_from_report,
    index_samples_from_report,
)
from zurini.market import Bar
from zurini.news_adapter import (
    collect_news_risk_events,
    write_news_adapter_events,
    write_news_adapter_report,
)
from zurini.news_blacklist_collector import load_news_risk_events, update_blacklist_from_news_events
from zurini.observability import append_event_jsonl, build_event
from zurini.observed_sessions import build_observed_session_plan, write_observed_session_plan
from zurini.operations import build_local_ops_status, write_local_ops_status
from zurini.stock_master import (
    KIS_STOCK_MASTER_SOURCE,
    build_kis_stock_master,
    build_kis_stock_master_plan,
    write_kis_stock_master_report,
    write_kis_stock_master_symbol_list,
)
from zurini.strategies.regime import (
    RegimeFilteredStrategy,
    RelativeStrengthFilteredStrategy,
    allowed_regimes,
    load_index_bars,
    load_regime_states,
)
from zurini.strategies.baseline import (
    ConfirmedPullbackDayStrategy,
    DaySupportPullbackStrategy,
    DefensivePullbackDayStrategy,
    GapReboundDayStrategy,
    IntradayMomentumSwingSupportPortfolioStrategy,
    IntradayMomentumContinuationStrategy,
    OpeningRangeBreakoutDayStrategy,
    PriorMomentumContinuationStrategy,
    SwingMomentumStrategy,
    SwingSupportStrategy,
    VwapFirstPullbackStrategy,
)
from zurini.phase2 import (
    build_monthly_rehearsal_plan,
    build_phase2_batch_summary,
    discover_report_paths,
    read_path_list,
    write_monthly_rehearsal_plan,
    write_phase2_batch_summary,
)
from zurini.reports.files import write_backtest_outputs

DEFAULT_CONFIG = Path("config/phase1-backtest.toml")


@dataclass(frozen=True)
class DummyConfig:
    symbols: list[str]
    seed: int
    trading_day: str
    minutes: int


@dataclass(frozen=True)
class Phase1Config:
    dummy: DummyConfig
    backtest: BacktestConfig
    output_dir: Path


@dataclass(frozen=True)
class FieldRunUniversePreparation:
    evidence: dict[str, object] | None
    symbols: tuple[str, ...]
    path: tuple[Path, ...]
    path_list: tuple[Path, ...]
    root: tuple[Path, ...]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "backtest":
        return run_backtest_command(args)
    if args.command == "load-sample":
        return run_load_sample_command(args)
    if args.command == "backtest-csv":
        return run_backtest_csv_command(args)
    if args.command == "scan-csv":
        return run_scan_csv_command(args)
    if args.command == "phase2-monthly-plan":
        return run_phase2_monthly_plan_command(args)
    if args.command == "phase2-summarize-runs":
        return run_phase2_summarize_runs_command(args)
    if args.command == "phase2-coverage":
        return run_phase2_coverage_command(args)
    if args.command == "phase2-observed-plan":
        return run_phase2_observed_plan_command(args)
    if args.command == "api-smoke":
        return run_api_smoke_command(args)
    if args.command == "kis-readonly-universe":
        return run_kis_readonly_universe_command(args)
    if args.command == "kis-stock-master-refresh":
        return run_kis_stock_master_refresh_command(args)
    if args.command == "kis-daily-bars":
        return run_kis_daily_bars_command(args)
    if args.command == "kis-readonly-depth":
        return run_kis_readonly_depth_command(args)
    if args.command == "update-news-blacklist":
        return run_update_news_blacklist_command(args)
    if args.command == "collect-news-risk-events":
        return run_collect_news_risk_events_command(args)
    if args.command == "build-field-universe":
        return run_build_field_universe_command(args)
    if args.command == "build-daily-field-universe":
        return run_build_daily_field_universe_command(args)
    if args.command == "rehearse-large-dummy":
        return run_rehearse_large_dummy_command(args)
    if args.command == "ops-status":
        return run_ops_status_command(args)
    if args.command == "record-event":
        return run_record_event_command(args)
    if args.command == "chaos-plan":
        return run_chaos_plan_command(args)
    if args.command == "plan-a-dry-run":
        return run_plan_a_dry_run_command(args)
    if args.command == "plan-a-dry-run-multi":
        return run_plan_a_dry_run_multi_command(args)
    if args.command == "dry-run-resume-state":
        return run_dry_run_resume_state_command(args)
    if args.command == "field-dry-run-monitor":
        return run_field_dry_run_monitor_command(args)
    if args.command == "field-run":
        return run_field_run_command(args)
    if args.command == "plan-a-sensitivity":
        return run_plan_a_sensitivity_command(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zurini")
    subparsers = parser.add_subparsers(dest="command")

    backtest = subparsers.add_parser("backtest", help="run the phase-1 dummy multi-symbol backtest")
    backtest.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    backtest.add_argument("--output-dir", type=Path)
    backtest.add_argument("--keep-db", action="store_true", help="do not reset market_bars before loading")

    load_sample = subparsers.add_parser("load-sample", help="load a Daishin/CYBOS minute CSV sample into Postgres")
    load_sample.add_argument("--path", type=Path, required=True)
    load_sample.add_argument("--symbol", help="symbol override; defaults to CSV file stem")
    load_sample.add_argument("--source", default="sample")
    load_sample.add_argument("--output-dir", type=Path, default=Path("reports/sample"))
    load_sample.add_argument("--keep-db", action="store_true", help="do not reset market_bars before loading")

    backtest_csv = subparsers.add_parser("backtest-csv", help="run a backtest from Daishin/CYBOS minute CSV files")
    backtest_csv.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    backtest_csv.add_argument("--path", type=Path, action="append", default=[])
    backtest_csv.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    backtest_csv.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    backtest_csv.add_argument("--symbol", action="append", help="symbol override matching each --path; defaults to file stems")
    backtest_csv.add_argument("--source", default="sample")
    backtest_csv.add_argument("--limit-files", type=int, help="limit discovered CSV files for smoke runs")
    backtest_csv.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    backtest_csv.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    backtest_csv.add_argument("--start-equity", help="override config backtest.start_equity")
    backtest_csv.add_argument("--quantity-step", help="override config backtest.quantity_step")
    backtest_csv.add_argument("--capital-mode", choices=["per-symbol", "shared-slot"], help="override config backtest.capital_mode")
    backtest_csv.add_argument("--max-open-positions", type=int, help="override config backtest.max_open_positions")
    backtest_csv.add_argument(
        "--signal-group-max-open-positions",
        action="append",
        default=[],
        metavar="GROUP=N",
        help="cap concurrent shared-slot positions for a signal group, e.g. day=1",
    )
    backtest_csv.add_argument(
        "--variable-slot-count",
        action="store_true",
        help="derive shared-slot max positions from account equity and --slot-capital-cap",
    )
    backtest_csv.add_argument("--slot-capital-cap", help="maximum planned deployed capital per slot")
    backtest_csv.add_argument("--weekly-contribution", help="external cash contribution added on each new observed week")
    backtest_csv.add_argument("--max-daily-stop-losses", type=int, help="disable new shared-slot entries after N daily hard stops")
    backtest_csv.add_argument("--max-daily-loss", help="disable new shared-slot entries after daily realized net loss reaches this KRW amount")
    backtest_csv.add_argument("--fee-rate", help="override config backtest.fee_rate")
    backtest_csv.add_argument("--slippage-rate", help="override config backtest.slippage_rate")
    backtest_csv.add_argument("--profit-target", help="override config backtest.profit_target")
    backtest_csv.add_argument("--hard-stop", help="override config backtest.hard_stop")
    backtest_csv.add_argument("--day-end-exit-time", help="KST HH:MM forced day-end exit cutoff")
    backtest_csv.add_argument("--max-holding-minutes", type=int, help="override config backtest.max_holding_minutes")
    backtest_csv.add_argument("--hold-overnight", action="store_true", help="disable day-end forced exits")
    backtest_csv.add_argument("--intrabar-policy", choices=["close-only", "conservative"], help="override config backtest.intrabar_policy")
    backtest_csv.add_argument(
        "--ambiguous-intrabar-policy",
        choices=["stop-first"],
        help="override config backtest.ambiguous_intrabar_policy",
    )
    backtest_csv.add_argument("--pullback-band", help="override VWAP pullback band")
    backtest_csv.add_argument("--min-bid-ask-ratio", help="override VWAP pressure threshold")
    backtest_csv.add_argument(
        "--strategy",
        choices=[
            "vwap",
            "a-day-v2",
            "confirmed-day-pullback",
            "day-support-pullback",
            "gap-rebound",
            "intraday-momentum",
            "portfolio-idmom-swing-support",
            "opening-range-breakout",
            "prior-momentum",
            "swing-support",
            "swing-momentum",
        ],
        help="strategy implementation",
    )
    backtest_csv.add_argument("--entry-start", help="KST HH:MM lower bound for new entries")
    backtest_csv.add_argument("--entry-end", help="KST HH:MM upper bound for new entries")
    backtest_csv.add_argument("--entry-mode", choices=["pullback", "breakout"], help="VWAP entry mode")
    backtest_csv.add_argument(
        "--require-above-vwap",
        action="store_true",
        help="only enter pullbacks that remain at or above prior VWAP",
    )
    backtest_csv.add_argument("--impulse-threshold", help="minimum close/VWAP impulse threshold before pullback entry")
    backtest_csv.add_argument("--min-impulse-volume", type=int, help="minimum impulse-bar volume before pullback entry")
    backtest_csv.add_argument("--impulse-volume-window", type=int, help="lookback bars for relative impulse-volume checks")
    backtest_csv.add_argument("--impulse-volume-multiple", help="minimum impulse volume divided by recent average volume")
    backtest_csv.add_argument("--aday-sma-window", type=int, help="prior-only SMA window for A-DAY-v2 universe")
    backtest_csv.add_argument("--aday-atr-window", type=int, help="prior-only ATR window for A-DAY-v2 universe")
    backtest_csv.add_argument("--aday-value-window", type=int, help="prior-only traded-value window for A-DAY-v2 universe")
    backtest_csv.add_argument("--aday-min-average-value", help="minimum prior average traded value for A-DAY-v2 universe")
    backtest_csv.add_argument("--aday-min-atr-ratio", help="minimum prior ATR/close ratio for A-DAY-v2 universe")
    backtest_csv.add_argument("--aday-max-opening-gap", help="maximum absolute opening gap for A-DAY-v2 scouter")
    backtest_csv.add_argument("--aday-min-session-value", help="minimum same-day observed traded value before A-DAY-v2 entry")
    backtest_csv.add_argument("--aday-reclaim-threshold", help="minimum rebound from armed pullback for confirmed-day-pullback")
    backtest_csv.add_argument("--opening-range-minutes", type=int, help="opening range duration for opening-range-breakout")
    backtest_csv.add_argument("--opening-breakout-buffer", help="close above opening range high required for opening-range-breakout")
    backtest_csv.add_argument("--opening-max-range-ratio", help="maximum opening range high/low span for opening-range-breakout")
    backtest_csv.add_argument("--momentum-min-day-return", help="minimum return from day open for intraday-momentum")
    backtest_csv.add_argument("--momentum-max-day-return", help="maximum return from day open for intraday-momentum")
    backtest_csv.add_argument("--momentum-min-vwap-distance", help="minimum close/VWAP distance for intraday-momentum")
    backtest_csv.add_argument("--prior-min-return", help="minimum prior daily return for prior-momentum")
    backtest_csv.add_argument("--prior-max-return", help="maximum prior daily return for prior-momentum")
    backtest_csv.add_argument("--prior-confirm-above-close", help="minimum current close over prior close for prior-momentum")
    backtest_csv.add_argument("--gap-min-down", help="minimum opening gap down for gap-rebound")
    backtest_csv.add_argument("--gap-max-down", help="maximum opening gap down for gap-rebound")
    backtest_csv.add_argument("--gap-reclaim-over-prior-close", help="minimum close over prior close for gap-rebound")
    backtest_csv.add_argument("--gap-min-vwap-distance", help="minimum close/VWAP distance for gap-rebound")
    backtest_csv.add_argument("--swing-sma-window", type=int, help="daily SMA window for swing-support strategy")
    backtest_csv.add_argument("--swing-volume-window", type=int, help="daily volume average window for swing-support strategy")
    backtest_csv.add_argument("--swing-support-band", help="SMA support band for swing-support strategy")
    backtest_csv.add_argument("--swing-max-volume-ratio", help="maximum current/average volume ratio for swing-support strategy")
    backtest_csv.add_argument("--swing-max-rsi", help="maximum RSI(14) for swing-support strategy")
    backtest_csv.add_argument("--swing-min-sma-distance", help="minimum close/SMA distance for swing-momentum strategy")
    backtest_csv.add_argument("--swing-min-volume-ratio", help="minimum current/average volume ratio for swing-momentum strategy")
    backtest_csv.add_argument("--swing-min-rsi", help="minimum RSI(14) for swing-momentum strategy")
    backtest_csv.add_argument("--regime-filter", choices=["bull-only", "non-bear"], help="block long entries outside allowed index regimes")
    backtest_csv.add_argument("--regime-index-root", type=Path, default=Path("data/raw/daishin/index-bars"))
    backtest_csv.add_argument("--regime-index-symbol", default="U001")
    backtest_csv.add_argument("--min-relative-strength", help="minimum symbol intraday return minus index intraday return")
    backtest_csv.add_argument("--output-dir", type=Path, default=Path("reports/sample-backtest"))
    backtest_csv.add_argument("--keep-db", action="store_true", help="do not reset market_bars before loading")
    backtest_csv.add_argument(
        "--skip-db",
        action="store_true",
        help="run directly from loaded CSV bars for fast strategy iteration; does not persist bars to Postgres",
    )
    backtest_csv.add_argument(
        "--trade-continuity-mode",
        choices=["exact-bar", "dense-window"],
        default="dense-window",
        help="dense-window preserves legacy grid audits; pass exact-bar for sparse phase-2 stock trade-event data",
    )

    scan_csv = subparsers.add_parser("scan-csv", help="scan Daishin/CYBOS CSV files without loading Postgres")
    scan_csv.add_argument("--root", type=Path, required=True, help="CSV file or directory tree")
    scan_csv.add_argument("--source", default="sample")
    scan_csv.add_argument("--output", type=Path, default=Path("reports/csv-scan.json"))
    scan_csv.add_argument("--acceptance-report", type=Path, help="write a phase-2 data acceptance report")
    scan_csv.add_argument("--min-success-rate", type=float, default=1.0)
    scan_csv.add_argument("--max-error-count", type=int, default=0)
    scan_csv.add_argument("--max-duplicate-timestamps", type=int, default=0)
    scan_csv.add_argument("--max-gap-count", type=int)
    scan_csv.add_argument("--max-missing-minutes", type=int)
    scan_csv.add_argument("--max-gap-minutes", type=int)
    scan_csv.add_argument("--max-zero-volume-count", type=int)
    scan_csv.add_argument("--min-symbols", type=int)
    scan_csv.add_argument("--min-periods", type=int)

    phase2_plan = subparsers.add_parser(
        "phase2-monthly-plan",
        help="prepare a phase-2 completed-month path list and backtest command",
    )
    phase2_plan.add_argument("--root", type=Path, default=Path("data/raw/daishin/minute-bars"))
    phase2_plan.add_argument("--output-dir", type=Path, default=Path("reports/phase2/monthly-rehearsal"))
    phase2_plan.add_argument("--current-yyyymm", help="override current month boundary for tests/replays")
    phase2_plan.add_argument("--limit-symbols", type=int, default=100)
    phase2_plan.add_argument("--month", action="append", help="restrict to specific completed YYYYMM periods")
    phase2_plan.add_argument(
        "--coverage-report",
        type=Path,
        action="append",
        default=[],
        help="require accepted day-set coverage evidence for completed-month selection",
    )

    phase2_summary = subparsers.add_parser(
        "phase2-summarize-runs",
        help="summarize one or more phase-2 backtest report.json files",
    )
    phase2_summary.add_argument("--report", type=Path, action="append", default=[])
    phase2_summary.add_argument("--report-list", type=Path, action="append", default=[])
    phase2_summary.add_argument("--root", type=Path, action="append", default=[], help="report.json file or directory tree")
    phase2_summary.add_argument("--output-json", type=Path, default=Path("reports/phase2/batch-summary.json"))
    phase2_summary.add_argument("--output-md", type=Path, default=Path("reports/phase2/batch-summary.md"))

    phase2_coverage = subparsers.add_parser(
        "phase2-coverage",
        help="profile phase-2 CSV coverage for strict index grids or sparse stock bars",
    )
    phase2_coverage.add_argument("--root", type=Path, required=True)
    phase2_coverage.add_argument("--class-mode", choices=["index-grid", "stock-sparse"], required=True)
    phase2_coverage.add_argument("--source", default="daishin-historical")
    phase2_coverage.add_argument("--period", action="append", default=[], help="restrict to YYYYMM period directories")
    phase2_coverage.add_argument("--limit-files", type=int, help="limit files for bounded smoke profiling")
    phase2_coverage.add_argument("--progress-every", type=int, default=0, help="write progress to stderr every N files")
    phase2_coverage.add_argument(
        "--require-day-set",
        action="store_true",
        help="require every expected trading day in the month to be present",
    )
    phase2_coverage.add_argument("--output", type=Path, default=Path("reports/phase2/coverage.json"))

    observed_plan = subparsers.add_parser(
        "phase2-observed-plan",
        help="build an observed-index-session block plan without dropping whole partial months",
    )
    observed_plan.add_argument("--index-root", type=Path, default=Path("data/raw/daishin/index-bars"))
    observed_plan.add_argument("--stock-root", type=Path, default=Path("data/raw/daishin/minute-bars"))
    observed_plan.add_argument("--output-dir", type=Path, default=Path("reports/phase2/observed-session"))
    observed_plan.add_argument("--limit-symbols", type=int, default=100)
    observed_plan.add_argument("--min-trading-days", type=int, default=20)
    observed_plan.add_argument("--select-block", default="", help="select a specific observed block name instead of the longest block")

    api_smoke = subparsers.add_parser("api-smoke", help="write a read-only API smoke-test plan")
    api_smoke.add_argument("--output", type=Path, default=Path("reports/api-smoke-plan.json"))
    api_smoke.add_argument(
        "--allow-network",
        action="store_true",
        help="mark probes network-capable when required environment variables exist; no orders are allowed",
    )
    api_smoke.add_argument(
        "--run-network",
        action="store_true",
        help="run read-only network smoke probes; no orders, balances, accounts, or secret output are allowed",
    )
    api_smoke.add_argument("--symbol", default="005930", help="KIS paper market-data symbol for read-only smoke")

    kis_universe = subparsers.add_parser(
        "kis-readonly-universe",
        help="build a no-order KIS read-only quote universe artifact",
    )
    kis_universe.add_argument("--symbol", action="append", default=[], help="KIS domestic stock symbol, repeatable")
    kis_universe.add_argument("--symbol-list", type=Path, action="append", default=[], help="newline-delimited symbol list")
    kis_universe.add_argument("--allow-network", action="store_true", help="allow read-only KIS market-data network checks")
    kis_universe.add_argument("--run-network", action="store_true", help="run read-only KIS quote calls; no order/account/balance calls")
    kis_universe.add_argument(
        "--quote-interval-seconds",
        help="override delay between KIS read-only quote calls when --run-network is used",
    )
    kis_universe.add_argument(
        "--rate-profile",
        choices=["prod", "paper"],
        default="prod",
        help="KIS REST pacing profile for read-only quote smoke; prod uses the conservative field budget",
    )
    kis_universe.add_argument(
        "--endpoint-profile",
        choices=["prod", "paper"],
        default="paper",
        help="KIS endpoint/auth profile for read-only quote smoke; paper is default, prod requires --confirm-prod-readonly",
    )
    kis_universe.add_argument(
        "--confirm-prod-readonly",
        action="store_true",
        help="required with --run-network --endpoint-profile prod to confirm production read-only quote calls",
    )
    kis_universe.add_argument(
        "--include-quote-depth",
        action="store_true",
        help="also call the read-only quote-depth endpoint per symbol and merge bid/ask ratio into the same snapshot",
    )
    _add_market_session_stop_arguments(kis_universe)
    kis_universe.add_argument("--output", type=Path, default=Path("reports/dry-run/kis-readonly-universe.json"))

    kis_stock_master = subparsers.add_parser(
        "kis-stock-master-refresh",
        help="refresh KIS stock master files and update local candidate symbols",
    )
    kis_stock_master.add_argument(
        "--market",
        action="append",
        choices=["KOSPI", "KOSDAQ"],
        default=[],
        help="market to inspect in offline plan mode; operational network refresh always requires both KOSPI and KOSDAQ",
    )
    kis_stock_master.add_argument("--allow-network", action="store_true", help="allow KIS public stock master downloads")
    kis_stock_master.add_argument("--run-network", action="store_true", help="download KIS public stock master files")
    kis_stock_master.add_argument(
        "--symbol-list-output",
        type=Path,
        default=Path("reports/dry-run/kis-source-symbols.txt"),
        help="write refreshed market-wide candidate symbols for downstream KIS daily-bar collection",
    )
    kis_stock_master.add_argument("--report-output", type=Path, default=Path("reports/dry-run/kis-stock-master.json"))

    kis_daily = subparsers.add_parser(
        "kis-daily-bars",
        help="collect no-order KIS read-only domestic daily OHLCV bars",
    )
    kis_daily.add_argument("--symbol", action="append", default=[], help="KIS domestic stock symbol, repeatable")
    kis_daily.add_argument("--symbol-list", type=Path, action="append", default=[], help="newline-delimited symbol list")
    kis_daily.add_argument("--start-date", required=True, help="inclusive YYYY-MM-DD start date")
    kis_daily.add_argument("--end-date", required=True, help="inclusive YYYY-MM-DD end date")
    kis_daily.add_argument(
        "--min-trading-days",
        type=int,
        default=60,
        help="minimum KIS daily rows required per included symbol; operating universe input uses 60 trading days",
    )
    kis_daily.add_argument("--allow-network", action="store_true", help="allow read-only KIS daily-bar network checks")
    kis_daily.add_argument("--run-network", action="store_true", help="run read-only KIS period-price calls; no order/account/balance calls")
    kis_daily.add_argument(
        "--quote-interval-seconds",
        help="override delay between KIS read-only daily-bar calls when --run-network is used",
    )
    kis_daily.add_argument(
        "--rate-profile",
        choices=["prod", "paper"],
        default="prod",
        help="KIS REST pacing profile for read-only daily-bar collection; prod uses the conservative field budget",
    )
    kis_daily.add_argument(
        "--endpoint-profile",
        choices=["prod", "paper"],
        default="paper",
        help="KIS endpoint/auth profile; paper is default, prod requires --confirm-prod-readonly",
    )
    kis_daily.add_argument(
        "--confirm-prod-readonly",
        action="store_true",
        help="required with --run-network --endpoint-profile prod to confirm production read-only daily-bar calls",
    )
    kis_daily.add_argument("--output-root", type=Path, default=Path("data/raw/kis/daily-bars"))
    kis_daily.add_argument("--report-output", type=Path, default=Path("reports/dry-run/kis-daily-bars.json"))

    kis_depth = subparsers.add_parser(
        "kis-readonly-depth",
        help="build a no-order KIS read-only quote-depth artifact",
    )
    kis_depth.add_argument("--symbol", action="append", default=[], help="KIS domestic stock symbol, repeatable")
    kis_depth.add_argument("--symbol-list", type=Path, action="append", default=[], help="newline-delimited symbol list")
    kis_depth.add_argument("--allow-network", action="store_true", help="allow read-only KIS quote-depth network checks")
    kis_depth.add_argument("--run-network", action="store_true", help="run read-only KIS quote-depth calls; no order/account/balance calls")
    kis_depth.add_argument(
        "--quote-interval-seconds",
        help="override delay between KIS read-only quote-depth calls when --run-network is used",
    )
    kis_depth.add_argument(
        "--rate-profile",
        choices=["prod", "paper"],
        default="prod",
        help="KIS REST pacing profile for read-only quote-depth smoke; prod uses the conservative field budget",
    )
    kis_depth.add_argument(
        "--endpoint-profile",
        choices=["prod", "paper"],
        default="paper",
        help="KIS endpoint/auth profile for read-only quote-depth smoke; paper is default, prod requires --confirm-prod-readonly",
    )
    kis_depth.add_argument(
        "--confirm-prod-readonly",
        action="store_true",
        help="required with --run-network --endpoint-profile prod to confirm production read-only quote-depth calls",
    )
    kis_depth.add_argument(
        "--paired-market-data-report",
        type=Path,
        help="existing KIS price snapshot report used only to calculate timestamp gap evidence",
    )
    _add_market_session_stop_arguments(kis_depth)
    kis_depth.add_argument("--output", type=Path, default=Path("reports/dry-run/kis-readonly-depth.json"))

    news_blacklist = subparsers.add_parser(
        "update-news-blacklist",
        help="update async blacklist from local news/DART webhook payload files; no broker/API calls",
    )
    news_blacklist.add_argument("--event-json", type=Path, action="append", default=[], help="news risk event JSON file")
    news_blacklist.add_argument("--existing", type=Path, help="existing async blacklist JSON to merge")
    news_blacklist.add_argument(
        "--allow-empty-heartbeat",
        action="store_true",
        help="explicitly allow a heartbeat refresh without news event files",
    )
    news_blacklist.add_argument("--ttl-minutes", type=int, default=60, help="default block duration for events without expires_at")
    news_blacklist.add_argument("--now", help="override collector heartbeat timestamp, ISO-8601")
    news_blacklist.add_argument("--output", type=Path, default=Path("reports/dry-run/news-blacklist.json"))

    news_events = subparsers.add_parser(
        "collect-news-risk-events",
        help="collect local/file-fed news, DART, or RSS risk events for async blacklist input; no broker/order calls",
    )
    news_events.add_argument("--news-json", type=Path, action="append", default=[], help="generic news JSON file")
    news_events.add_argument("--dart-json", type=Path, action="append", default=[], help="DART-style disclosure JSON file")
    news_events.add_argument("--rss", type=Path, action="append", default=[], help="RSS XML file captured by an external fetcher")
    news_events.add_argument("--news-json-url", action="append", default=[], help="generic news JSON URL; requires --allow-network --run-network")
    news_events.add_argument("--dart-json-url", action="append", default=[], help="DART-style disclosure JSON URL; requires --allow-network --run-network")
    news_events.add_argument("--rss-url", action="append", default=[], help="RSS XML URL; requires --allow-network --run-network")
    news_events.add_argument("--allow-network", action="store_true", help="allow external news/RSS/DART read-only fetches")
    news_events.add_argument("--run-network", action="store_true", help="run external news/RSS/DART read-only fetches")
    news_events.add_argument("--timeout-seconds", type=float, default=10.0, help="external news fetch timeout when --run-network is used")
    news_events.add_argument("--source-max-age-minutes", type=int, default=60, help="fail closed when source item timestamps are older than this age")
    news_events.add_argument("--now", help="override adapter heartbeat timestamp, ISO-8601")
    news_events.add_argument("--events-output", type=Path, default=Path("reports/dry-run/news-risk-events.json"))
    news_events.add_argument("--report-output", type=Path, default=Path("reports/dry-run/news-adapter-report.json"))

    field_universe = subparsers.add_parser(
        "build-field-universe",
        help="build a prior-only field universe from local market bars",
    )
    field_universe.add_argument("--target-date", required=True, help="next field date in YYYY-MM-DD format")
    field_universe.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS minute CSV path")
    field_universe.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    field_universe.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    field_universe.add_argument("--source", default="field-universe")
    field_universe.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded universe build")
    field_universe.add_argument(
        "--latest-months",
        type=int,
        default=2,
        help="when --root contains YYYYMM folders, load only the latest N available months at or before target-date",
    )
    field_universe.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    field_universe.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    field_universe.add_argument("--value-window", type=int, default=5)
    field_universe.add_argument("--sma-window", type=int, default=20)
    field_universe.add_argument("--atr-window", type=int, default=14)
    field_universe.add_argument("--min-prior-trading-days", type=int, default=60)
    field_universe.add_argument("--min-average-value", default="50000000000")
    field_universe.add_argument("--min-atr-ratio", default="0.03")
    field_universe.add_argument("--disable-close-above-sma", action="store_true")
    field_universe.add_argument("--max-symbols", type=int, default=100)
    field_universe.add_argument("--max-prior-data-lag-days", type=int, help="fail closed when latest prior source date is older than this many calendar days before target-date")
    field_universe.add_argument("--expected-prior-date", help="required latest prior source date in YYYY-MM-DD for operating reuse/builds")
    field_universe.add_argument("--krx-holiday", action="append", default=[], help="YYYY-MM-DD market holiday used when deriving expected prior trading date")
    field_universe.add_argument("--universe-id", default="field-u1-prior-only")
    field_universe.add_argument("--standby-artifact", type=Path, help="reuse candidate prior-only universe artifact")
    field_universe.add_argument("--reuse-standby-artifact", action="store_true", help="validate and reuse --standby-artifact before rebuilding")
    field_universe.add_argument("--max-standby-artifact-age-minutes", type=int, help="fail closed when reused standby artifact is older than this age")
    field_universe.add_argument("--kis-symbol-list-output", type=Path, help="write included KIS symbols for read-only KIS quote smoke")
    field_universe.add_argument("--output", type=Path, default=Path("reports/dry-run/field-universe.json"))

    daily_field_universe = subparsers.add_parser(
        "build-daily-field-universe",
        help="build the next-session prior-only universe for the daily post-close/pre-open routine",
    )
    daily_field_universe.add_argument("--target-date", help="next field date in YYYY-MM-DD format; defaults to next weekday")
    daily_field_universe.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS minute CSV path")
    daily_field_universe.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    daily_field_universe.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    daily_field_universe.add_argument("--source", default="daily-field-universe")
    daily_field_universe.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded universe build")
    daily_field_universe.add_argument("--latest-months", type=int, default=2)
    daily_field_universe.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    daily_field_universe.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    daily_field_universe.add_argument("--value-window", type=int, default=5)
    daily_field_universe.add_argument("--sma-window", type=int, default=20)
    daily_field_universe.add_argument("--atr-window", type=int, default=14)
    daily_field_universe.add_argument("--min-prior-trading-days", type=int, default=60)
    daily_field_universe.add_argument("--min-average-value", default="50000000000")
    daily_field_universe.add_argument("--min-atr-ratio", default="0.03")
    daily_field_universe.add_argument("--disable-close-above-sma", action="store_true")
    daily_field_universe.add_argument("--max-symbols", type=int, default=100)
    daily_field_universe.add_argument("--max-prior-data-lag-days", type=int, default=3, help="fail closed when latest prior source date is older than this many calendar days before target-date")
    daily_field_universe.add_argument("--expected-prior-date", help="required latest prior source date in YYYY-MM-DD; defaults to previous weekday minus --krx-holiday dates")
    daily_field_universe.add_argument("--disable-expected-prior-date", action="store_true", help="analysis-only escape hatch; do not use for operating universe builds")
    daily_field_universe.add_argument("--krx-holiday", action="append", default=[], help="YYYY-MM-DD market holiday used when deriving expected prior trading date")
    daily_field_universe.add_argument("--universe-id", default="field-u1-prior-only")
    daily_field_universe.add_argument("--standby-artifact", type=Path, help="reuse candidate prior-only universe artifact")
    daily_field_universe.add_argument("--reuse-standby-artifact", action="store_true", help="validate and reuse --standby-artifact before rebuilding")
    daily_field_universe.add_argument("--max-standby-artifact-age-minutes", type=int, default=720, help="fail closed when reused standby artifact is older than this age")
    daily_field_universe.add_argument("--kis-symbol-list-output", type=Path, help="write included KIS symbols for read-only KIS quote smoke")
    daily_field_universe.add_argument("--output", type=Path, default=Path("reports/dry-run/daily-field-universe.json"))

    rehearse = subparsers.add_parser(
        "rehearse-large-dummy",
        help="run a bounded phase-1.5 synthetic large-data rehearsal",
    )
    rehearse.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    rehearse.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    rehearse.add_argument("--output-dir", type=Path, default=Path("reports/phase15-large-dummy"))
    rehearse.add_argument(
        "--include-quality-anomalies",
        action="store_true",
        help="include optional gap/zero-volume quality fixtures and report duplicate/invalid fixtures",
    )
    rehearse.add_argument(
        "--dry-run",
        action="store_true",
        help="write only the profile/count/anomaly report without loading Postgres or running a backtest",
    )
    rehearse.add_argument(
        "--max-materialized-market-rows",
        type=int,
        default=200_000,
        help="guardrail that prevents accidental full local materialization on 16 GB PCs",
    )
    rehearse.add_argument("--keep-db", action="store_true", help="do not reset rehearsal tables before loading")

    ops_status = subparsers.add_parser("ops-status", help="check local report artifacts without network or broker actions")
    ops_status.add_argument("--report", type=Path, action="append", default=[], help="JSON report artifact to validate")
    ops_status.add_argument("--output", type=Path, default=Path("reports/ops/status.json"))

    record_event = subparsers.add_parser("record-event", help="append a redacted local operational JSONL event")
    record_event.add_argument("--run-id", required=True)
    record_event.add_argument("--event-type", required=True)
    record_event.add_argument("--component", required=True)
    record_event.add_argument("--status", required=True)
    record_event.add_argument("--severity", default="info")
    record_event.add_argument("--message", default="")
    record_event.add_argument("--output", type=Path, default=Path("reports/ops/events.jsonl"))

    chaos_plan = subparsers.add_parser("chaos-plan", help="write safe local fixture-based chaos-test plan")
    chaos_plan.add_argument("--output", type=Path, default=Path("reports/ops/chaos-plan.json"))

    dry_run = subparsers.add_parser(
        "plan-a-dry-run",
        help="write a no-order Plan A dry-run session report scaffold",
    )
    dry_run.add_argument("--trading-date", required=True, help="dry-run trading date in YYYY-MM-DD format")
    dry_run.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS minute CSV path")
    dry_run.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    dry_run.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    dry_run.add_argument("--source", default="dry-run")
    dry_run.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded dry-run smoke")
    dry_run.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    dry_run.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    dry_run.add_argument("--max-trading-days", type=int, help="limit dry-run to first N observed trading days")
    dry_run.add_argument("--session-id", help="stable dry-run session identifier")
    dry_run.add_argument("--persist-db", action="store_true", help="persist the no-order dry-run report to the local DB ledger")
    dry_run.add_argument("--api-rate-limit-per-second", type=int, default=20, help="future field API per-second call budget")
    dry_run.add_argument("--local-free-space-gb", help="override local free-space guardrail estimate in GB")
    dry_run.add_argument("--enable-raw-burst", action="store_true", help="enable short-TTL event-window raw burst capture contract")
    dry_run.add_argument("--blacklist", type=Path, help="async blacklist JSON; stale or listed symbols block new entries")
    dry_run.add_argument("--enable-index-trend-filter", action="store_true", help="block day entries when KOSPI/KOSDAQ trend is missing, stale, or bearish")
    dry_run.add_argument("--index-trend-report", type=Path, action="append", default=[], help="KIS index poll report for post-close trend-filter simulation")
    dry_run.add_argument("--output", type=Path, default=Path("reports/dry-run/plan-a-session.json"))

    dry_run_multi = subparsers.add_parser(
        "plan-a-dry-run-multi",
        help="write a multi-session no-order Plan A dry-run report",
    )
    dry_run_multi.add_argument("--run-id", required=True, help="stable multi-session dry-run identifier")
    dry_run_multi.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS minute CSV path")
    dry_run_multi.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    dry_run_multi.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    dry_run_multi.add_argument("--source", default="dry-run")
    dry_run_multi.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded dry-run smoke")
    dry_run_multi.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    dry_run_multi.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    dry_run_multi.add_argument("--max-trading-days", type=int, help="limit dry-run to first N observed trading days")
    dry_run_multi.add_argument("--starting-seed", default="1000000", help="starting dry-run seed capital")
    dry_run_multi.add_argument(
        "--api-rate-limit-per-second",
        type=int,
        default=20,
        help="future field API per-second call budget",
    )
    dry_run_multi.add_argument("--local-free-space-gb", help="override local free-space guardrail estimate in GB")
    dry_run_multi.add_argument("--enable-raw-burst", action="store_true", help="enable short-TTL event-window raw burst capture contract")
    dry_run_multi.add_argument("--blacklist", type=Path, help="async blacklist JSON; stale or listed symbols block new entries")
    dry_run_multi.add_argument("--enable-index-trend-filter", action="store_true", help="block day entries when KOSPI/KOSDAQ trend is missing, stale, or bearish")
    dry_run_multi.add_argument("--index-trend-report", type=Path, action="append", default=[], help="KIS index poll report for post-close trend-filter simulation")
    dry_run_multi.add_argument("--persist-db", action="store_true", help="persist every no-order dry-run session to the local DB ledger")
    dry_run_multi.add_argument("--output", type=Path, default=Path("reports/dry-run/plan-a-multi-session.json"))

    resume_state = subparsers.add_parser(
        "dry-run-resume-state",
        help="write latest no-order dry-run DB resume state; no broker/order/account calls",
    )
    resume_state.add_argument("--session-id-prefix", help="optional dry-run session id prefix")
    resume_state.add_argument("--as-of", help="resume state cutoff timestamp, ISO-8601")
    resume_state.add_argument("--target-trading-date", help="required latest session trading_date in YYYY-MM-DD")
    resume_state.add_argument("--max-session-age-minutes", type=int, default=60, help="fail closed when latest session/event evidence is older than this age at --as-of/current time")
    resume_state.add_argument("--output", type=Path, default=Path("reports/dry-run/resume-state.json"))

    monitor = subparsers.add_parser(
        "field-dry-run-monitor",
        help="write local-csv no-order field dry-run monitor status; not a live field-data/API readiness proof",
    )
    monitor.add_argument("--run-id", required=True, help="stable field dry-run monitor identifier")
    monitor.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS minute CSV path")
    monitor.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited CSV paths")
    monitor.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    monitor.add_argument("--source", default="field-monitor-local")
    monitor.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded dry-run smoke")
    monitor.add_argument("--start-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    monitor.add_argument("--end-date", help="inclusive YYYY-MM-DD filter for loaded bars")
    monitor.add_argument("--max-trading-days", type=int, help="limit each scenario to first N observed trading days")
    monitor.add_argument("--api-rate-limit-per-second", type=int, default=20, help="future field API per-second call budget")
    monitor.add_argument("--local-free-space-gb", help="override local free-space guardrail estimate in GB")
    monitor.add_argument("--enable-raw-burst", action="store_true", help="enable short-TTL event-window raw burst capture contract")
    monitor.add_argument("--watch", action="store_true", help="declare watch-mode contract; this local command still performs one bounded pass")
    monitor.add_argument("--market-data-report", type=Path, action="append", default=[], help="read KIS read-only quote universe reports as no-order field snapshots")
    monitor.add_argument(
        "--market-data-max-age-seconds",
        type=int,
        default=120,
        help="degrade monitor status when the newest market-data observed_at is older than this TTL",
    )
    monitor.add_argument(
        "--quote-depth-report",
        type=Path,
        action="append",
        default=[],
        help="merge KIS read-only quote-depth reports into market snapshots by symbol",
    )
    monitor.add_argument("--api-report", type=Path, action="append", default=[], help="read API smoke/universe report flags into monitor status")
    monitor.add_argument("--blacklist", type=Path, help="async blacklist JSON; stale heartbeat becomes a monitor degradation flag")
    monitor.add_argument("--require-news-feed", action="store_true", help="degrade monitor status when async news/blacklist feed is absent")
    monitor.add_argument("--enable-index-trend-filter", action="store_true", help="block day-entry scenarios when real-time index trend is unavailable or bearish")
    monitor.add_argument("--index-trend-report", type=Path, action="append", default=[], help="KIS index poll report used as no-order trend-filter evidence")
    monitor.add_argument("--persist-db", action="store_true", help="persist scenario no-order dry-run ledgers to the local DB")
    _add_market_session_stop_arguments(monitor)
    monitor.add_argument("--output-dir", type=Path, default=Path("reports/dry-run/field-monitor"))
    monitor.add_argument("--status-output", type=Path, default=Path("reports/dry-run/current-status.json"))

    field_run = subparsers.add_parser(
        "field-run",
        help="run the one-command no-order field sequence: KIS quote-depth snapshot then field monitor pass",
    )
    field_run.add_argument("--run-id", required=True, help="stable field run identifier")
    field_run.add_argument("--symbol", action="append", default=[], help="KIS domestic stock symbol, repeatable")
    field_run.add_argument("--symbol-list", type=Path, action="append", default=[], help="newline-delimited KIS symbol list")
    field_run.add_argument("--build-universe", action="store_true", help="build the prior-only field universe before the first monitor cycle")
    field_run.add_argument("--universe-report", type=Path, help="accepted field-universe artifact to preflight before polling")
    field_run.add_argument("--universe-output", type=Path, default=Path("reports/dry-run/field-universe.json"))
    field_run.add_argument("--universe-id", default="field-u1-prior-only")
    field_run.add_argument("--expected-prior-date", help="YYYY-MM-DD expected completed prior trading date for --universe-report")
    field_run.add_argument("--krx-holiday", action="append", default=[], help="YYYY-MM-DD KRX holiday for expected prior-date calculation")
    field_run.add_argument("--max-prior-data-lag-days", type=int, default=3, help="maximum accepted source-date lag in the reusable universe artifact")
    field_run.add_argument("--max-universe-artifact-age-minutes", type=int, default=720, help="maximum accepted age for the reusable universe artifact")
    field_run.add_argument("--path", type=Path, action="append", default=[], help="Daishin/CYBOS warm-up CSV path")
    field_run.add_argument("--path-list", type=Path, action="append", default=[], help="newline-delimited warm-up CSV paths")
    field_run.add_argument("--root", type=Path, action="append", default=[], help="warm-up CSV file or directory tree")
    field_run.add_argument("--limit-files", type=int, help="limit discovered CSV files for bounded universe/warm-up runs")
    field_run.add_argument("--latest-months", type=int, default=2)
    field_run.add_argument("--start-date", help="inclusive YYYY-MM-DD warm-up filter")
    field_run.add_argument("--end-date", help="inclusive YYYY-MM-DD warm-up filter")
    field_run.add_argument("--value-window", type=int, default=5)
    field_run.add_argument("--sma-window", type=int, default=20)
    field_run.add_argument("--atr-window", type=int, default=14)
    field_run.add_argument("--min-prior-trading-days", type=int, default=60)
    field_run.add_argument("--min-average-value", default="50000000000")
    field_run.add_argument("--min-atr-ratio", default="0.03")
    field_run.add_argument("--disable-close-above-sma", action="store_true")
    field_run.add_argument("--max-symbols", type=int, default=100)
    field_run.add_argument("--max-trading-days", type=int, help="limit each scenario to first N observed trading days")
    field_run.add_argument("--allow-network", action="store_true", help="allow read-only KIS market-data network checks")
    field_run.add_argument("--run-network", action="store_true", help="run read-only KIS quote/depth calls; no order/account/balance calls")
    field_run.add_argument("--endpoint-profile", choices=["prod", "paper"], default="prod")
    field_run.add_argument("--rate-profile", choices=["prod", "paper"], default="prod")
    field_run.add_argument("--confirm-prod-readonly", action="store_true")
    field_run.add_argument("--quote-interval-seconds", help="override KIS quote pacing between read calls")
    field_run.add_argument("--skip-quote-depth", action="store_true", help="diagnostic escape hatch; operating field runs should not use this")
    field_run.add_argument("--market-data-max-age-seconds", type=int, default=120)
    field_run.add_argument("--api-rate-limit-per-second", type=int, default=20)
    field_run.add_argument("--local-free-space-gb")
    field_run.add_argument("--enable-raw-burst", action="store_true")
    field_run.add_argument("--blacklist", type=Path)
    field_run.add_argument("--require-news-feed", action="store_true")
    field_run.add_argument("--enable-index-trend-filter", action="store_true")
    field_run.add_argument("--index-poll-interval-seconds", type=int, default=10)
    field_run.add_argument("--index-report", type=Path, default=Path("reports/dry-run/kis-index-trend.json"))
    field_run.add_argument("--index-trend-report", type=Path, action="append", default=[], help="additional post-close/index trend reports to pass into monitor")
    field_run.add_argument("--persist-db", action="store_true")
    field_run.add_argument("--cycle-limit", type=int, help="bounded cycle count for tests or planned finite runs")
    field_run.add_argument("--quote-degraded-retry-limit", type=int, default=3, help="fail closed after this many consecutive degraded quote/depth cycles")
    field_run.add_argument("--quote-degraded-backoff-seconds", type=float, default=5.0, help="cooldown before retrying after a degraded quote/depth cycle")
    field_run.add_argument("--swing-focus-start-time", default="15:10", help="KST HH:MM time to switch to swing candidate focus when candidates exist")
    field_run.add_argument("--max-swing-focus-symbols", type=int, default=50)
    field_run.add_argument("--source", default="field-run-main")
    field_run.add_argument("--quote-report", type=Path, default=Path("reports/dry-run/kis-readonly-universe.json"))
    field_run.add_argument("--output-dir", type=Path, default=Path("reports/dry-run/field-monitor"))
    field_run.add_argument("--status-output", type=Path, default=Path("reports/dry-run/current-status.json"))
    field_run.add_argument("--control-output", type=Path, default=Path("reports/dry-run/field-run-control.json"))
    field_run.add_argument("--ai-report-interval-seconds", type=int, default=300)
    _add_market_session_stop_arguments(field_run)

    sensitivity = subparsers.add_parser(
        "plan-a-sensitivity",
        help="write the bounded Plan A sensitivity decision record",
    )
    sensitivity.add_argument("--output", type=Path, default=Path("reports/dry-run/plan-a-sensitivity-decision.json"))
    return parser


def run_backtest_command(args: argparse.Namespace) -> int:
    config = load_config(args.config, output_dir=args.output_dir)
    bars = generate_configured_dummy_bars(config.dummy)

    with db.workflow_lock():
        if args.keep_db:
            db.apply_schema()
        else:
            db.reset_market_bars()
        inserted = db.insert_bars(bars)

        loaded: list[Bar] = []
        for symbol in config.dummy.symbols:
            loaded.extend(db.fetch_bars(symbol))

    report, trades = run_backtest(loaded, config=config.backtest)
    outputs = write_backtest_outputs(
        report=report,
        trades=trades,
        output_dir=config.output_dir,
        symbols=config.dummy.symbols,
        inserted_rows=inserted,
    )

    print(f"symbols={','.join(config.dummy.symbols)}")
    print(f"inserted_rows={inserted}")
    print(f"trade_count={report.trade_count}")
    print(f"net_pnl={report.net_pnl}")
    print(f"report={outputs['json']}")
    return 0


def run_load_sample_command(args: argparse.Namespace) -> int:
    bars = load_daishin_minute_csv(args.path, symbol=args.symbol, source=args.source)
    report = build_csv_quality_report(bars, source_path=args.path, symbol=args.symbol, source=args.source)

    with db.workflow_lock():
        if args.keep_db:
            db.apply_schema()
        else:
            db.reset_market_bars()
        inserted = db.insert_bars(bars)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "sample-quality.json"
    payload = report.as_dict() | {"inserted_rows": inserted}
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"symbol={report.symbol}")
    print(f"inserted_rows={inserted}")
    print(f"first_timestamp={report.first_timestamp}")
    print(f"last_timestamp={report.last_timestamp}")
    print(f"gap_count={report.gap_count}")
    print(f"report={report_path}")
    return 0


def run_backtest_csv_command(args: argparse.Namespace) -> int:
    config = load_config(args.config, output_dir=args.output_dir)
    if args.root and args.symbol:
        raise ValueError("--symbol overrides are only supported with explicit --path arguments")
    paths = _csv_paths(args.path, args.root, args.path_list)
    if args.limit_files is not None:
        paths = paths[: args.limit_files]
    symbols = _csv_symbols(paths, args.symbol)
    report_symbols = _unique_preserve_order(symbols)
    bars: list[Bar] = []
    quality_reports = []
    for path, symbol in zip(paths, symbols, strict=True):
        loaded = load_daishin_minute_csv(path, symbol=symbol, source=args.source)
        loaded = _filter_bars_by_date(loaded, start_date=args.start_date, end_date=args.end_date)
        bars.extend(loaded)
        quality_reports.append(build_csv_quality_report(loaded, source_path=path, symbol=symbol, source=args.source))

    if args.skip_db:
        inserted = len(bars)
        loaded_from_db = sorted(bars, key=lambda bar: (bar.symbol, bar.timestamp))
    else:
        with db.workflow_lock():
            if args.keep_db:
                db.apply_schema()
            else:
                db.reset_market_bars()
            inserted = db.insert_bars(bars)

            loaded_from_db: list[Bar] = []
            for symbol in report_symbols:
                loaded_from_db.extend(db.fetch_bars(symbol))

    backtest_config = _override_backtest_config(config.backtest, args)
    strategy_factory = _strategy_factory_from_args(args)
    strategy_factory = _apply_regime_filter(strategy_factory, args)
    strategy_factory = _apply_relative_strength_filter(strategy_factory, args)
    report, trades = run_backtest(loaded_from_db, config=backtest_config, strategy_factory=strategy_factory)
    continuity = assess_trade_continuity(loaded_from_db, trades, audit_mode=args.trade_continuity_mode)
    continuity_trades = summarize_trades_by_continuity(trades, continuity)
    outputs = write_backtest_outputs(
        report=report,
        trades=trades,
        output_dir=args.output_dir,
        symbols=report_symbols,
        inserted_rows=inserted,
        title="PROJECT_ZURINI phase-1 CSV sample backtest",
        extra={
            "trade_continuity": continuity.as_dict(),
            "trade_continuity_summary": continuity_trades.as_dict(),
            "phase2_parameters": {
                "start_equity": str(backtest_config.start_equity),
                "quantity_step": str(backtest_config.quantity_step),
                "capital_mode": backtest_config.capital_mode,
                "max_open_positions": backtest_config.max_open_positions,
                "signal_group_max_open_positions": dict(
                    backtest_config.signal_group_max_open_positions
                ),
                "variable_slot_count": backtest_config.variable_slot_count,
                "slot_capital_cap": (
                    str(backtest_config.slot_capital_cap)
                    if backtest_config.slot_capital_cap is not None
                    else None
                ),
                "weekly_contribution": str(backtest_config.weekly_contribution),
                "max_daily_stop_losses": backtest_config.max_daily_stop_losses,
                "max_daily_loss": str(backtest_config.max_daily_loss) if backtest_config.max_daily_loss is not None else None,
                "profit_target": str(backtest_config.profit_target),
                "hard_stop": str(backtest_config.hard_stop),
                "day_end_exit": backtest_config.day_end_exit,
                "day_end_exit_time": (
                    backtest_config.day_end_exit_time.strftime("%H:%M")
                    if backtest_config.day_end_exit_time is not None
                    else None
                ),
                "max_holding_minutes": backtest_config.max_holding_minutes,
                "fee_rate": str(backtest_config.fee_rate),
                "slippage_rate": str(backtest_config.slippage_rate),
                "intrabar_policy": backtest_config.intrabar_policy,
                "ambiguous_intrabar_policy": backtest_config.ambiguous_intrabar_policy,
                "execution_path": "memory" if args.skip_db else "postgres",
                "strategy": args.strategy or "default",
                "pullback_band": str(_decimal(args.pullback_band)) if args.pullback_band else "default",
                "min_bid_ask_ratio": str(_decimal(args.min_bid_ask_ratio)) if args.min_bid_ask_ratio else "default",
                "entry_start": args.entry_start or "default",
                "entry_end": args.entry_end or "default",
                "entry_mode": args.entry_mode or "default",
                "require_above_vwap": bool(args.require_above_vwap),
                "impulse_threshold": str(_decimal(args.impulse_threshold)) if args.impulse_threshold else "default",
                "min_impulse_volume": args.min_impulse_volume if args.min_impulse_volume is not None else "default",
                "impulse_volume_window": (
                    args.impulse_volume_window if args.impulse_volume_window is not None else "default"
                ),
                "impulse_volume_multiple": (
                    str(_decimal(args.impulse_volume_multiple)) if args.impulse_volume_multiple else "default"
                ),
                "aday_sma_window": args.aday_sma_window if args.aday_sma_window is not None else "default",
                "aday_atr_window": args.aday_atr_window if args.aday_atr_window is not None else "default",
                "aday_value_window": args.aday_value_window if args.aday_value_window is not None else "default",
                "aday_min_average_value": (
                    str(_decimal(args.aday_min_average_value)) if args.aday_min_average_value else "default"
                ),
                "aday_min_atr_ratio": (
                    str(_decimal(args.aday_min_atr_ratio)) if args.aday_min_atr_ratio else "default"
                ),
                "aday_max_opening_gap": (
                    str(_decimal(args.aday_max_opening_gap)) if args.aday_max_opening_gap else "default"
                ),
                "aday_min_session_value": (
                    str(_decimal(args.aday_min_session_value)) if args.aday_min_session_value else "default"
                ),
                "aday_reclaim_threshold": (
                    str(_decimal(args.aday_reclaim_threshold)) if args.aday_reclaim_threshold else "default"
                ),
                "opening_range_minutes": (
                    args.opening_range_minutes if args.opening_range_minutes is not None else "default"
                ),
                "opening_breakout_buffer": (
                    str(_decimal(args.opening_breakout_buffer)) if args.opening_breakout_buffer else "default"
                ),
                "opening_max_range_ratio": (
                    str(_decimal(args.opening_max_range_ratio)) if args.opening_max_range_ratio else "default"
                ),
                "momentum_min_day_return": (
                    str(_decimal(args.momentum_min_day_return)) if args.momentum_min_day_return else "default"
                ),
                "momentum_max_day_return": (
                    str(_decimal(args.momentum_max_day_return)) if args.momentum_max_day_return else "default"
                ),
                "momentum_min_vwap_distance": (
                    str(_decimal(args.momentum_min_vwap_distance)) if args.momentum_min_vwap_distance else "default"
                ),
                "prior_min_return": str(_decimal(args.prior_min_return)) if args.prior_min_return else "default",
                "prior_max_return": str(_decimal(args.prior_max_return)) if args.prior_max_return else "default",
                "prior_confirm_above_close": (
                    str(_decimal(args.prior_confirm_above_close)) if args.prior_confirm_above_close else "default"
                ),
                "gap_min_down": str(_decimal(args.gap_min_down)) if args.gap_min_down else "default",
                "gap_max_down": str(_decimal(args.gap_max_down)) if args.gap_max_down else "default",
                "gap_reclaim_over_prior_close": (
                    str(_decimal(args.gap_reclaim_over_prior_close))
                    if args.gap_reclaim_over_prior_close
                    else "default"
                ),
                "gap_min_vwap_distance": (
                    str(_decimal(args.gap_min_vwap_distance)) if args.gap_min_vwap_distance else "default"
                ),
                "swing_sma_window": args.swing_sma_window if args.swing_sma_window is not None else "default",
                "swing_volume_window": (
                    args.swing_volume_window if args.swing_volume_window is not None else "default"
                ),
                "swing_support_band": (
                    str(_decimal(args.swing_support_band)) if args.swing_support_band else "default"
                ),
                "swing_max_volume_ratio": (
                    str(_decimal(args.swing_max_volume_ratio)) if args.swing_max_volume_ratio else "default"
                ),
                "swing_max_rsi": str(_decimal(args.swing_max_rsi)) if args.swing_max_rsi else "default",
                "swing_min_sma_distance": (
                    str(_decimal(args.swing_min_sma_distance)) if args.swing_min_sma_distance else "default"
                ),
                "swing_min_volume_ratio": (
                    str(_decimal(args.swing_min_volume_ratio)) if args.swing_min_volume_ratio else "default"
                ),
                "swing_min_rsi": str(_decimal(args.swing_min_rsi)) if args.swing_min_rsi else "default",
                "regime_filter": args.regime_filter or "default",
                "regime_index_root": (
                    str(args.regime_index_root)
                    if args.regime_filter or args.min_relative_strength
                    else "default"
                ),
                "regime_index_symbol": (
                    args.regime_index_symbol
                    if args.regime_filter or args.min_relative_strength
                    else "default"
                ),
                "min_relative_strength": (
                    str(_decimal(args.min_relative_strength)) if args.min_relative_strength else "default"
                ),
            },
        },
    )
    quality_path = args.output_dir / "csv-quality.json"
    quality_path.write_text(
        json.dumps([item.as_dict() for item in quality_reports], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"symbols={','.join(symbols)}")
    print(f"inserted_rows={inserted}")
    print(f"trade_count={report.trade_count}")
    print(f"net_pnl={report.net_pnl}")
    print(f"report={outputs['json']}")
    print(f"quality_report={quality_path}")
    return 0


def run_phase2_observed_plan_command(args: argparse.Namespace) -> int:
    plan = build_observed_session_plan(
        index_root=args.index_root,
        stock_root=args.stock_root,
        output_dir=args.output_dir,
        limit_symbols=args.limit_symbols,
        min_trading_days=args.min_trading_days,
        select_block=args.select_block,
    )
    outputs = write_observed_session_plan(plan)
    print(f"accepted_day_count={plan.accepted_day_count}")
    print(f"rejected_day_count={plan.rejected_day_count}")
    print(f"block_count={len(plan.blocks)}")
    print(f"selected_block={plan.selected_block.name if plan.selected_block else ''}")
    print(f"selected_dates={(plan.selected_block.start_date + '..' + plan.selected_block.end_date) if plan.selected_block else ''}")
    print(f"selected_symbol_count={len(plan.selected_symbols)}")
    print(f"path_count={len(plan.path_list)}")
    print(f"plan={outputs['plan']}")
    print(f"path_list={outputs['path_list']}")
    print("recommended_command=" + " ".join(plan.recommended_command))
    return 0 if plan.selected_block and plan.selected_symbols else 1


def run_scan_csv_command(args: argparse.Namespace) -> int:
    summary = scan_daishin_csv_tree(args.root, source=args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    acceptance = _csv_acceptance_result(args, summary) if args.acceptance_report else None
    if args.acceptance_report:
        args.acceptance_report.parent.mkdir(parents=True, exist_ok=True)
        args.acceptance_report.write_text(
            json.dumps(
                {
                    "purpose": "phase-2 real-data intake gate before DB promotion",
                    "real_data_source_boundary": (
                        "promoted stage/API data source is Korea Investment Securities only; "
                        "two-year historical raw acquisition may use Daishin Securities CYBOS "
                        "only as unpromoted read-only intake"
                    ),
                    "scan": summary.as_dict(),
                    "acceptance": acceptance.as_dict() if acceptance else None,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    print(f"root={summary.root}")
    print(f"file_count={summary.file_count}")
    print(f"ok_count={summary.ok_count}")
    print(f"error_count={summary.error_count}")
    print(f"success_rate={summary.success_rate:.4f}")
    print(f"symbol_count={summary.symbol_count}")
    print(f"period_count={summary.period_count}")
    print(f"row_count={summary.row_count}")
    print(f"gap_count={summary.gap_count}")
    print(f"missing_minutes_count={summary.missing_minutes_count}")
    print(f"max_gap_minutes={summary.max_gap_minutes}")
    print(f"report={args.output}")
    if args.acceptance_report:
        print(f"acceptance_status={acceptance.status if acceptance else 'not-run'}")
        print(f"acceptance_report={args.acceptance_report}")
    if acceptance:
        return 0 if acceptance.accepted else 1
    return 1 if summary.error_count else 0


def run_phase2_monthly_plan_command(args: argparse.Namespace) -> int:
    plan = build_monthly_rehearsal_plan(
        args.root,
        output_dir=args.output_dir,
        current_yyyymm=args.current_yyyymm,
        limit_symbols=args.limit_symbols,
        requested_months=args.month,
        coverage_reports=args.coverage_report,
    )
    outputs = write_monthly_rehearsal_plan(plan)

    print(f"root={plan.root}")
    print(f"month_count={len(plan.months)}")
    print(f"selected_months={','.join(plan.selected_months)}")
    print(f"excluded_months={','.join(plan.excluded_months)}")
    print(f"selected_symbol_count={len(plan.selected_symbols)}")
    print(f"path_count={len(plan.path_list)}")
    print(f"plan={outputs['plan']}")
    print(f"path_list={outputs['path_list']}")
    print("recommended_command=" + " ".join(plan.recommended_command))
    return 0 if plan.selected_months and plan.selected_symbols else 1


def run_phase2_summarize_runs_command(args: argparse.Namespace) -> int:
    report_paths = list(args.report)
    for report_list in args.report_list:
        report_paths.extend(read_path_list(report_list))
    paths = discover_report_paths(report_paths, args.root)
    summary = build_phase2_batch_summary(paths)
    write_phase2_batch_summary(summary, output_json=args.output_json, output_markdown=args.output_md)

    print(f"report_count={summary.report_count}")
    print(f"total_inserted_rows={summary.total_inserted_rows}")
    print(f"total_trade_count={summary.total_trade_count}")
    print(f"total_net_pnl={summary.total_net_pnl}")
    print(f"total_valid_trades={summary.total_valid_trades}")
    print(f"total_invalid_trades={summary.total_invalid_trades}")
    print(f"total_ambiguous_intrabar_trades={summary.total_ambiguous_intrabar_trades}")
    print(f"continuity_status={summary.continuity_status}")
    print(f"optimization_gate_status={summary.optimization_gate_status}")
    print(f"summary_json={args.output_json}")
    print(f"summary_md={args.output_md}")
    return 0


def run_phase2_coverage_command(args: argparse.Namespace) -> int:
    summary = profile_csv_coverage(
        args.root,
        class_mode=args.class_mode,
        source=args.source,
        periods=args.period,
        limit_files=args.limit_files,
        progress_every=args.progress_every,
        require_day_set=args.require_day_set,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if summary.file_count == 0:
        print("warning=no csv files matched the requested root/period filters", file=sys.stderr)
    print(f"root={summary.root}")
    print(f"class_mode={summary.class_mode}")
    print(f"calendar_version={summary.calendar_version}")
    print(f"calendar_certified={str(summary.calendar_certified).lower()}")
    print(f"file_count={summary.file_count}")
    print(f"ok_count={summary.ok_count}")
    print(f"error_count={summary.error_count}")
    print(f"accepted_count={summary.accepted_count}")
    print(f"acceptance_status={summary.acceptance_status}")
    print(f"coverage_ratio={summary.coverage_ratio:.6f}")
    print(f"missing_minutes_count={summary.missing_minutes_count}")
    print(f"longest_missing_run={summary.longest_missing_run}")
    print(f"missing_edge_minutes={summary.missing_edge_minutes}")
    print(f"expected_trading_days={summary.expected_trading_days}")
    print(f"observed_trading_days={summary.observed_trading_days}")
    print(f"missing_trading_day_count={len(summary.missing_trading_days)}")
    print(f"day_set_evaluated={str(summary.day_set_evaluated).lower()}")
    print(f"day_set_complete={str(summary.day_set_complete).lower()}")
    print(f"promotable_calendar={str(summary.promotable_calendar).lower()}")
    print(f"out_of_session_count={summary.out_of_session_count}")
    print(f"zero_volume_count={summary.zero_volume_count}")
    print(f"report={args.output}")
    return 0 if summary.acceptance_status == "accepted" else 1


def run_ops_status_command(args: argparse.Namespace) -> int:
    status = build_local_ops_status(args.report)
    write_local_ops_status(status, args.output)
    print(f"status={status.status}")
    print(f"checked_report_count={len(status.checked_reports)}")
    print(f"report={args.output}")
    return 0 if status.status == "ok" else 1


def run_record_event_command(args: argparse.Namespace) -> int:
    event = build_event(
        run_id=args.run_id,
        event_type=args.event_type,
        component=args.component,
        status=args.status,
        severity=args.severity,
        message=args.message,
    )
    append_event_jsonl(args.output, event)
    print(f"event_status={event.status}")
    print(f"event_log={args.output}")
    return 0


def run_chaos_plan_command(args: argparse.Namespace) -> int:
    plan = build_safe_chaos_plan()
    write_safe_chaos_plan(plan, args.output)
    print(f"status={plan.status}")
    print(f"execution_mode={plan.execution_mode}")
    print(f"scenario_count={len(plan.scenarios)}")
    print(f"report={args.output}")
    return 0


def run_api_smoke_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    payload = (
        run_api_smoke_network(symbol=args.symbol, auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"))
        if args.run_network
        else build_api_smoke_plan(allow_network=args.allow_network)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status={payload['status']}")
    print(f"mode={payload['mode']}")
    print(f"report={args.output}")
    if args.run_network:
        return 0 if payload["status"] == "passed" else 1
    if args.allow_network:
        return 0 if payload["status"] == "ready" else 1
    return 0


def run_kis_readonly_universe_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    if args.run_network and args.endpoint_profile == "prod" and not args.confirm_prod_readonly:
        raise ValueError("--run-network --endpoint-profile prod requires --confirm-prod-readonly")
    symbols = tuple(args.symbol) + tuple(_read_symbol_lists(args.symbol_list))
    stop_guard = _market_session_stop_guard(args)
    if stop_guard is not None:
        result = {
            "status": "stopped",
            "mode": "market-session-closed",
            "universe_id": "kis-readonly-session-closed",
            "symbol_count": len(symbols),
            "symbols": list(symbols),
            "included_symbols": [],
            "excluded_symbols": [{"symbol": symbol, "reason": "market-session-closed"} for symbol in symbols],
            "members": [],
            "api_flags": ["market_session_closed"],
            "read_call_count": 0,
            "budget_evidence": {
                "source": f"kis-readonly-universe-{args.endpoint_profile}",
                "within_budget": True,
                "measured_read_calls": 0,
                "stop_guard": stop_guard,
            },
            "ready_for_broker_or_order_transmission": False,
            "safety_boundary": "read-only market-data calls skipped after configured market-session stop",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"status={result['status']}")
        print(f"mode={result['mode']}")
        print(f"universe_id={result['universe_id']}")
        print(f"symbol_count={result['symbol_count']}")
        print("included_symbols=0")
        print("api_flags=market_session_closed")
        print(f"report={args.output}")
        return 0
    result = (
        build_kis_read_only_universe(
            symbols=symbols,
            quote_interval_seconds=_kis_quote_interval(args),
            endpoint_profile=args.endpoint_profile,
            auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
            confirm_prod_readonly=args.confirm_prod_readonly,
            include_quote_depth=args.include_quote_depth,
        ).as_dict()
        if args.run_network
        else build_kis_read_only_universe_plan(symbols=symbols)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status={result['status']}")
    print(f"mode={result['mode']}")
    print(f"universe_id={result['universe_id']}")
    print(f"symbol_count={result['symbol_count']}")
    if "included_symbols" in result:
        print(f"included_symbols={len(result['included_symbols'])}")
        print(f"api_flags={','.join(result['api_flags']) if result['api_flags'] else 'none'}")
    print(f"report={args.output}")
    if args.run_network:
        if args.include_quote_depth:
            return 0 if result["status"] == "passed" else 1
        return 0 if result["status"] in {"passed", "degraded"} else 1
    return 0


def run_kis_daily_bars_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    if args.run_network and args.endpoint_profile == "prod" and not args.confirm_prod_readonly:
        raise ValueError("--run-network --endpoint-profile prod requires --confirm-prod-readonly")
    symbols = tuple(args.symbol) + tuple(_read_symbol_lists(args.symbol_list))
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    result = (
        build_kis_daily_bars(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            quote_interval_seconds=_kis_quote_interval(args),
            endpoint_profile=args.endpoint_profile,
            auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
            confirm_prod_readonly=args.confirm_prod_readonly,
            min_trading_days=args.min_trading_days,
        ).as_dict()
        if args.run_network
        else build_kis_daily_bars_plan(symbols=symbols, start_date=start_date, end_date=end_date)
    )
    if args.run_network:
        written = _write_kis_daily_bar_csvs(result, args.output_root) if result["status"] == "passed" else 0
        result["csv_output_root"] = str(args.output_root)
        result["csv_file_count"] = written
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status={result['status']}")
    print(f"mode={result['mode']}")
    print(f"symbol_count={result['symbol_count']}")
    if "included_symbols" in result:
        print(f"included_symbols={len(result['included_symbols'])}")
        print(f"api_flags={','.join(result['api_flags']) if result['api_flags'] else 'none'}")
    if args.run_network:
        print(f"csv_output_root={args.output_root}")
    print(f"report={args.report_output}")
    if args.run_network:
        return 0 if result["status"] == "passed" else 1
    return 0


def run_kis_stock_master_refresh_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    markets = tuple(args.market) if args.market else ("KOSPI", "KOSDAQ")
    if args.run_network and set(markets) != {"KOSPI", "KOSDAQ"}:
        raise ValueError("operational KIS stock master refresh requires both KOSPI and KOSDAQ")
    result = (
        build_kis_stock_master(markets=markets).as_dict()
        if args.run_network
        else build_kis_stock_master_plan(markets=markets)
    )
    if args.run_network and result["status"] == "passed":
        try:
            metadata = _symbol_metadata_from_stock_master_members(result["members"])
            db.apply_schema()
            with db.workflow_lock():
                updated_rows = db.replace_symbol_metadata_source(metadata, source=KIS_STOCK_MASTER_SOURCE)
        except Exception as exc:
            result["status"] = "failed"
            result["api_flags"] = list(result.get("api_flags", [])) + ["local_db_update_failed"]
            result["local_db_update"] = {
                "table": "symbol_metadata",
                "source": KIS_STOCK_MASTER_SOURCE,
                "error_type": type(exc).__name__,
            }
        else:
            result["local_db_update"] = {
                "table": "symbol_metadata",
                "source": KIS_STOCK_MASTER_SOURCE,
                "row_count": updated_rows,
            }
            write_kis_stock_master_symbol_list(result["included_symbols"], args.symbol_list_output)
            result["symbol_list_output"] = str(args.symbol_list_output)
    write_kis_stock_master_report(result, args.report_output)

    print(f"status={result['status']}")
    print(f"mode={result['mode']}")
    print(f"symbol_count={result.get('symbol_count', 0)}")
    if "included_symbols" in result:
        print(f"included_symbols={len(result['included_symbols'])}")
        print(f"api_flags={','.join(result['api_flags']) if result['api_flags'] else 'none'}")
    if result.get("symbol_list_output"):
        print(f"symbol_list_output={result['symbol_list_output']}")
    print(f"report={args.report_output}")
    if args.run_network:
        return 0 if result["status"] == "passed" else 1
    return 0


def run_kis_readonly_depth_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    if args.run_network and args.endpoint_profile == "prod" and not args.confirm_prod_readonly:
        raise ValueError("--run-network --endpoint-profile prod requires --confirm-prod-readonly")
    symbols = tuple(args.symbol) + tuple(_read_symbol_lists(args.symbol_list))
    stop_guard = _market_session_stop_guard(args)
    if stop_guard is not None:
        result = {
            "status": "stopped",
            "mode": "market-session-closed",
            "universe_id": "kis-readonly-depth-session-closed",
            "symbol_count": len(symbols),
            "symbols": list(symbols),
            "included_symbols": [],
            "excluded_symbols": [{"symbol": symbol, "reason": "market-session-closed"} for symbol in symbols],
            "members": [],
            "api_flags": ["market_session_closed"],
            "read_call_count": 0,
            "budget_evidence": {
                "source": f"kis-readonly-depth-{args.endpoint_profile}",
                "within_budget": True,
                "measured_read_calls": 0,
                "stop_guard": stop_guard,
            },
            "ready_for_broker_or_order_transmission": False,
            "safety_boundary": "read-only quote-depth calls skipped after configured market-session stop",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"status={result['status']}")
        print(f"mode={result['mode']}")
        print(f"universe_id={result['universe_id']}")
        print(f"symbol_count={result['symbol_count']}")
        print("included_symbols=0")
        print("api_flags=market_session_closed")
        print(f"report={args.output}")
        return 0
    paired_price_report = None
    if args.paired_market_data_report:
        paired_price_report = json.loads(args.paired_market_data_report.read_text(encoding="utf-8"))
    result = (
        build_kis_read_only_depth(
            symbols=symbols,
            quote_interval_seconds=_kis_quote_interval(args),
            endpoint_profile=args.endpoint_profile,
            auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
            confirm_prod_readonly=args.confirm_prod_readonly,
            paired_price_report=paired_price_report,
        ).as_dict()
        if args.run_network
        else build_kis_read_only_depth_plan(symbols=symbols)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"status={result['status']}")
    print(f"mode={result['mode']}")
    print(f"universe_id={result['universe_id']}")
    print(f"symbol_count={result['symbol_count']}")
    if "included_symbols" in result:
        print(f"included_symbols={len(result['included_symbols'])}")
        print(f"api_flags={','.join(result['api_flags']) if result['api_flags'] else 'none'}")
    if result.get("paired_snapshot_evidence"):
        evidence = result["paired_snapshot_evidence"]
        print(f"paired_count={evidence['paired_count']}")
        print(f"max_gap_seconds={evidence['max_gap_seconds']}")
        print(f"fresh_pairing={evidence['fresh_pairing']}")
    print(f"report={args.output}")
    if args.run_network:
        return 0 if result["status"] in {"passed", "degraded"} else 1
    return 0


def run_update_news_blacklist_command(args: argparse.Namespace) -> int:
    if not args.event_json and not args.allow_empty_heartbeat:
        raise ValueError("update-news-blacklist requires --event-json or explicit --allow-empty-heartbeat")
    now = _parse_cli_datetime(args.now) if args.now else normalize_to_kst(datetime.now().astimezone())
    existing = load_async_blacklist(args.existing) if args.existing else None
    events = tuple(event for path in args.event_json for event in load_news_risk_events(path))
    snapshot = update_blacklist_from_news_events(
        existing=existing,
        events=events,
        now=now,
        ttl=timedelta(minutes=args.ttl_minutes),
    )
    write_async_blacklist(snapshot, args.output)
    print("status=passed")
    print("mode=news-blacklist-collector")
    print(f"event_count={len(events)}")
    print(f"active_entries={len(snapshot.entries)}")
    print(f"output={args.output}")
    return 0


def run_collect_news_risk_events_command(args: argparse.Namespace) -> int:
    network_sources = [*args.news_json_url, *args.dart_json_url, *args.rss_url]
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    if network_sources and not args.run_network:
        raise ValueError("URL sources require --allow-network --run-network")
    if not args.news_json and not args.dart_json and not args.rss and not network_sources:
        raise ValueError(
            "collect-news-risk-events requires at least one --news-json, --dart-json, --rss, --news-json-url, --dart-json-url, or --rss-url source"
        )
    now = _parse_cli_datetime(args.now) if args.now else normalize_to_kst(datetime.now().astimezone())
    report = collect_news_risk_events(
        news_json_paths=tuple(args.news_json),
        dart_json_paths=tuple(args.dart_json),
        rss_paths=tuple(args.rss),
        news_json_urls=tuple(args.news_json_url),
        dart_json_urls=tuple(args.dart_json_url),
        rss_urls=tuple(args.rss_url),
        now=now,
        allow_network_fetches=args.allow_network and args.run_network,
        timeout_seconds=args.timeout_seconds,
        source_max_age_minutes=args.source_max_age_minutes,
    )
    write_news_adapter_events(report, args.events_output)
    write_news_adapter_report(report, args.report_output)
    print("status=passed")
    print("mode=news-risk-event-adapter")
    print(f"source_count={report.source_count}")
    print(f"item_count={report.item_count}")
    print(f"event_count={report.event_count}")
    print(f"flags={','.join(report.flags) if report.flags else 'none'}")
    print(f"events={args.events_output}")
    print(f"report={args.report_output}")
    return 0


def run_build_field_universe_command(args: argparse.Namespace) -> int:
    target_date = datetime.strptime(args.target_date, "%Y-%m-%d").date()
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    if getattr(args, "reuse_standby_artifact", False):
        if not args.standby_artifact:
            raise ValueError("--reuse-standby-artifact requires --standby-artifact")
        payload = load_reusable_field_universe_artifact(
            args.standby_artifact,
            target_date=target_date,
            expected_prior_date=expected_prior_date,
            max_prior_data_lag_days=getattr(args, "max_prior_data_lag_days", None),
            as_of=normalize_to_kst(datetime.now().astimezone()),
            max_artifact_age_minutes=getattr(args, "max_standby_artifact_age_minutes", None),
        )
        write_reused_field_universe_artifact(payload, args.output)
        if args.kis_symbol_list_output:
            write_reused_kis_symbol_list(payload, args.kis_symbol_list_output)
        report = payload["report"]
        summary = payload["summary"]
        print("status=ready")
        print(f"mode={report['mode']}")
        print(f"universe_id={report['universe_id']}")
        print(f"target_date={report['target_date']}")
        print(f"included_count={summary['included_count']}")
        print(f"excluded_count={summary['excluded_count']}")
        print("loaded_bar_count=0")
        print(f"reused_standby_artifact={args.standby_artifact}")
        if args.kis_symbol_list_output:
            print(f"kis_symbol_list={args.kis_symbol_list_output}")
        print(f"report={args.output}")
        return 0
    bars = _load_field_universe_bars(args, target_date=target_date)
    report = build_prior_only_field_universe(
        bars,
        target_date=target_date,
        universe_id=args.universe_id,
        value_window=args.value_window,
        sma_window=args.sma_window,
        atr_window=args.atr_window,
        min_average_value=_decimal(args.min_average_value),
        min_atr_ratio=_decimal(args.min_atr_ratio),
        require_close_above_sma=not args.disable_close_above_sma,
        max_symbols=args.max_symbols,
        min_prior_trading_days=args.min_prior_trading_days,
        max_prior_data_lag_days=getattr(args, "max_prior_data_lag_days", None),
        expected_prior_date=expected_prior_date,
    )
    write_field_universe_report(report, args.output)
    if args.kis_symbol_list_output:
        write_kis_symbol_list(report, args.kis_symbol_list_output)

    summary = report.summary()
    print(f"status={'ready' if report.included_symbols else 'empty'}")
    print(f"mode={report.mode}")
    print(f"universe_id={report.universe_id}")
    print(f"target_date={report.target_date.isoformat()}")
    print(f"included_count={summary['included_count']}")
    print(f"excluded_count={summary['excluded_count']}")
    print(f"loaded_bar_count={len(bars)}")
    print(f"latest_prior_date={summary['latest_prior_date'] or 'none'}")
    print(f"source_fresh={summary['source_fresh']}")
    print(f"expected_prior_date={expected_prior_date.isoformat() if expected_prior_date else 'none'}")
    if args.kis_symbol_list_output:
        print(f"kis_symbol_list={args.kis_symbol_list_output}")
    print(f"report={args.output}")
    return 0 if report.included_symbols else 1


def run_build_daily_field_universe_command(args: argparse.Namespace) -> int:
    if not args.target_date:
        args.target_date = _next_weekday(date.today()).isoformat()
    return run_build_field_universe_command(args)


def _csv_acceptance_result(args: argparse.Namespace, summary: CsvScanSummary):
    criteria = CsvAcceptanceCriteria(
        min_success_rate=args.min_success_rate,
        max_error_count=args.max_error_count,
        max_duplicate_timestamp_count=args.max_duplicate_timestamps,
        max_gap_count=args.max_gap_count,
        max_missing_minutes_count=args.max_missing_minutes,
        max_gap_minutes=args.max_gap_minutes,
        max_zero_volume_count=args.max_zero_volume_count,
        min_symbol_count=args.min_symbols,
        min_period_count=args.min_periods,
    )
    return assess_csv_scan(summary, criteria)


def run_rehearse_large_dummy_command(args: argparse.Namespace) -> int:
    profile = get_large_dummy_profile(args.profile)
    if not args.dry_run and profile.market_bar_count > args.max_materialized_market_rows:
        raise ValueError(
            f"profile {profile.name!r} would materialize {profile.market_bar_count} market rows; "
            "use --dry-run for sizing evidence or raise --max-materialized-market-rows explicitly"
        )

    config = load_config(args.config)
    metadata = generate_symbol_metadata(profile)
    backtest_payload: dict[str, object] = {}
    inserted_market_rows = 0
    inserted_index_rows = 0
    inserted_metadata_rows = 0

    if not args.dry_run:
        with db.workflow_lock():
            if args.keep_db:
                db.apply_schema()
            else:
                db.reset_rehearsal_tables()
            inserted_metadata_rows = db.insert_symbol_metadata(metadata)
            inserted_market_rows = db.insert_bars(
                iter_large_dummy_market_bars(
                    profile,
                    include_quality_anomalies=args.include_quality_anomalies,
                )
            )
            inserted_index_rows = db.insert_index_bars(iter_large_dummy_index_bars(profile))
            backtest_bars: list[Bar] = []
            for item in metadata:
                backtest_bars.extend(db.fetch_bars(item.symbol))
        report, trades = run_backtest(backtest_bars, config=config.backtest)
        outputs = write_backtest_outputs(
            report=report,
            trades=trades,
            output_dir=args.output_dir / "backtest",
            symbols=[item.symbol for item in metadata],
            inserted_rows=inserted_market_rows,
            title="PROJECT_ZURINI phase-1.5 synthetic large-dummy rehearsal backtest",
        )
        backtest_payload = {
            "trade_count": report.trade_count,
            "gross_pnl": str(report.gross_pnl),
            "net_pnl": str(report.net_pnl),
            "max_drawdown": str(report.max_drawdown),
            "start_equity": str(report.start_equity),
            "end_equity": str(report.end_equity),
            "report": str(outputs["json"]),
        }

    summary = summarize_large_dummy_profile(
        profile,
        include_quality_anomalies=args.include_quality_anomalies,
        inserted_market_rows=inserted_market_rows,
        inserted_index_rows=inserted_index_rows,
        inserted_metadata_rows=inserted_metadata_rows,
        backtest=backtest_payload,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "rehearsal-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"profile={profile.name}")
    print(f"logical_months={profile.logical_months}")
    print(f"estimated_market_rows={profile.market_bar_count}")
    print(f"estimated_index_rows={profile.index_bar_count}")
    print(f"metadata_rows={len(metadata)}")
    print(f"inserted_market_rows={inserted_market_rows}")
    print(f"inserted_index_rows={inserted_index_rows}")
    print(f"report={summary_path}")
    return 0


def run_plan_a_dry_run_command(args: argparse.Namespace) -> int:
    trading_date = datetime.strptime(args.trading_date, "%Y-%m-%d").date()
    bars = _load_dry_run_bars(args)
    blacklist_snapshot = load_async_blacklist(args.blacklist) if args.blacklist else None
    _validate_index_trend_reports_for_simulation(
        args.index_trend_report,
        enabled=args.enable_index_trend_filter,
    )
    index_provider = _index_trend_provider_from_reports(
        args.index_trend_report,
        enabled=args.enable_index_trend_filter,
    )
    if bars:
        report = run_plan_a_historical_dry_run(
            bars,
            trading_date=trading_date,
            session_id=args.session_id,
            max_trading_days=args.max_trading_days,
            api_rate_limit_per_second=args.api_rate_limit_per_second,
            local_free_space_gb=_local_free_space_gb(args.local_free_space_gb, args.output),
            raw_burst_enabled=args.enable_raw_burst,
            blacklist_snapshot=blacklist_snapshot,
            index_trend_filter_enabled=args.enable_index_trend_filter,
            index_trend_provider=index_provider,
        )
    else:
        report = build_empty_plan_a_dry_run_report(
            trading_date=trading_date,
            session_id=args.session_id,
        )
    write_dry_run_report(report, args.output)
    persisted_events = None
    if args.persist_db:
        with db.workflow_lock():
            db.apply_schema()
            persisted_events = persist_dry_run_report(report)

    print("mode=no-order")
    print(f"order_hard_block={report.session.order_hard_block}")
    print(f"package={report.strategy_package.package_id}")
    print(f"virtual_orders={len(report.virtual_orders)}")
    print(f"capital_feasibility={len(report.capital_feasibility)}")
    if persisted_events is not None:
        print(f"db_ledger_events={persisted_events}")
    print(f"report={args.output}")
    return 0


def run_plan_a_dry_run_multi_command(args: argparse.Namespace) -> int:
    bars = _load_dry_run_bars(args, require_input=True)
    blacklist_snapshot = load_async_blacklist(args.blacklist) if args.blacklist else None
    _validate_index_trend_reports_for_simulation(
        args.index_trend_report,
        enabled=args.enable_index_trend_filter,
    )
    index_provider = _index_trend_provider_from_reports(
        args.index_trend_report,
        enabled=args.enable_index_trend_filter,
    )
    report = run_plan_a_multi_session_dry_run(
        bars,
        run_id=args.run_id,
        starting_seed=_decimal(args.starting_seed),
        max_trading_days=args.max_trading_days,
        api_rate_limit_per_second=args.api_rate_limit_per_second,
        local_free_space_gb=_local_free_space_gb(args.local_free_space_gb, args.output),
        raw_burst_enabled=args.enable_raw_burst,
        blacklist_snapshot=blacklist_snapshot,
        index_trend_filter_enabled=args.enable_index_trend_filter,
        index_trend_provider=index_provider,
    )
    write_multi_session_dry_run_report(report, args.output)
    persisted_events = None
    if args.persist_db:
        with db.workflow_lock():
            db.apply_schema()
            persisted_events = persist_multi_session_dry_run_report(report)

    summary = report.summary()
    print("mode=no-order")
    print(f"order_hard_block={summary['order_hard_block']}")
    print(f"run_id={report.run_id}")
    print(f"sessions={summary['session_count']}")
    print(f"trading_days={summary['trading_day_count']}")
    print(f"checkpoint_events={summary['checkpoint_event_count']}")
    print(f"api_rate_limit_breaches={summary['api_rate_limit_breach_count']}")
    print(f"storage_guardrail_breaches={summary['storage_guardrail_breach_count']}")
    if persisted_events is not None:
        print(f"db_ledger_events={persisted_events}")
    print(f"report={args.output}")
    return 0


def run_dry_run_resume_state_command(args: argparse.Namespace) -> int:
    as_of = _parse_cli_datetime(args.as_of) if args.as_of else normalize_to_kst(datetime.now().astimezone())
    target_trading_date = _parse_date(args.target_trading_date) if args.target_trading_date else None
    with db.workflow_lock():
        db.apply_schema()
        state = db.fetch_latest_dry_run_resume_state(
            session_id_prefix=args.session_id_prefix,
            as_of=as_of,
            target_trading_date=target_trading_date,
            max_session_age_minutes=args.max_session_age_minutes,
        )
    if state is None:
        raise ValueError("no dry-run ledger session is available for resume")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"status={state['status']}")
    print(f"mode={state['mode']}")
    print(f"session_id={state['session']['session_id']}")
    print(f"open_positions={len(state['open_positions'])}")
    print(f"checkpoint_events={len(state['checkpoint_events'])}")
    print(f"ready_for_broker_or_order_transmission={state['ready_for_broker_or_order_transmission']}")
    print(f"report={args.output}")
    return 0


def run_field_dry_run_monitor_command(args: argparse.Namespace) -> int:
    if len(args.market_data_report) > 1:
        raise ValueError("field monitoring accepts exactly one live --market-data-report artifact")
    if args.quote_depth_report:
        raise ValueError(
            "--quote-depth-report is diagnostic-only for field monitoring; "
            "use one kis-readonly-universe --include-quote-depth artifact as --market-data-report"
        )
    duplicate_live_reports = {path.resolve() for path in args.market_data_report} & {
        path.resolve() for path in args.api_report
    }
    if duplicate_live_reports:
        raise ValueError("do not pass the same KIS artifact as both --market-data-report and --api-report")
    scenarios = _field_monitor_scenarios_for_args(args)
    blacklist_snapshot = load_async_blacklist(args.blacklist) if args.blacklist else None
    stop_guard = _market_session_stop_guard(args)
    if stop_guard is not None:
        flags = tuple(
            dict.fromkeys(
                (
                    "market_session_closed",
                    *_api_report_flags(
                        [*args.api_report, *args.market_data_report],
                        quote_depth_reports=args.quote_depth_report,
                        max_age_seconds=args.market_data_max_age_seconds,
                        now=_parse_guard_now(args.now) if args.now else None,
                    ),
                    *_news_feed_flags(
                        blacklist_snapshot,
                        require_news_feed=args.require_news_feed,
                        now=_parse_guard_now(args.now) if args.now else None,
                    ),
                    *_index_trend_report_flags(
                        args.index_trend_report,
                        enabled=args.enable_index_trend_filter,
                        max_age_seconds=args.market_data_max_age_seconds,
                        now=_parse_guard_now(args.now) if args.now else None,
                    ),
                )
            )
        )
        review_day = _parse_date(stop_guard["session_date"])
        review_path = args.output_dir / "daily-review" / f"{review_day.isoformat()}.md"
        api_payloads = tuple(_api_report_payloads([*args.api_report, *args.market_data_report, *args.quote_depth_report, *args.index_trend_report]))
        payload = write_terminal_field_monitor_status(
            output=args.status_output,
            run_id=args.run_id,
            watch=args.watch,
            source=args.source,
            flags=flags,
            api_reports=api_payloads,
            scenarios=scenarios,
        )
        if not review_path.exists():
            status = build_field_monitor_status(
                run_id=args.run_id,
                bars=[],
                reports={},
                output_dir=args.output_dir,
                watch=args.watch,
                source=args.source,
                flags=flags,
                api_reports=api_payloads,
                scenarios=scenarios,
            )
            review_path = write_field_daily_review(status, args.output_dir, trading_day=review_day)
        print("mode=no-order")
        print(f"order_hard_block={payload['order_hard_block']}")
        print(f"ready_for_broker_or_order_transmission={payload['ready_for_broker_or_order_transmission']}")
        print(f"status={payload['status']}")
        print(f"scenarios={len(payload.get('scenarios', []))}")
        print(f"scenario_results={len(payload.get('scenario_results', []))}")
        print(f"flags={','.join(payload.get('flags', [])) if payload.get('flags') else 'none'}")
        print(f"status_report={args.status_output}")
        print(f"daily_review={review_path}")
        return 0
    input_flags = tuple(
        dict.fromkeys(
            (
                *_api_report_flags(
                    [*args.api_report, *args.market_data_report],
                    quote_depth_reports=args.quote_depth_report,
                    max_age_seconds=args.market_data_max_age_seconds,
                    now=_parse_guard_now(args.now) if args.now else None,
                ),
                *_news_feed_flags(
                    blacklist_snapshot,
                    require_news_feed=args.require_news_feed,
                    now=_parse_guard_now(args.now) if args.now else None,
                ),
                *_index_trend_report_flags(
                    args.index_trend_report,
                    enabled=args.enable_index_trend_filter,
                    max_age_seconds=args.market_data_max_age_seconds,
                    now=_parse_guard_now(args.now) if args.now else None,
                ),
            )
        )
    )
    api_payloads = tuple(_api_report_payloads([*args.api_report, *args.market_data_report, *args.quote_depth_report, *args.index_trend_report]))
    if _has_input_contract_degradation(input_flags):
        status = build_field_monitor_status(
            run_id=args.run_id,
            bars=[],
            reports={},
            output_dir=args.output_dir,
            watch=args.watch,
            source=args.source,
            flags=input_flags,
            api_reports=api_payloads,
            scenarios=scenarios,
        )
        write_field_monitor_status(status, args.status_output)
        review_path = write_field_daily_review(status, args.output_dir)
        print("mode=no-order")
        print(f"order_hard_block={status.order_hard_block}")
        print(f"ready_for_broker_or_order_transmission={status.ready_for_broker_or_order_transmission}")
        print(f"status={status.status}")
        print(f"scenarios={len(status.scenarios)}")
        print(f"scenario_results={len(status.scenario_results)}")
        print(f"flags={','.join(status.flags) if status.flags else 'none'}")
        print(f"status_report={args.status_output}")
        print(f"daily_review={review_path}")
        return 1

    market_bars = (
        _bars_from_market_data_reports(args.market_data_report, quote_depth_reports=args.quote_depth_report)
        if args.market_data_report
        else []
    )
    warmup_args = args
    if market_bars and not getattr(args, "symbol_filter", None):
        warmup_args = argparse.Namespace(
            **{
                **vars(args),
                "symbol_filter": list(dict.fromkeys(bar.symbol for bar in market_bars)),
            }
        )
    warmup_bars = _load_dry_run_bars(warmup_args, require_input=False)
    if market_bars:
        replay_bars = _bars_from_watchlist_history(
            args.output_dir,
            trading_day=max(bar.timestamp.date() for bar in market_bars),
        )
        bars = _combine_field_monitor_bars(
            warmup_bars=warmup_bars,
            replay_bars=replay_bars,
            market_bars=market_bars,
        )
    else:
        bars = warmup_bars
    blacklist_snapshot = load_async_blacklist(args.blacklist) if args.blacklist else None
    index_provider = _index_trend_provider_from_reports(
        args.index_trend_report,
        enabled=args.enable_index_trend_filter,
    )
    reports = {}
    for scenario in scenarios:
        if not bars:
            continue
        report = run_plan_a_multi_session_dry_run(
            bars,
            run_id=f"{args.run_id}-{scenario.scenario_id}",
            starting_seed=scenario.starting_seed,
            max_trading_days=args.max_trading_days,
            api_rate_limit_per_second=args.api_rate_limit_per_second,
            local_free_space_gb=_local_free_space_gb(args.local_free_space_gb, args.output_dir),
            raw_burst_enabled=args.enable_raw_burst,
            blacklist_snapshot=blacklist_snapshot,
            index_trend_filter_enabled=args.enable_index_trend_filter,
            index_trend_provider=index_provider,
        )
        scenario_path = args.output_dir / "scenarios" / f"{scenario.scenario_id}.json"
        write_multi_session_dry_run_report(report, scenario_path)
        if args.persist_db:
            with db.workflow_lock():
                db.apply_schema()
                persist_multi_session_dry_run_report(report)
        reports[scenario.scenario_id] = (report, scenario_path)

    status = build_field_monitor_status(
        run_id=args.run_id,
        bars=bars,
        reports=reports,
        output_dir=args.output_dir,
        watch=args.watch,
        source=args.source,
        flags=input_flags,
        api_reports=api_payloads,
        scenarios=scenarios,
    )
    write_field_monitor_status(status, args.status_output)
    review_path = write_field_daily_review(
        status,
        args.output_dir,
        trading_day=bars[-1].timestamp.date() if bars else None,
    )
    watchlist_paths: tuple[Path, Path] | None = None
    primary = reports.get("primary-current-seed-1m")
    if primary is not None and bars:
        watchlist_paths = write_watchlist_full_report(
            primary[0],
            args.output_dir,
            trading_day=bars[-1].timestamp.date(),
        )

    print("mode=no-order")
    print(f"order_hard_block={status.order_hard_block}")
    print(f"ready_for_broker_or_order_transmission={status.ready_for_broker_or_order_transmission}")
    print(f"status={status.status}")
    print(f"scenarios={len(status.scenarios)}")
    print(f"scenario_results={len(status.scenario_results)}")
    print(f"flags={','.join(status.flags) if status.flags else 'none'}")
    print(f"status_report={args.status_output}")
    print(f"daily_review={review_path}")
    if watchlist_paths is not None:
        print(f"watchlist_full={watchlist_paths[0]}")
        print(f"watchlist_summary={watchlist_paths[1]}")
    return 0


def _field_monitor_scenarios_for_args(args: argparse.Namespace):
    if getattr(args, "command", "") == "field-run":
        return build_primary_field_dry_run_scenarios()
    return build_default_field_dry_run_scenarios()


def run_field_run_command(args: argparse.Namespace) -> int:
    if args.run_network and not args.allow_network:
        raise ValueError("--run-network requires --allow-network")
    if args.run_network and args.endpoint_profile == "prod" and not args.confirm_prod_readonly:
        raise ValueError("--run-network --endpoint-profile prod requires --confirm-prod-readonly")
    if args.cycle_limit is not None and args.cycle_limit <= 0:
        raise ValueError("cycle-limit must be positive")
    if args.ai_report_interval_seconds <= 0:
        raise ValueError("ai-report-interval-seconds must be positive")
    if args.quote_degraded_retry_limit <= 0:
        raise ValueError("quote-degraded-retry-limit must be positive")
    if args.quote_degraded_backoff_seconds < 0:
        raise ValueError("quote-degraded-backoff-seconds must be non-negative")
    if args.cycle_limit is None and not args.enforce_market_session_stop:
        raise ValueError("continuous field-run requires --enforce-market-session-stop or a bounded --cycle-limit")

    prewarm_guard = _field_run_token_prewarm_guard(args)
    if prewarm_guard is not None:
        _write_field_run_control(
            args,
            cycle_count=0,
            status="waiting",
            quote_status="skipped",
            monitor_status=0,
            extra={
                "stop_guard": prewarm_guard,
                "auth_preflight": None,
                "universe_report": None,
                "requested_symbol_count": 0,
                "cycle_symbol_count": 0,
                "focused_symbols": False,
            },
        )
        if getattr(args, "now", None):
            print("mode=no-order")
            print("status=waiting")
            print("reason=token-prewarm-not-open")
            print(f"control_report={args.control_output}")
            return 0
        _wait_for_field_run_token_prewarm(args)

    auth_cooldown_path = Path(".omx/state/kis-auth-cooldown.json")
    token_cache = None
    auth_preflight: dict[str, object] | None = None
    if args.run_network:
        print("field_run_stage=auth_preflight_start", flush=True)
        token_cache, auth_result = prewarm_kis_token_cache(
            endpoint_profile=args.endpoint_profile,
            auth_cooldown_path=auth_cooldown_path,
            confirm_prod_readonly=args.confirm_prod_readonly,
        )
        auth_preflight = auth_result.as_dict()
        print(
            f"field_run_stage=auth_preflight_done status={auth_result.status} "
            f"read_call_count={auth_result.read_call_count} from_cache={auth_result.from_cache}",
            flush=True,
        )
        if auth_result.status != "passed" or token_cache is None:
            _write_field_run_control(
                args,
                cycle_count=0,
                status="failed",
                quote_status="skipped",
                monitor_status=1,
                extra={
                    "auth_preflight": auth_preflight,
                    "requested_symbol_count": 0,
                    "cycle_symbol_count": 0,
                    "focused_symbols": False,
                },
            )
            print("mode=no-order")
            print("status=failed")
            print("reason=kis-auth-preflight-failed")
            print(f"control_report={args.control_output}")
            return 1

    requested_symbols = tuple(args.symbol) + tuple(_read_symbol_lists(args.symbol_list))
    auto_universe_requested = _field_run_auto_universe_requested(args, requested_symbols)
    try:
        print("field_run_stage=universe_prepare_start", flush=True)
        universe_preparation = _prepare_field_run_universe(args, requested_symbols, token_cache=token_cache)
        print(
            f"field_run_stage=universe_prepare_done symbol_count={len(universe_preparation.symbols)}",
            flush=True,
        )
    except (OSError, ValueError) as exc:
        if not auto_universe_requested:
            raise
        _write_field_run_control(
            args,
            cycle_count=0,
            status="failed",
            quote_status="skipped",
            monitor_status=1,
            extra={
                "auth_preflight": auth_preflight,
                "universe_report": None,
                "universe_error": str(exc),
                "universe_selection_mode": "auto",
                "requested_symbol_count": 0,
                "cycle_symbol_count": 0,
                "focused_symbols": False,
            },
        )
        print("mode=no-order")
        print("status=failed")
        print("reason=field-run-universe-unavailable")
        print(f"control_report={args.control_output}")
        return 1
    universe_evidence = universe_preparation.evidence
    symbols = universe_preparation.symbols
    if not symbols:
        raise ValueError("field-run requires symbols from --symbol/--symbol-list, --universe-report, or --build-universe")
    cycle_count = 0
    consecutive_degraded_quote_cycles = 0
    last_monitor_status = 0
    while True:
        stop_guard = _market_session_stop_guard(args)
        if stop_guard is not None:
            if _field_run_should_wait_for_market_open(args, stop_guard):
                wait_seconds = _field_run_wait_seconds(stop_guard)
                _write_field_run_control(
                    args,
                    cycle_count=cycle_count,
                    status="waiting",
                    quote_status="skipped",
                    monitor_status=0,
                    extra={
                        "stop_guard": stop_guard,
                        "auth_preflight": auth_preflight,
                        "universe_report": universe_evidence,
                        "requested_symbol_count": len(symbols),
                        "cycle_symbol_count": 0,
                        "focused_symbols": False,
                        "wait_seconds": wait_seconds,
                    },
                )
                print("mode=no-order", flush=True)
                print("status=waiting", flush=True)
                print("reason=market-session-not-open", flush=True)
                print(f"wait_seconds={wait_seconds}", flush=True)
                print(f"control_report={args.control_output}", flush=True)
                time.sleep(wait_seconds)
                continue
            _write_field_run_control(
                args,
                cycle_count=cycle_count,
                status="stopped",
                quote_status="skipped",
                monitor_status=0,
                extra={
                    "stop_guard": stop_guard,
                    "auth_preflight": auth_preflight,
                    "universe_report": universe_evidence,
                    "requested_symbol_count": len(symbols),
                    "cycle_symbol_count": 0,
                    "focused_symbols": False,
                },
            )
            print("mode=no-order")
            print("status=stopped")
            print(f"reason={stop_guard.get('reason') or 'market-session-closed'}")
            print(f"cycles={cycle_count}")
            print(f"control_report={args.control_output}")
            return 0

        cycle_symbols = _field_run_cycle_symbols(args, symbols)
        focused_symbols = len(cycle_symbols) < len(symbols)
        print(
            f"field_run_stage=cycle_start cycle={cycle_count + 1} "
            f"requested_symbol_count={len(symbols)} cycle_symbol_count={len(cycle_symbols)} "
            f"focused_symbols={str(focused_symbols).lower()}",
            flush=True,
        )
        print(
            f"field_run_stage=quote_depth_start cycle={cycle_count + 1} "
            f"run_network={str(args.run_network).lower()} include_quote_depth={str(not args.skip_quote_depth).lower()} "
            f"quote_report={args.quote_report}",
            flush=True,
        )
        quote_payload = (
            build_kis_read_only_universe(
                symbols=cycle_symbols,
                quote_interval_seconds=_kis_quote_interval(args),
                endpoint_profile=args.endpoint_profile,
                auth_cooldown_path=auth_cooldown_path,
                confirm_prod_readonly=args.confirm_prod_readonly,
                include_quote_depth=not args.skip_quote_depth,
                token_cache=token_cache,
            ).as_dict()
            if args.run_network
            else build_kis_read_only_universe_plan(symbols=cycle_symbols)
        )
        quote_payload = _field_run_quote_payload_with_operational_exclusions(
            quote_payload,
            max_age_seconds=args.market_data_max_age_seconds,
            now=_parse_guard_now(args.now) if args.now else None,
        )
        args.quote_report.parent.mkdir(parents=True, exist_ok=True)
        args.quote_report.write_text(json.dumps(quote_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        index_reports = list(args.index_trend_report)
        quote_status = str(quote_payload.get("status") or "unknown")
        degraded_symbols = _field_run_degraded_symbols_from_quote_payload(quote_payload)
        print(
            f"field_run_stage=quote_depth_done cycle={cycle_count + 1} status={quote_status} "
            f"degraded_symbol_count={len(degraded_symbols)} read_call_count={quote_payload.get('read_call_count', 0)} "
            f"quote_report={args.quote_report}",
            flush=True,
        )
        if args.run_network and quote_status != "passed":
            consecutive_degraded_quote_cycles += 1
            cycle_count += 1
            retry_exhausted = consecutive_degraded_quote_cycles >= args.quote_degraded_retry_limit
            _write_field_run_degraded_quote_status(args, quote_payload)
            _write_field_run_control(
                args,
                cycle_count=cycle_count,
                status="failed" if retry_exhausted else "running",
                quote_status=quote_status,
                monitor_status="skipped",
                extra={
                    "quote_report": str(args.quote_report),
                    "status_report": str(args.status_output),
                    "auth_preflight": auth_preflight,
                    "universe_report": universe_evidence,
                    "requested_symbol_count": len(symbols),
                    "cycle_symbol_count": len(cycle_symbols),
                    "focused_symbols": focused_symbols,
                    "degraded_symbols": degraded_symbols,
                    "consecutive_degraded_quote_cycles": consecutive_degraded_quote_cycles,
                    "quote_degraded_retry_limit": args.quote_degraded_retry_limit,
                    "input_contract_action": (
                        "fail_closed_persistent_degraded_quote"
                        if retry_exhausted
                        else "skipped_monitor_for_degraded_quote"
                    ),
                },
            )
            print(
                f"field_run_stage=monitor_skipped cycle={cycle_count} reason=degraded_quote "
                f"quote_status={quote_status} degraded_symbol_count={len(degraded_symbols)} "
                f"control_report={args.control_output}",
                flush=True,
            )
            if retry_exhausted:
                print(
                    f"field_run_stage=quote_degraded_retry_exhausted cycle={cycle_count} "
                    f"retry_limit={args.quote_degraded_retry_limit} control_report={args.control_output}",
                    flush=True,
                )
                print("mode=no-order")
                print("status=failed")
                print("reason=persistent-degraded-quote")
                print(f"field_run_cycles={cycle_count}")
                print(f"control_report={args.control_output}")
                return 1
            if args.cycle_limit is not None and cycle_count >= args.cycle_limit:
                _write_field_run_control(
                    args,
                    cycle_count=cycle_count,
                    status="failed",
                    quote_status=quote_status,
                    monitor_status="skipped",
                    extra={
                        "quote_report": str(args.quote_report),
                        "status_report": str(args.status_output),
                        "auth_preflight": auth_preflight,
                        "universe_report": universe_evidence,
                        "requested_symbol_count": len(symbols),
                        "cycle_symbol_count": len(cycle_symbols),
                        "focused_symbols": focused_symbols,
                        "degraded_symbols": degraded_symbols,
                        "consecutive_degraded_quote_cycles": consecutive_degraded_quote_cycles,
                        "quote_degraded_retry_limit": args.quote_degraded_retry_limit,
                        "input_contract_action": "fail_closed_degraded_quote_cycle_limit",
                    },
                )
                print(
                    f"field_run_stage=degraded_quote_cycle_limit_reached cycle={cycle_count} "
                    f"control_report={args.control_output}",
                    flush=True,
                )
                print(f"field_run_cycles={cycle_count}")
                print(f"control_report={args.control_output}")
                return 1
            _field_run_degraded_quote_backoff(args)
            continue

        if args.enable_index_trend_filter:
            print(
                f"field_run_stage=index_poll_start cycle={cycle_count + 1} "
                f"run_network={str(args.run_network).lower()} index_report={args.index_report}",
                flush=True,
            )
            index_payload = (
                build_kis_index_poll_snapshot(
                    poll_interval_seconds=args.index_poll_interval_seconds,
                    endpoint_profile=args.endpoint_profile,
                    auth_cooldown_path=auth_cooldown_path,
                    confirm_prod_readonly=args.confirm_prod_readonly,
                    token_cache=token_cache,
                ).as_dict()
                if args.run_network
                else build_kis_index_poll_plan(poll_interval_seconds=args.index_poll_interval_seconds)
            )
            index_payload = _index_payload_with_accumulated_bars(
                [*args.index_trend_report, args.index_report],
                index_payload,
            )
            args.index_report.parent.mkdir(parents=True, exist_ok=True)
            args.index_report.write_text(json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            index_reports.append(args.index_report)
            if args.persist_db and str(index_payload.get("status") or "") == "passed":
                with db.workflow_lock():
                    db.apply_schema()
                    db.insert_index_ticks(
                        index_samples_from_report(index_payload),
                        poll_interval_seconds=args.index_poll_interval_seconds,
                        source_run_id=str(getattr(args, "run_id", None) or "field-run"),
                    )
                    db.insert_index_bars(index_bars_from_report(index_payload))
            print(
                f"field_run_stage=index_poll_done cycle={cycle_count + 1} "
                f"status={index_payload.get('status', 'unknown')} "
                f"read_call_count={index_payload.get('read_call_count', 0)} index_report={args.index_report}",
                flush=True,
            )

        consecutive_degraded_quote_cycles = 0
        print(
            f"field_run_stage=monitor_start cycle={cycle_count + 1} "
            f"market_data_report={args.quote_report} status_output={args.status_output}",
            flush=True,
        )
        monitor_args = argparse.Namespace(
            command="field-run",
            run_id=args.run_id,
            path=list(universe_preparation.path),
            path_list=list(universe_preparation.path_list),
            root=list(universe_preparation.root),
            source=args.source,
            limit_files=args.limit_files,
            start_date=args.start_date,
            end_date=args.end_date,
            max_trading_days=args.max_trading_days,
            api_rate_limit_per_second=args.api_rate_limit_per_second,
            local_free_space_gb=args.local_free_space_gb,
            enable_raw_burst=args.enable_raw_burst,
            watch=True,
            market_data_report=[args.quote_report],
            market_data_max_age_seconds=args.market_data_max_age_seconds,
            quote_depth_report=[],
            api_report=[],
            blacklist=args.blacklist,
            require_news_feed=args.require_news_feed,
            enable_index_trend_filter=args.enable_index_trend_filter,
            index_trend_report=index_reports,
            persist_db=args.persist_db,
            enforce_market_session_stop=args.enforce_market_session_stop,
            market_session_date=args.market_session_date,
            market_session_stop_time=args.market_session_stop_time,
            market_session_start_time=args.market_session_start_time,
            now=args.now,
            output_dir=args.output_dir,
            status_output=args.status_output,
        )
        last_monitor_status = run_field_dry_run_monitor_command(monitor_args)
        cycle_count += 1
        print(
            f"field_run_stage=monitor_done cycle={cycle_count} status={last_monitor_status} "
            f"status_output={args.status_output}",
            flush=True,
        )
        _write_field_run_control(
            args,
            cycle_count=cycle_count,
            status="running" if last_monitor_status == 0 else "failed",
            quote_status=quote_status,
            monitor_status=last_monitor_status,
            extra={
                "quote_report": str(args.quote_report),
                "status_report": str(args.status_output),
                "auth_preflight": auth_preflight,
                "universe_report": universe_evidence,
                "requested_symbol_count": len(symbols),
                "cycle_symbol_count": len(cycle_symbols),
                "focused_symbols": focused_symbols,
                "degraded_symbols": degraded_symbols,
            },
        )
        if last_monitor_status != 0:
            print("mode=no-order")
            print("status=failed")
            print("reason=field-run-monitor-failed")
            print(f"monitor_status={last_monitor_status}")
            print(f"cycles={cycle_count}")
            print(f"control_report={args.control_output}")
            return last_monitor_status
        if args.cycle_limit is not None and cycle_count >= args.cycle_limit:
            print(
                f"field_run_stage=cycle_limit_reached cycle={cycle_count} "
                f"control_report={args.control_output}",
                flush=True,
            )
            print(f"field_run_cycles={cycle_count}")
            print(f"control_report={args.control_output}")
            return 0


def _field_run_token_prewarm_guard(args: argparse.Namespace) -> dict[str, str] | None:
    if not getattr(args, "run_network", False):
        return None
    if getattr(args, "cycle_limit", None) is not None:
        return None
    if not getattr(args, "enforce_market_session_stop", False):
        return None
    now = _parse_guard_now(getattr(args, "now", None))
    if getattr(args, "market_session_date", None):
        session_date = _parse_date(args.market_session_date)
    else:
        session_date = now.date()
    prewarm_time = _parse_hhmm("08:30")
    prewarm_at = datetime.combine(session_date, prewarm_time, tzinfo=KST)
    if now >= prewarm_at:
        return None
    return {
        "reason": "token-prewarm-not-open",
        "session_date": session_date.isoformat(),
        "prewarm_time": prewarm_time.strftime("%H:%M"),
        "prewarm_at": prewarm_at.isoformat(),
        "checked_at": now.isoformat(),
    }


def _wait_for_field_run_token_prewarm(args: argparse.Namespace) -> None:
    if getattr(args, "now", None):
        return
    while True:
        prewarm_guard = _field_run_token_prewarm_guard(args)
        if prewarm_guard is None:
            return
        prewarm_at = datetime.fromisoformat(prewarm_guard["prewarm_at"])
        _field_run_sleep_until(prewarm_at, stage="token_prewarm_wait_until")


def _field_run_should_wait_for_market_open(args: argparse.Namespace, stop_guard: dict[str, str]) -> bool:
    return (
        stop_guard.get("reason") == "market-session-not-open"
        and getattr(args, "now", None) is None
        and getattr(args, "cycle_limit", None) is None
    )


def _field_run_sleep_until(target: datetime, *, stage: str) -> None:
    while True:
        now = normalize_to_kst(datetime.now().astimezone())
        remaining = (normalize_to_kst(target) - now).total_seconds()
        if remaining <= 0:
            return
        wait_seconds = max(1, math.ceil(remaining))
        print(
            f"field_run_stage={stage} target={normalize_to_kst(target).isoformat()} wait_seconds={wait_seconds}",
            flush=True,
        )
        time.sleep(wait_seconds)


def _field_run_wait_seconds(stop_guard: dict[str, str], *, now: datetime | None = None) -> int:
    start_at_raw = stop_guard.get("start_at")
    if start_at_raw:
        try:
            start_at = datetime.fromisoformat(start_at_raw)
            reference_now = normalize_to_kst(now or datetime.now().astimezone())
            open_wake_at = normalize_to_kst(start_at) - timedelta(seconds=30)
            target = open_wake_at if reference_now < open_wake_at else normalize_to_kst(start_at)
            remaining = math.ceil((target - reference_now).total_seconds())
            return max(1, remaining)
        except ValueError:
            pass
    return 30


def _field_run_degraded_quote_backoff(args: argparse.Namespace) -> None:
    seconds = float(args.quote_degraded_backoff_seconds)
    if seconds <= 0:
        return
    if getattr(args, "now", None):
        return
    print(f"field_run_stage=quote_degraded_backoff seconds={seconds:g}", flush=True)
    time.sleep(seconds)


def _write_field_run_control(
    args: argparse.Namespace,
    *,
    cycle_count: int,
    status: str,
    quote_status: str,
    monitor_status: int,
    extra: dict[str, object] | None = None,
) -> None:
    payload = {
        "run_id": args.run_id,
        "mode": "no-order",
        "status": status,
        "cycle_count": cycle_count,
        "quote_status": quote_status,
        "monitor_exit_status": monitor_status,
        "order_hard_block": True,
        "ready_for_broker_or_order_transmission": False,
        "intraday_monitor_module": {
            "cadence": "continuous",
            "post_cycle_sleep_seconds": 0,
            "pacing": "KIS quote/depth collection duration and API throttle only",
        },
        "ai_watch_mode": {
            "cadence": "reporting-only",
            "report_interval_seconds": args.ai_report_interval_seconds,
            "does_not_throttle_intraday_monitor": True,
        },
        "swing_lock_step": {
            "candidate_preselection_time": "15:10",
            "decision_basis": "first accepted snapshot at or after 15:15 for selected swing candidates",
        },
        "extra": extra or {},
    }
    args.control_output.parent.mkdir(parents=True, exist_ok=True)
    args.control_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _field_run_degraded_symbols_from_quote_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    degraded: list[dict[str, object]] = []
    for member in payload.get("members", []):
        if not isinstance(member, dict):
            continue
        symbol = str(member.get("symbol") or "")
        if not symbol:
            continue
        flags = [str(flag) for flag in member.get("field_data_flags", []) if flag]
        included = bool(member.get("included"))
        reason = str(member.get("reason") or "")
        if included and not flags:
            continue
        degraded.append(
            {
                "symbol": symbol,
                "included": included,
                "reason": reason,
                "field_data_flags": flags,
                "price_observed_at": str(member.get("price_observed_at") or ""),
                "depth_observed_at": str(member.get("depth_observed_at") or ""),
                "paired_snapshot_gap_seconds": str(member.get("paired_snapshot_gap_seconds") or ""),
            }
        )
    return degraded


def _field_run_quote_payload_with_operational_exclusions(
    payload: dict[str, object],
    *,
    max_age_seconds: int | None,
    now: datetime | None,
) -> dict[str, object]:
    if payload.get("status") != "degraded":
        return payload
    budget_evidence = payload.get("budget_evidence")
    if isinstance(budget_evidence, dict) and budget_evidence.get("within_budget") is False:
        return payload
    api_flags = [str(flag) for flag in payload.get("api_flags", []) if flag]
    allowed_top_level_flags = {"bid_ask_placeholder"}
    if any(flag not in allowed_top_level_flags for flag in api_flags):
        return payload
    members = payload.get("members")
    if not isinstance(members, list):
        return payload
    excluded_members: list[dict[str, object]] = []
    kept_members: list[dict[str, object]] = []
    member_degradation_flags: set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            kept_members.append(member)
            continue
        flags = [str(flag) for flag in member.get("field_data_flags", []) if flag]
        member_degradation_flags.update(flags)
        if (
            bool(member.get("included"))
            and flags == ["bid_ask_placeholder"]
            and _field_run_placeholder_exclusion_contract_valid(
                member,
                max_age_seconds=max_age_seconds,
                now=now,
            )
        ):
            excluded_members.append(member)
        else:
            kept_members.append(member)
    if any(flag != "bid_ask_placeholder" for flag in member_degradation_flags):
        return payload
    if not excluded_members:
        return payload
    clean_included = [
        member
        for member in kept_members
        if isinstance(member, dict) and member.get("included") and not member.get("field_data_flags")
    ]
    if not clean_included:
        return payload
    transformed = dict(payload)
    transformed["status"] = "passed"
    transformed["api_flags"] = []
    transformed["members"] = kept_members
    transformed["included_symbols"] = [
        str(member.get("symbol") or "")
        for member in clean_included
        if str(member.get("symbol") or "")
    ]
    existing_excluded = list(payload.get("excluded_symbols", []) or [])
    quote_depth_excluded = [
        {
            "symbol": str(member.get("symbol") or ""),
            "reason": "bid_ask_placeholder",
            "price_observed_at": str(member.get("price_observed_at") or ""),
            "depth_observed_at": str(member.get("depth_observed_at") or ""),
            "paired_snapshot_gap_seconds": str(member.get("paired_snapshot_gap_seconds") or ""),
        }
        for member in excluded_members
        if str(member.get("symbol") or "")
    ]
    transformed["excluded_symbols"] = [
        *existing_excluded,
        *[
            [item["symbol"], "quote depth placeholder excluded from current no-order monitor cycle"]
            for item in quote_depth_excluded
        ],
    ]
    transformed["quote_depth_excluded_symbols"] = quote_depth_excluded
    transformed["input_contract_action"] = "excluded_bid_ask_placeholder_symbols"
    return transformed


def _field_run_placeholder_exclusion_contract_valid(
    member: dict[str, object],
    *,
    max_age_seconds: int | None,
    now: datetime | None,
) -> bool:
    observed_at = str(member.get("observed_at") or member.get("timestamp") or "")
    price_observed_at = str(member.get("price_observed_at") or "")
    depth_observed_at = str(member.get("depth_observed_at") or "")
    gap_value = str(member.get("paired_snapshot_gap_seconds") or "")
    if not observed_at or not price_observed_at or not depth_observed_at or not gap_value:
        return False
    try:
        parsed_observed_at = _parse_market_timestamp(observed_at)
        parsed_price_at = _parse_market_timestamp(price_observed_at)
        parsed_depth_at = _parse_market_timestamp(depth_observed_at)
        reported_gap = float(gap_value)
    except (TypeError, ValueError):
        return False
    if max_age_seconds is not None:
        reference_now = normalize_to_kst(now or datetime.now().astimezone())
        age_seconds = (reference_now - parsed_observed_at).total_seconds()
        if age_seconds < -60 or age_seconds > max_age_seconds:
            return False
    computed_gap = abs((parsed_depth_at - parsed_price_at).total_seconds())
    return not (reported_gap > 5.0 or computed_gap > 5.0 or abs(reported_gap - computed_gap) > 1.0)


def _write_field_run_degraded_quote_status(args: argparse.Namespace, quote_payload: dict[str, object]) -> None:
    flags = tuple(
        dict.fromkeys(
            _api_report_flags(
                [args.quote_report],
                max_age_seconds=args.market_data_max_age_seconds,
                now=_parse_guard_now(args.now) if args.now else None,
            )
            if args.quote_report.exists()
            else tuple(str(flag) for flag in quote_payload.get("api_flags", []))
        )
    )
    status = build_field_monitor_status(
        run_id=args.run_id,
        bars=[],
        reports={},
        output_dir=args.output_dir,
        watch=True,
        source=args.source,
        flags=flags,
        api_reports=(quote_payload,),
        scenarios=build_primary_field_dry_run_scenarios(),
    )
    write_field_monitor_status(status, args.status_output)


def _prepare_field_run_universe(
    args: argparse.Namespace,
    requested_symbols: tuple[str, ...],
    *,
    token_cache: KisTokenCache | None = None,
) -> FieldRunUniversePreparation:
    if args.build_universe and args.universe_report:
        raise ValueError("field-run accepts either --build-universe or --universe-report, not both")
    if args.build_universe:
        payload = _build_field_run_universe_report(args)
        symbols = _field_run_symbols_from_universe_payload(payload)
        if requested_symbols and tuple(_normalize_kis_symbol(symbol) for symbol in requested_symbols) != symbols:
            raise ValueError("field-run built universe kis_symbols must exactly match requested symbols when symbols are provided")
        return _field_run_universe_preparation(
            evidence=_field_run_universe_evidence(args.universe_output, args=args, payload=payload),
            symbols=symbols,
            args=args,
        )
    if args.universe_report:
        payload = _validate_field_run_universe_report(
            args.universe_report,
            args=args,
            symbols=requested_symbols or None,
        )
        return _field_run_universe_preparation(
            evidence=_field_run_universe_evidence(args.universe_report, args=args, payload=payload),
            symbols=requested_symbols or _field_run_symbols_from_universe_payload(payload),
            args=args,
        )
    if _field_run_auto_universe_requested(args, requested_symbols):
        return _prepare_auto_field_run_universe(args, token_cache=token_cache)
    return _field_run_universe_preparation(evidence=None, symbols=requested_symbols, args=args)


def _field_run_universe_preparation(
    *,
    evidence: dict[str, object] | None,
    symbols: tuple[str, ...],
    args: argparse.Namespace,
) -> FieldRunUniversePreparation:
    return FieldRunUniversePreparation(
        evidence=evidence,
        symbols=symbols,
        path=tuple(args.path),
        path_list=tuple(args.path_list),
        root=tuple(args.root),
    )


def _field_run_auto_universe_requested(args: argparse.Namespace, requested_symbols: tuple[str, ...]) -> bool:
    return not requested_symbols and not args.build_universe and not args.universe_report


def _prepare_auto_field_run_universe(
    args: argparse.Namespace,
    *,
    token_cache: KisTokenCache | None = None,
) -> FieldRunUniversePreparation:
    target_date = _field_run_target_date(args)
    universe_path = _field_run_auto_universe_path(args, target_date)
    print(f"field_run_stage=auto_universe_start target_date={target_date.isoformat()} path={universe_path}", flush=True)
    reuse_error: str | None = None
    auto_args = argparse.Namespace(**vars(args))
    auto_args.universe_output = universe_path
    explicit_source_requested = bool(auto_args.path or auto_args.path_list or auto_args.root)
    expected_prior_date = _resolve_field_run_expected_prior_date(
        auto_args,
        target_date=target_date,
        token_cache=token_cache,
    )
    if expected_prior_date is not None:
        auto_args.expected_prior_date = expected_prior_date.isoformat()
    source_acceptance_error = _field_run_daily_source_acceptance_error(
        target_date,
        expected_prior_date=expected_prior_date,
    )

    if universe_path.exists():
        try:
            payload = _validate_field_run_universe_report(universe_path, args=auto_args, symbols=None)
            if source_acceptance_error:
                raise ValueError(source_acceptance_error)
            if _field_run_daily_source_newer_than_universe(universe_path):
                raise ValueError("field-run daily source is newer than reusable universe artifact")
            universe_symbols = _field_run_symbols_from_universe_payload(payload)
            evidence = _field_run_universe_evidence(universe_path, args=auto_args, payload=payload)
            evidence["selection_mode"] = "auto"
            evidence["action"] = "reused"
            _attach_reused_universe_warmup_source(
                auto_args,
                target_date=target_date,
                required_symbols=universe_symbols,
                evidence=evidence,
            )
            return _field_run_universe_preparation(
                evidence=evidence,
                symbols=universe_symbols,
                args=auto_args,
            )
        except ValueError as exc:
            reuse_error = str(exc)
            if not explicit_source_requested:
                auto_args.path = []
                auto_args.path_list = []
                auto_args.root = []
            print(f"field_run_stage=auto_universe_reuse_rejected reason={reuse_error}", flush=True)

    collected_source = False
    if not (auto_args.path or auto_args.path_list or auto_args.root):
        default_path_list = _field_run_default_prior_path_list(target_date)
        if default_path_list.exists() and not source_acceptance_error:
            auto_args.path_list = [default_path_list]
            print(f"field_run_stage=auto_universe_source_reuse path_list={default_path_list}", flush=True)
        elif args.run_network:
            print("field_run_stage=auto_universe_source_collect_start", flush=True)
            auto_args.path_list = [
                _collect_auto_field_run_daily_source(auto_args, target_date=target_date, token_cache=token_cache)
            ]
            collected_source = True
            print(f"field_run_stage=auto_universe_source_collect_done path_list={auto_args.path_list[0]}", flush=True)

    if not (auto_args.path or auto_args.path_list or auto_args.root):
        reason = (
            f"field-run auto universe found no valid current universe artifact at {universe_path} "
            f"and no warm-up CSV source for {target_date.isoformat()}"
        )
        if reuse_error:
            reason += f"; existing artifact rejected: {reuse_error}"
        raise ValueError(reason)

    source_error: str | None = None
    try:
        print("field_run_stage=auto_universe_build_start", flush=True)
        payload = _build_field_run_universe_report(auto_args)
    except (OSError, ValueError) as exc:
        source_error = str(exc)
        if not args.run_network or collected_source:
            raise
        auto_args.path = []
        auto_args.root = []
        auto_args.path_list = [
            _collect_auto_field_run_daily_source(
                auto_args,
                target_date=target_date,
                refresh_stock_master=True,
                token_cache=token_cache,
            )
        ]
        collected_source = True
        print("field_run_stage=auto_universe_recollect_done", flush=True)
        print("field_run_stage=auto_universe_build_retry_start", flush=True)
        payload = _build_field_run_universe_report(auto_args)
    evidence = _field_run_universe_evidence(universe_path, args=auto_args, payload=payload)
    evidence["selection_mode"] = "auto"
    evidence["action"] = "built"
    evidence["source_path_list"] = [str(path) for path in auto_args.path_list]
    if collected_source:
        evidence["source_action"] = "collected"
    if source_error:
        evidence["rejected_stored_source_error"] = source_error
    return _field_run_universe_preparation(
        evidence=evidence,
        symbols=_field_run_symbols_from_universe_payload(payload),
        args=auto_args,
    )


def _field_run_auto_universe_path(args: argparse.Namespace, target_date: date) -> Path:
    default_path = Path("reports/dry-run/field-universe.json")
    if args.universe_output == default_path:
        return Path("reports/dry-run") / f"field-universe-{target_date.isoformat()}.json"
    return args.universe_output


def _field_run_default_prior_path_list(target_date: date) -> Path:
    return Path("reports/dry-run") / f"accepted-prior-warmup-paths-{target_date.isoformat()}.txt"


def _attach_reused_universe_warmup_source(
    args: argparse.Namespace,
    *,
    target_date: date,
    required_symbols: tuple[str, ...],
    evidence: dict[str, object],
) -> None:
    if args.path or args.path_list or args.root:
        selectors = list(args.path or []) + list(args.path_list or []) + list(args.root or [])
        _validate_field_run_warmup_sources(args, target_date=target_date, required_symbols=required_symbols)
        evidence["source_path_list"] = [str(path) for path in selectors]
        evidence["source_action"] = "explicit"
        return
    default_path_list = _field_run_default_prior_path_list(target_date)
    if not default_path_list.exists():
        raise ValueError(
            "field-run reusable universe requires accepted warm-up path-list "
            f"for {target_date.isoformat()}: {default_path_list}"
        )
    if not read_path_list(default_path_list):
        raise ValueError(
            "field-run reusable universe warm-up path-list is empty "
            f"for {target_date.isoformat()}: {default_path_list}"
        )
    args.path_list = [default_path_list]
    _validate_field_run_warmup_sources(args, target_date=target_date, required_symbols=required_symbols)
    evidence["source_path_list"] = [str(default_path_list)]
    evidence["source_action"] = "reused"


def _validate_field_run_warmup_sources(
    args: argparse.Namespace,
    *,
    target_date: date,
    required_symbols: tuple[str, ...],
) -> None:
    required_symbol_set = {_normalize_kis_symbol(item) for item in required_symbols if item}
    paths = _field_universe_csv_paths(
        list(args.path or []),
        list(args.root or []),
        list(args.path_list or []),
        target_date=target_date,
        latest_months=getattr(args, "latest_months", None),
    )
    if required_symbol_set:
        paths = tuple(
            path
            for path in paths
            if (_symbol_from_kis_daily_bar_path(path) or _normalize_kis_symbol(path.stem)) in required_symbol_set
        )
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    bars = load_prior_daily_bars_from_minute_csvs(
        paths,
        target_date=target_date,
        source=args.source,
        end_date=expected_prior_date,
    )
    if not bars:
        raise ValueError("field-run reusable universe warm-up source produced no prior bars")
    dates_by_symbol: dict[str, set[date]] = {}
    for bar in bars:
        trading_date = _field_run_bar_date(bar.timestamp)
        if trading_date >= target_date:
            continue
        dates_by_symbol.setdefault(_normalize_kis_symbol(bar.symbol), set()).add(trading_date)
    if not dates_by_symbol:
        raise ValueError("field-run reusable universe warm-up source produced no prior trading dates")
    missing_symbols = sorted(
        symbol
        for symbol in required_symbol_set
        if symbol not in dates_by_symbol
    )
    if missing_symbols:
        raise ValueError(
            "field-run reusable universe warm-up source is missing universe symbols; "
            f"symbols={','.join(missing_symbols)}"
        )
    for symbol, trading_dates in sorted(dates_by_symbol.items()):
        if required_symbol_set and symbol not in required_symbol_set:
            continue
        if len(trading_dates) < args.min_prior_trading_days:
            raise ValueError(
                "field-run reusable universe warm-up source has insufficient prior trading days; "
                f"symbol={symbol}; count={len(trading_dates)}; required={args.min_prior_trading_days}"
            )
        if expected_prior_date is not None and max(trading_dates) != expected_prior_date:
            raise ValueError(
                "field-run reusable universe warm-up source latest prior date mismatch; "
                f"symbol={symbol}; latest={max(trading_dates).isoformat()}; "
                f"expected={expected_prior_date.isoformat()}"
            )


def _field_run_bar_date(timestamp: datetime) -> date:
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(KST).date()


def _field_run_daily_source_acceptance_error(target_date: date, *, expected_prior_date: date | None) -> str | None:
    report_path = Path("reports/dry-run/kis-daily-bars.json")
    if not report_path.exists():
        return None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return f"field-run daily source acceptance report is unreadable: {exc}"
    if payload.get("status") != "passed" or payload.get("operational_acceptance") != "accepted":
        return (
            "field-run daily source is not operationally accepted; "
            f"status={payload.get('status')!r}; operational_acceptance={payload.get('operational_acceptance')!r}"
        )
    report_end_date = payload.get("end_date")
    if isinstance(report_end_date, str) and expected_prior_date is not None and report_end_date != expected_prior_date.isoformat():
        return (
            "field-run daily source acceptance report is for the wrong prior date; "
            f"end_date={report_end_date!r}; expected_prior_date={expected_prior_date.isoformat()!r}"
        )
    return None


def _field_run_daily_source_newer_than_universe(universe_path: Path) -> bool:
    try:
        universe_payload = json.loads(universe_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    universe_report = universe_payload.get("report")
    if not isinstance(universe_report, dict):
        return False
    universe_latest_raw = universe_report.get("latest_prior_date")
    if not isinstance(universe_latest_raw, str) or not universe_latest_raw:
        return False
    try:
        universe_latest = date.fromisoformat(universe_latest_raw)
    except ValueError:
        return False

    daily_report = Path("reports/dry-run/kis-daily-bars.json")
    if not daily_report.exists():
        return False
    try:
        daily_payload = json.loads(daily_report.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    if daily_payload.get("status") != "passed" or daily_payload.get("operational_acceptance") != "accepted":
        return False
    daily_end_raw = daily_payload.get("end_date")
    if not isinstance(daily_end_raw, str) or not daily_end_raw:
        return False
    try:
        daily_end = date.fromisoformat(daily_end_raw)
    except ValueError:
        return False
    return daily_end > universe_latest


def _date_from_field_universe_path(path: Path) -> str | None:
    stem = path.stem
    prefix = "field-universe-"
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return None


def _field_run_holiday_calendar_report_path(target_date: date) -> Path:
    return Path("reports/dry-run") / f"kis-holiday-calendar-{target_date.isoformat()}.json"


def _resolve_field_run_expected_prior_date(
    args: argparse.Namespace,
    *,
    target_date: date,
    token_cache: KisTokenCache | None = None,
) -> date | None:
    explicit = getattr(args, "expected_prior_date", None)
    if explicit:
        return _parse_date(str(explicit))
    if not getattr(args, "run_network", False) or token_cache is None or not hasattr(token_cache, "get_token"):
        return _field_universe_expected_prior_date(args, target_date)
    report_path = _field_run_holiday_calendar_report_path(target_date)
    if report_path.exists():
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            if payload.get("status") == "passed" and payload.get("target_date") == target_date.isoformat():
                expected_prior_date = payload.get("expected_prior_date")
                if isinstance(expected_prior_date, str) and expected_prior_date:
                    return date.fromisoformat(expected_prior_date)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    result = build_kis_holiday_calendar(
        target_date=target_date,
        endpoint_profile=args.endpoint_profile,
        auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
        confirm_prod_readonly=args.confirm_prod_readonly,
        token_cache=token_cache,
    ).as_dict()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.get("status") != "passed":
        raise ValueError(f"KIS holiday calendar failed; report={report_path}")
    expected_prior_date = result.get("expected_prior_date")
    if not isinstance(expected_prior_date, str) or not expected_prior_date:
        raise ValueError(f"KIS holiday calendar returned no expected prior date; report={report_path}")
    return date.fromisoformat(expected_prior_date)


def _collect_auto_field_run_daily_source(
    args: argparse.Namespace,
    *,
    target_date: date,
    refresh_stock_master: bool = False,
    token_cache: KisTokenCache | None = None,
) -> Path:
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    if expected_prior_date is None:
        raise ValueError("field-run auto data collection requires an expected prior date")
    expected_trading_dates = _field_run_expected_trading_dates_from_holiday_report(target_date)
    symbol_list_path = Path("reports/dry-run/kis-source-symbols.txt")
    stock_master_report = Path("reports/dry-run/kis-stock-master.json")
    if refresh_stock_master or not symbol_list_path.exists():
        stock_result = build_kis_stock_master(markets=("KOSPI", "KOSDAQ")).as_dict()
        write_kis_stock_master_report(stock_result, stock_master_report)
        if stock_result.get("status") != "passed":
            raise ValueError(f"KIS stock master refresh failed; report={stock_master_report}")
        write_kis_stock_master_symbol_list(stock_result.get("included_symbols", []), symbol_list_path)
    symbols = tuple(_read_symbol_lists([symbol_list_path]))
    if not symbols:
        raise ValueError(f"KIS source symbol list is empty; path={symbol_list_path}")
    print(f"field_run_stage=daily_source_symbols count={len(symbols)}", flush=True)

    daily_output_root = Path("data/raw/kis/daily-bars")
    daily_report = Path("reports/dry-run/kis-daily-bars.json")
    full_symbols, incremental_symbol_groups = _classify_daily_bar_collection_scope(
        symbols,
        output_root=daily_output_root,
        target_date=target_date,
        expected_prior_date=expected_prior_date,
        min_prior_trading_days=args.min_prior_trading_days,
        expected_trading_dates=expected_trading_dates,
    )
    collection_results: list[dict[str, object]] = []
    if full_symbols:
        collection_results.append(
            build_kis_daily_bars(
                symbols=full_symbols,
                start_date=expected_prior_date - timedelta(days=120),
                end_date=expected_prior_date,
                quote_interval_seconds=_kis_quote_interval(args),
                endpoint_profile=args.endpoint_profile,
                auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
                confirm_prod_readonly=args.confirm_prod_readonly,
                min_trading_days=args.min_prior_trading_days,
                token_cache=token_cache,
            ).as_dict()
        )
    incremental_symbols = tuple(
        symbol
        for grouped_symbols in incremental_symbol_groups.values()
        for symbol in grouped_symbols
    )
    refresh_symbols = set(full_symbols) | set(incremental_symbols)
    current_symbols = tuple(symbol for symbol in symbols if symbol not in refresh_symbols)
    print(
        f"field_run_stage=daily_source_scope current={len(current_symbols)} "
        f"full_refresh={len(full_symbols)} incremental={len(incremental_symbols)}",
        flush=True,
    )
    for incremental_start_date, grouped_symbols in sorted(incremental_symbol_groups.items()):
        collection_results.append(
            build_kis_daily_bars(
                symbols=grouped_symbols,
                start_date=incremental_start_date,
                end_date=expected_prior_date,
                quote_interval_seconds=_kis_quote_interval(args),
                endpoint_profile=args.endpoint_profile,
                auth_cooldown_path=Path(".omx/state/kis-auth-cooldown.json"),
                confirm_prod_readonly=args.confirm_prod_readonly,
                min_trading_days=1,
                token_cache=token_cache,
            ).as_dict()
        )
    if collection_results:
        daily_result = _merge_kis_daily_bar_collection_results(
            collection_results,
            current_symbols=current_symbols,
            full_symbols=full_symbols,
            incremental_symbols=incremental_symbols,
        )
    else:
        daily_result = {
            "status": "passed",
            "mode": "local-daily-bars-current",
            "symbol_count": len(symbols),
            "start_date": expected_prior_date.isoformat(),
            "end_date": expected_prior_date.isoformat(),
            "included_symbols": list(symbols),
            "excluded_symbols": [],
            "api_flags": [],
            "members": [],
            "read_call_count": 0,
            "collection_scope": "local_current",
            "current_symbol_count": len(symbols),
            "full_refresh_symbol_count": 0,
            "incremental_symbol_count": 0,
        }
    collectable_status = daily_result.get("status") == "passed"
    has_source_symbols = bool(symbols)
    written = _write_kis_daily_bar_csvs(daily_result, daily_output_root) if collection_results and collectable_status else 0
    daily_result["operational_acceptance"] = "accepted" if collectable_status else "rejected"
    daily_result["csv_output_root"] = str(daily_output_root)
    daily_result["csv_file_count"] = written
    daily_report.parent.mkdir(parents=True, exist_ok=True)
    daily_report.write_text(json.dumps(daily_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"field_run_stage=daily_source_report status={daily_result.get('status')} "
        f"operational_acceptance={daily_result.get('operational_acceptance')} "
        f"included={len(daily_result.get('included_symbols', []) or [])} "
        f"excluded={len(daily_result.get('excluded_symbols', []) or [])}",
        flush=True,
    )
    if not collectable_status or not has_source_symbols:
        raise ValueError(f"KIS daily-bar collection failed; report={daily_report}")

    path_list = _field_run_default_prior_path_list(target_date)
    csv_paths = _accepted_kis_daily_bar_csv_paths(
        daily_output_root,
        symbols=tuple(str(symbol) for symbol in daily_result.get("included_symbols", []) if symbol),
    )
    if not csv_paths:
        raise ValueError(f"KIS daily-bar collection wrote no CSV files; report={daily_report}")
    path_list.parent.mkdir(parents=True, exist_ok=True)
    path_list.write_text("\n".join(str(path) for path in csv_paths) + "\n", encoding="utf-8")
    return path_list


def _accepted_kis_daily_bar_csv_paths(output_root: Path, *, symbols: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for symbol in dict.fromkeys(symbols):
        paths.extend(sorted(output_root.glob(f"*/A{symbol}.csv")))
    return sorted(dict.fromkeys(paths))


def _classify_daily_bar_collection_scope(
    symbols: tuple[str, ...],
    *,
    output_root: Path,
    target_date: date,
    expected_prior_date: date,
    min_prior_trading_days: int,
    expected_trading_dates: tuple[date, ...] = (),
) -> tuple[tuple[str, ...], dict[date, tuple[str, ...]]]:
    full_symbols: list[str] = []
    incremental_symbols_by_start: dict[date, list[str]] = {}
    prior_dates_by_symbol = _existing_kis_daily_bar_dates_by_symbol(
        output_root,
        target_date=target_date,
    )
    for symbol in symbols:
        prior_dates = prior_dates_by_symbol.get(symbol, set())
        missing_expected_dates = tuple(
            trading_date
            for trading_date in expected_trading_dates
            if trading_date not in prior_dates
        )
        if expected_prior_date in prior_dates and not missing_expected_dates:
            continue
        if len(prior_dates) >= min_prior_trading_days:
            if missing_expected_dates:
                incremental_start_date = min(missing_expected_dates)
            else:
                incremental_start_date = max(prior_dates) + timedelta(days=1)
            incremental_symbols_by_start.setdefault(incremental_start_date, []).append(symbol)
        else:
            full_symbols.append(symbol)
    return tuple(full_symbols), {
        start_date: tuple(grouped_symbols)
        for start_date, grouped_symbols in incremental_symbols_by_start.items()
    }


def _existing_kis_daily_bar_dates_by_symbol(output_root: Path, *, target_date: date) -> dict[str, set[date]]:
    dates_by_symbol: dict[str, set[date]] = {}
    for path in sorted(output_root.glob("*/*.csv")):
        symbol = _symbol_from_kis_daily_bar_path(path)
        if symbol is None:
            continue
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    raw_date = str(row.get("date") or "").strip()
                    if len(raw_date) != 8 or not raw_date.isdigit():
                        continue
                    trading_date = datetime.strptime(raw_date, "%Y%m%d").date()
                    if trading_date < target_date:
                        dates_by_symbol.setdefault(symbol, set()).add(trading_date)
        except OSError:
            continue
    return dates_by_symbol


def _symbol_from_kis_daily_bar_path(path: Path) -> str | None:
    stem = path.stem
    if not stem.startswith("A"):
        return None
    symbol = stem[1:]
    if not symbol:
        return None
    return _normalize_kis_symbol(symbol)


def _existing_kis_daily_bar_dates(output_root: Path, *, symbol: str, target_date: date) -> set[date]:
    dates: set[date] = set()
    for path in sorted(output_root.glob(f"*/A{symbol}.csv")):
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    raw_date = str(row.get("date") or "").strip()
                    if len(raw_date) != 8 or not raw_date.isdigit():
                        continue
                    trading_date = datetime.strptime(raw_date, "%Y%m%d").date()
                    if trading_date < target_date:
                        dates.add(trading_date)
        except OSError:
            continue
    return dates


def _field_run_expected_trading_dates_from_holiday_report(target_date: date) -> tuple[date, ...]:
    report_path = _field_run_holiday_calendar_report_path(target_date)
    if not report_path.exists():
        return ()
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ()
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return ()
    trading_dates: list[date] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("bzdy_yn") or "").upper() != "Y":
            continue
        if str(row.get("opnd_yn") or "").upper() != "Y":
            continue
        raw_date = row.get("bass_dt")
        if not isinstance(raw_date, str):
            continue
        try:
            trading_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        if trading_date < target_date:
            trading_dates.append(trading_date)
    return tuple(sorted(set(trading_dates)))


def _merge_kis_daily_bar_collection_results(
    results: list[dict[str, object]],
    *,
    current_symbols: tuple[str, ...],
    full_symbols: tuple[str, ...],
    incremental_symbols: tuple[str, ...],
) -> dict[str, object]:
    statuses = [str(result.get("status") or "failed") for result in results]
    diagnostic_flags: list[str] = []
    accepted_symbols: list[str] = list(current_symbols)
    excluded_symbols: list[object] = []
    accepted_members: list[object] = []
    rejected_members: list[object] = []
    component_ranges: list[dict[str, object]] = []
    start_dates: list[str] = []
    end_dates: list[str] = []
    read_call_count = 0
    for result in results:
        diagnostic_flags.extend(str(flag) for flag in result.get("api_flags", []) if flag)
        excluded = result.get("excluded_symbols")
        if isinstance(excluded, list):
            excluded_symbols.extend(excluded)
        member_rows = result.get("members")
        if isinstance(member_rows, list):
            for member in member_rows:
                if not isinstance(member, dict):
                    continue
                symbol = str(member.get("symbol") or "")
                member_flags = [str(flag) for flag in member.get("field_data_flags", []) if flag]
                if member.get("included") and symbol and not member_flags:
                    accepted_symbols.append(symbol)
                    accepted_members.append(member)
                else:
                    rejected_members.append(member)
        start_date = result.get("start_date")
        end_date = result.get("end_date")
        if isinstance(start_date, str) and start_date:
            start_dates.append(start_date)
        if isinstance(end_date, str) and end_date:
            end_dates.append(end_date)
        component_ranges.append(
            {
                "status": result.get("status"),
                "start_date": start_date,
                "end_date": end_date,
                "symbol_count": result.get("symbol_count"),
                "included_symbol_count": len(result.get("included_symbols", []) or []),
                "excluded_symbol_count": len(result.get("excluded_symbols", []) or []),
            }
        )
        read_call_count += int(result.get("read_call_count") or 0)
    accepted_symbol_set = set(accepted_symbols)
    refresh_symbol_set = set(full_symbols) | set(incremental_symbols)
    missing_refresh_symbols = sorted(symbol for symbol in refresh_symbol_set if symbol not in accepted_symbol_set)
    for member in rejected_members:
        if not isinstance(member, dict):
            continue
        symbol = str(member.get("symbol") or "")
        if not symbol or symbol in accepted_symbol_set:
            continue
        reason = str(member.get("reason") or "daily bar member rejected")
        excluded_symbols.append([symbol, reason])
    for symbol in missing_refresh_symbols:
        excluded_symbols.append([symbol, "daily bar refresh failed or was not accepted"])
    full_symbol_set = set(full_symbols)
    missing_full_symbols = sorted(symbol for symbol in missing_refresh_symbols if symbol in full_symbol_set)
    missing_incremental_symbols = sorted(symbol for symbol in missing_refresh_symbols if symbol not in full_symbol_set)
    tolerable_full_exclusions = _tolerable_full_refresh_daily_bar_exclusions(
        missing_full_symbols,
        excluded_symbols=excluded_symbols,
    )
    clean_components = bool(statuses) and (
        all(status == "passed" for status in statuses)
        or (tolerable_full_exclusions and all(status in {"passed", "failed", "degraded"} for status in statuses))
    )
    clean_refresh = not missing_incremental_symbols and (
        not diagnostic_flags or tolerable_full_exclusions
    )
    status = "passed" if accepted_symbols and clean_components and clean_refresh else "failed"
    return {
        "status": status,
        "mode": "network-read-only-daily-bars-prod-auto-incremental",
        "included_symbols": list(dict.fromkeys(accepted_symbols)),
        "excluded_symbols": _dedupe_symbol_reason_rows(excluded_symbols),
        "api_flags": [] if status == "passed" else list(dict.fromkeys(diagnostic_flags or ["daily_bar_refresh_incomplete"])),
        "diagnostic_api_flags": list(dict.fromkeys(diagnostic_flags)),
        "members": accepted_members,
        "read_call_count": read_call_count,
        "collection_scope": "mixed" if full_symbols and incremental_symbols else ("full" if full_symbols else "incremental"),
        "current_symbol_count": len(current_symbols),
        "full_refresh_symbol_count": len(full_symbols),
        "incremental_symbol_count": len(incremental_symbols),
        "component_statuses": statuses,
        "component_ranges": component_ranges,
        "start_date": min(start_dates) if start_dates else None,
        "end_date": max(end_dates) if end_dates else None,
    }


def _tolerable_full_refresh_daily_bar_exclusions(
    missing_full_symbols: list[str],
    *,
    excluded_symbols: list[object],
) -> bool:
    if not missing_full_symbols:
        return False
    reasons_by_symbol: dict[str, list[str]] = {}
    for row in excluded_symbols:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        symbol = str(row[0] or "")
        reason = str(row[1] or "")
        if symbol:
            reasons_by_symbol.setdefault(symbol, []).append(reason)
    for symbol in missing_full_symbols:
        reasons = reasons_by_symbol.get(symbol, [])
        if not reasons or not any(_is_tolerable_daily_bar_exclusion(reason) for reason in reasons):
            return False
    return True


def _is_tolerable_daily_bar_exclusion(reason: str) -> bool:
    normalized = reason.lower()
    return (
        "insufficient kis daily rows" in normalized
        or "schema mismatch: missing output2" in normalized
    )


def _dedupe_symbol_reason_rows(rows: list[object]) -> list[object]:
    deduped: list[object] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            key = (str(row[0]), str(row[1]))
            if key in seen:
                continue
            seen.add(key)
            deduped.append([key[0], key[1]])
        else:
            deduped.append(row)
    return deduped


def _build_field_run_universe_report(args: argparse.Namespace) -> dict[str, object]:
    target_date = _field_run_target_date(args)
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    bars = _load_field_universe_bars(args, target_date=target_date)
    report = build_prior_only_field_universe(
        bars,
        target_date=target_date,
        universe_id=args.universe_id,
        value_window=args.value_window,
        sma_window=args.sma_window,
        atr_window=args.atr_window,
        min_average_value=_decimal(args.min_average_value),
        min_atr_ratio=_decimal(args.min_atr_ratio),
        require_close_above_sma=not args.disable_close_above_sma,
        max_symbols=args.max_symbols,
        min_prior_trading_days=args.min_prior_trading_days,
        max_prior_data_lag_days=args.max_prior_data_lag_days,
        expected_prior_date=expected_prior_date,
    )
    write_field_universe_report(report, args.universe_output)
    if not report.kis_symbols:
        raise ValueError("field-run universe build produced no KIS symbols")
    return report.as_dict()


def _field_run_symbols_from_universe_payload(payload: dict[str, object]) -> tuple[str, ...]:
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("field-run universe payload must contain a report object")
    kis_symbols = report.get("kis_symbols")
    if not isinstance(kis_symbols, list) or not all(isinstance(symbol, str) for symbol in kis_symbols):
        raise ValueError("field-run universe report kis_symbols must be a string list")
    if not kis_symbols:
        raise ValueError("field-run universe report must include at least one KIS symbol")
    return tuple(kis_symbols)


def _field_run_universe_evidence(path: Path, *, args: argparse.Namespace, payload: dict[str, object]) -> dict[str, object]:
    target_date = _field_run_target_date(args)
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    report = payload["report"]
    summary = payload["summary"]
    return {
        "path": str(path),
        "target_date": target_date.isoformat(),
        "expected_prior_date": expected_prior_date.isoformat() if expected_prior_date is not None else None,
        "included_count": summary["included_count"],
        "kis_symbols": list(report["kis_symbols"]),
        "latest_prior_date": report["latest_prior_date"],
        "latest_prior_lag_days": report["latest_prior_lag_days"],
        "source_fresh": True,
    }


def _validate_field_run_universe_report(path: Path, *, args: argparse.Namespace, symbols: tuple[str, ...] | None) -> dict[str, object]:
    target_date = _field_run_target_date(args)
    expected_prior_date = _field_universe_expected_prior_date(args, target_date)
    as_of = _parse_guard_now(args.now) if args.now else normalize_to_kst(datetime.now().astimezone())
    payload = load_reusable_field_universe_artifact(
        path,
        target_date=target_date,
        expected_prior_date=expected_prior_date,
        max_prior_data_lag_days=args.max_prior_data_lag_days,
        as_of=as_of,
        max_artifact_age_minutes=args.max_universe_artifact_age_minutes,
    )
    report = payload["report"]
    artifact_symbols = tuple(str(symbol) for symbol in report["kis_symbols"])
    requested_symbols = tuple(_normalize_kis_symbol(symbol) for symbol in symbols) if symbols is not None else None
    if requested_symbols is not None and artifact_symbols != requested_symbols:
        raise ValueError("field-run universe report kis_symbols must exactly match requested symbols")
    return payload


def _field_run_target_date(args: argparse.Namespace) -> date:
    if getattr(args, "market_session_date", None):
        return _parse_date(args.market_session_date)
    return (_parse_guard_now(args.now) if args.now else normalize_to_kst(datetime.now().astimezone())).date()


def _field_run_cycle_symbols(args: argparse.Namespace, symbols: tuple[str, ...]) -> tuple[str, ...]:
    if args.max_swing_focus_symbols <= 0:
        raise ValueError("max-swing-focus-symbols must be positive")
    now = _parse_guard_now(args.now) if args.now else normalize_to_kst(datetime.now().astimezone())
    if now.time() < _parse_hhmm(args.swing_focus_start_time):
        return symbols
    candidates = _field_run_swing_focus_symbols(
        args.output_dir,
        trading_day=now.date(),
        max_symbols=args.max_swing_focus_symbols,
    )
    if not candidates:
        return symbols
    allowed = {_normalize_kis_symbol(symbol) for symbol in candidates}
    focused = tuple(symbol for symbol in symbols if _normalize_kis_symbol(symbol) in allowed)
    return focused or symbols


def _field_run_swing_focus_symbols(output_dir: Path, *, trading_day: date, max_symbols: int) -> tuple[str, ...]:
    path = output_dir / "watchlist" / f"watchlist-full-{trading_day.isoformat()}.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    summaries = payload.get("symbol_summaries") or []
    ranked = sorted(
        (item for item in summaries if _field_run_decimal(item.get("intraday_change_pct")) > 0),
        key=lambda item: (
            -_field_run_decimal(item.get("intraday_change_pct")),
            -int(item.get("passed_count") or 0),
            str(item.get("symbol") or ""),
        ),
    )
    return tuple(str(item.get("symbol") or "") for item in ranked[:max_symbols] if item.get("symbol"))


def _normalize_kis_symbol(symbol: str) -> str:
    value = str(symbol).strip()
    return value[1:] if value.startswith("A") and len(value) == 7 else value


def _field_run_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def run_plan_a_sensitivity_command(args: argparse.Namespace) -> int:
    decision = build_plan_a_limited_sensitivity_decision()
    write_plan_a_sensitivity_decision(decision, args.output)

    print(f"decision_id={decision.decision_id}")
    print(f"status={decision.status}")
    print(f"candidate_b_action={decision.candidate_b_action}")
    print(f"report={args.output}")
    return 0


def _load_dry_run_bars(args: argparse.Namespace, *, require_input: bool = False) -> list[Bar]:
    csv_input_requested = bool(args.path or args.root or args.path_list)
    if not csv_input_requested:
        if require_input:
            raise ValueError("dry-run CSV input is required for this command")
        return []
    paths = _csv_paths(args.path, args.root, args.path_list)
    symbol_filter = {
        _normalize_report_symbol(str(symbol))
        for symbol in (getattr(args, "symbol_filter", None) or [])
        if str(symbol).strip()
    }
    if symbol_filter:
        paths = [path for path in paths if _normalize_report_symbol(path.stem) in symbol_filter]
    if args.limit_files is not None:
        if args.limit_files <= 0:
            raise ValueError("limit-files must be positive")
        paths = paths[: args.limit_files]
    if not paths:
        raise ValueError("no dry-run CSV paths remained after applying --limit-files")
    symbols = _csv_symbols(paths, None)
    bars: list[Bar] = []
    for path, symbol in zip(paths, symbols, strict=True):
        loaded = load_daishin_minute_csv(path, symbol=symbol, source=args.source)
        bars.extend(_filter_bars_by_date(loaded, start_date=args.start_date, end_date=args.end_date))
    if not bars:
        raise ValueError("no dry-run bars matched the provided CSV paths and date filters")
    return bars


def _combine_field_monitor_bars(
    *,
    warmup_bars: list[Bar],
    replay_bars: list[Bar],
    market_bars: list[Bar],
) -> list[Bar]:
    market_cutoff = min(bar.timestamp for bar in market_bars)
    combined: dict[tuple[datetime, str], Bar] = {}
    for bar in warmup_bars:
        if bar.timestamp < market_cutoff:
            symbol = _normalize_report_symbol(bar.symbol)
            combined[(bar.timestamp, symbol)] = replace(bar, symbol=symbol)
    for bar in replay_bars:
        if bar.timestamp < market_cutoff:
            symbol = _normalize_report_symbol(bar.symbol)
            combined[(bar.timestamp, symbol)] = replace(bar, symbol=symbol)
    for bar in market_bars:
        symbol = _normalize_report_symbol(bar.symbol)
        combined[(bar.timestamp, symbol)] = replace(bar, symbol=symbol)
    return sorted(combined.values(), key=lambda item: (item.timestamp, item.symbol))


def _bars_from_watchlist_history(output_dir: Path, *, trading_day: date) -> list[Bar]:
    path = output_dir / "watchlist" / f"watchlist-full-{trading_day.isoformat()}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    bars: list[Bar] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        try:
            timestamp = _member_observed_at(row, fallback=None)
            close = _positive_decimal(row.get("close"), fallback=Decimal("0"))
        except (ArithmeticError, TypeError, ValueError):
            continue
        if timestamp is None:
            continue
        if close <= 0:
            continue
        open_price = _positive_decimal(row.get("open"), fallback=close)
        high_price = _positive_decimal(row.get("high"), fallback=max(open_price, close))
        low_price = _positive_decimal(row.get("low"), fallback=min(open_price, close))
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp,
                open=open_price,
                high=max(high_price, open_price, close),
                low=min(low_price, open_price, close),
                close=close,
                volume=_nonnegative_int(row.get("volume")),
                value=_positive_decimal(row.get("traded_value"), fallback=close * Decimal(_nonnegative_int(row.get("volume")))),
                source=f"watchlist-replay:{path.name}",
                bid_ask_ratio=_positive_decimal(row.get("bid_ask_ratio"), fallback=Decimal("2.0")),
            )
        )
    return bars


def _load_field_universe_bars(args: argparse.Namespace, *, target_date: date) -> list[Bar]:
    csv_input_requested = bool(args.path or args.root or args.path_list)
    if not csv_input_requested:
        raise ValueError("field-universe CSV input is required for this command")
    paths = _field_universe_csv_paths(
        args.path,
        args.root,
        args.path_list,
        target_date=target_date,
        latest_months=args.latest_months,
    )
    if args.limit_files is not None:
        if args.limit_files <= 0:
            raise ValueError("limit-files must be positive")
        paths = paths[: args.limit_files]
    if not paths:
        raise ValueError("no field-universe CSV paths remained after applying input filters")

    bars = load_prior_daily_bars_from_minute_csvs(
        paths,
        target_date=target_date,
        source=args.source,
        start_date=datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None,
        end_date=datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None,
    )
    if not bars:
        raise ValueError("no field-universe bars matched the provided CSV paths and date filters")
    return bars


def load_config(path: Path, *, output_dir: Path | None = None) -> Phase1Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    dummy = raw.get("dummy", {})
    backtest = raw.get("backtest", {})
    output = raw.get("output", {})

    symbols = list(dummy.get("symbols", []))
    if not symbols:
        raise ValueError("dummy.symbols must contain at least one symbol")

    return Phase1Config(
        dummy=DummyConfig(
            symbols=symbols,
            seed=int(dummy.get("seed", 7477)),
            trading_day=str(dummy.get("trading_day", "2026-01-05")),
            minutes=int(dummy.get("minutes", 30)),
        ),
        backtest=BacktestConfig(
            start_equity=_decimal(backtest.get("start_equity", "10000000")),
            fee_rate=_decimal(backtest.get("fee_rate", "0.00015")),
            slippage_rate=_decimal(backtest.get("slippage_rate", "0.00050")),
            quantity_step=_decimal(backtest.get("quantity_step", "0.000001")),
            profit_target=_decimal(backtest.get("profit_target", "0.03")),
            hard_stop=_decimal(backtest.get("hard_stop", "-0.03")),
            day_end_exit=_bool(backtest.get("day_end_exit", True)),
            day_end_exit_time=(
                _time(str(backtest["day_end_exit_time"]))
                if backtest.get("day_end_exit_time") is not None
                else None
            ),
            intrabar_policy=str(backtest.get("intrabar_policy", "close-only")),
            ambiguous_intrabar_policy=str(backtest.get("ambiguous_intrabar_policy", "stop-first")),
            max_holding_minutes=(
                int(backtest["max_holding_minutes"])
                if backtest.get("max_holding_minutes") is not None
                else None
            ),
            capital_mode=str(backtest.get("capital_mode", "per-symbol")),
            max_open_positions=int(backtest.get("max_open_positions", 5)),
            variable_slot_count=_bool(backtest.get("variable_slot_count", False)),
            slot_capital_cap=(
                _decimal(backtest["slot_capital_cap"])
                if backtest.get("slot_capital_cap") is not None
                else None
            ),
            weekly_contribution=_decimal(backtest.get("weekly_contribution", "0")),
            max_daily_stop_losses=(
                int(backtest["max_daily_stop_losses"])
                if backtest.get("max_daily_stop_losses") is not None
                else None
            ),
            max_daily_loss=(
                _decimal(backtest["max_daily_loss"])
                if backtest.get("max_daily_loss") is not None
                else None
            ),
            signal_group_max_open_positions=_parse_signal_group_limits(
                backtest.get("signal_group_max_open_positions")
            ),
            signal_group_strategy_ids=_parse_signal_group_strings(
                backtest.get("signal_group_strategy_ids")
            ),
        ),
        output_dir=output_dir or Path(output.get("directory", "reports/phase-1")),
    )


def generate_configured_dummy_bars(config: DummyConfig) -> list[Bar]:
    bars: list[Bar] = []
    for index, symbol in enumerate(config.symbols):
        bars.extend(
            generate_dummy_bars(
                symbol=symbol,
                seed=config.seed + index,
                trading_day=config.trading_day,
                minutes=config.minutes,
            )
        )
    return bars


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _add_market_session_stop_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--enforce-market-session-stop",
        action="store_true",
        help="skip work after the configured KST market-session stop time; prevents lingering polling loops",
    )
    parser.add_argument(
        "--market-session-date",
        help="KST session date for stop guard, YYYY-MM-DD; field-run infers this from --now/current KST date when omitted",
    )
    parser.add_argument(
        "--market-session-stop-time",
        default="15:35",
        help="KST HH:MM stop cutoff when --enforce-market-session-stop is supplied",
    )
    parser.add_argument(
        "--market-session-start-time",
        default="09:00",
        help="KST HH:MM start cutoff when --enforce-market-session-stop is supplied",
    )
    parser.add_argument(
        "--now",
        help="test/operator override for current timestamp, ISO-8601; interpreted as KST if timezone is omitted",
    )


def _market_session_stop_guard(args: argparse.Namespace) -> dict[str, str] | None:
    if not getattr(args, "enforce_market_session_stop", False):
        return None
    now = _parse_guard_now(getattr(args, "now", None))
    if getattr(args, "market_session_date", None):
        session_date = _parse_date(args.market_session_date)
    elif getattr(args, "command", "") == "field-run":
        session_date = now.date()
    else:
        raise ValueError("--enforce-market-session-stop requires --market-session-date")
    start_time = _parse_hhmm(args.market_session_start_time)
    start_at = datetime.combine(session_date, start_time, tzinfo=KST)
    if now < start_at:
        return {
            "reason": "market-session-not-open",
            "session_date": session_date.isoformat(),
            "start_time": start_time.strftime("%H:%M"),
            "start_at": start_at.isoformat(),
            "checked_at": now.isoformat(),
        }
    stop_time = _parse_hhmm(args.market_session_stop_time)
    stop_at = datetime.combine(session_date, stop_time, tzinfo=KST)
    if now < stop_at:
        return None
    return {
        "reason": "market-session-closed",
        "session_date": session_date.isoformat(),
        "stop_time": stop_time.strftime("%H:%M"),
        "stop_at": stop_at.isoformat(),
        "checked_at": now.isoformat(),
    }


def _parse_guard_now(value: str | None) -> datetime:
    if value is None:
        return normalize_to_kst(datetime.now().astimezone())
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return normalize_to_kst(parsed)


def _parse_hhmm(value: str):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError("market-session-stop-time must be HH:MM") from exc


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc


def _field_universe_expected_prior_date(args: argparse.Namespace, target_date: date) -> date | None:
    explicit = getattr(args, "expected_prior_date", None)
    if explicit:
        return _parse_date(explicit)
    if getattr(args, "disable_expected_prior_date", False):
        return None
    if getattr(args, "command", "") not in {"build-daily-field-universe", "field-run"}:
        return None
    holidays = {_parse_date(value) for value in getattr(args, "krx_holiday", [])}
    return _previous_trading_weekday(target_date, holidays=holidays)


def _previous_trading_weekday(target_date: date, *, holidays: set[date]) -> date:
    candidate = target_date - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate -= timedelta(days=1)
    return candidate


def _local_free_space_gb(override: str | None, target: Path) -> Decimal:
    if override is not None:
        return _decimal(override)
    probe = target if target.exists() and target.is_dir() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return Decimal(usage.free) / Decimal(1024**3)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _parse_signal_group_limits(value: object) -> tuple[tuple[str, int], ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, str):
                if "=" not in item:
                    raise ValueError("signal group limit must be GROUP=N")
                group, limit = item.split("=", 1)
                items.append((group, limit))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                items.append((item[0], item[1]))
            else:
                raise ValueError("signal group limit must be GROUP=N")
    else:
        raise ValueError("signal group limits must be a mapping or list")

    limits: list[tuple[str, int]] = []
    for group, limit in items:
        group_name = str(group).strip()
        parsed_limit = int(limit)
        if not group_name:
            raise ValueError("signal group name must be non-empty")
        if parsed_limit <= 0:
            raise ValueError("signal group max open positions must be positive")
        limits.append((group_name, parsed_limit))
    return tuple(limits)


def _parse_signal_group_strings(value: object) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, str):
                if "=" not in item:
                    raise ValueError("signal group mapping must be GROUP=VALUE")
                group, mapped = item.split("=", 1)
                items.append((group, mapped))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                items.append((item[0], item[1]))
            else:
                raise ValueError("signal group mapping must be GROUP=VALUE")
    else:
        raise ValueError("signal group mappings must be a mapping or list")

    mappings: list[tuple[str, str]] = []
    for group, mapped in items:
        group_name = str(group).strip()
        mapped_value = str(mapped).strip()
        if not group_name or not mapped_value:
            raise ValueError("signal group mapping values must be non-empty")
        mappings.append((group_name, mapped_value))
    return tuple(mappings)


def _csv_paths(paths: list[Path], roots: list[Path], path_lists: list[Path] | None = None) -> list[Path]:
    resolved = list(paths)
    for path_list in path_lists or []:
        resolved.extend(read_path_list(path_list))
    for root in roots:
        resolved.extend(discover_daishin_csv_paths(root))
    if not resolved:
        raise ValueError("at least one --path or --root is required")
    return list(dict.fromkeys(resolved))


def _field_universe_csv_paths(
    paths: list[Path],
    roots: list[Path],
    path_lists: list[Path] | None,
    *,
    target_date: date,
    latest_months: int | None,
) -> list[Path]:
    if latest_months is not None and latest_months <= 0:
        raise ValueError("latest-months must be positive")

    resolved = list(paths)
    for path_list in path_lists or []:
        resolved.extend(read_path_list(path_list))
    for root in roots:
        root = Path(root)
        selected_month_dirs = _select_month_directories(root, target_date=target_date, latest_months=latest_months)
        if selected_month_dirs:
            for month_dir in selected_month_dirs:
                resolved.extend(_discover_csv_paths_prefer_direct(month_dir))
        else:
            resolved.extend(discover_daishin_csv_paths(root))
    if not resolved:
        raise ValueError("at least one --path or --root is required")
    return list(dict.fromkeys(resolved))


def _select_month_directories(root: Path, *, target_date: date, latest_months: int | None) -> list[Path]:
    if not root.exists() or not root.is_dir() or latest_months is None:
        return []
    target_yyyymm = target_date.strftime("%Y%m")
    month_dirs = sorted(
        item
        for item in root.iterdir()
        if item.is_dir() and _is_eligible_month_dir(item, target_yyyymm=target_yyyymm)
    )
    if not month_dirs:
        month_dirs = sorted(
            item
            for item in root.rglob("*")
            if item.is_dir() and _is_eligible_month_dir(item, target_yyyymm=target_yyyymm)
        )
    selected_months = sorted({item.name for item in month_dirs})[-latest_months:]
    return [item for item in month_dirs if item.name in selected_months]


def _is_eligible_month_dir(path: Path, *, target_yyyymm: str) -> bool:
    return len(path.name) == 6 and path.name.isdigit() and path.name <= target_yyyymm


def _discover_csv_paths_prefer_direct(root: Path) -> list[Path]:
    if not root.exists():
        raise FileNotFoundError(f"CSV path does not exist: {root}")
    if not root.is_dir():
        return [root]
    direct_csvs = sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() == ".csv")
    if direct_csvs:
        return direct_csvs
    return discover_daishin_csv_paths(root)


def _read_symbol_lists(paths: list[Path]) -> list[str]:
    symbols: list[str] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            symbol = line.strip()
            if symbol and not symbol.startswith("#"):
                symbols.append(symbol)
    return symbols


def _api_report_flags(
    paths: list[Path],
    *,
    quote_depth_reports: list[Path] | None = None,
    max_age_seconds: int | None = None,
    now: datetime | None = None,
) -> list[str]:
    if max_age_seconds is not None and max_age_seconds <= 0:
        raise ValueError("market-data-max-age-seconds must be positive")
    flags: list[str] = []
    quote_depth_by_symbol = _quote_depth_by_symbol(quote_depth_reports or [])
    included_member_count = 0
    parsed_included_timestamp_count = 0
    reference_now = normalize_to_kst(now or datetime.now().astimezone()) if max_age_seconds is not None else None
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        flags.extend(str(flag) for flag in payload.get("api_flags", []))
        evidence = payload.get("budget_evidence") or {}
        is_kis_live_market_report = (
            str(payload.get("universe_id") or "").startswith("kis-readonly-u")
            or str(evidence.get("source") or "").startswith("kis-readonly-universe-")
        )
        for member in payload.get("members", []):
            if isinstance(member, dict):
                symbol = _normalize_report_symbol(str(member.get("symbol") or ""))
                depth = quote_depth_by_symbol.get(symbol)
                member_flags = [str(flag) for flag in member.get("field_data_flags", [])]
                if depth and depth.get("bid_ask_ratio"):
                    member_flags = [flag for flag in member_flags if flag != "bid_ask_placeholder"]
                flags.extend(member_flags)
                if member.get("included"):
                    included_member_count += 1
                    if not member_flags:
                        missing_fields = [
                            field
                            for field in ("price", "open", "high", "low", "volume", "traded_value")
                            if not member.get(field)
                        ]
                        if missing_fields:
                            flags.append(f"field_data_incomplete:{','.join(missing_fields)}")
                        if not member.get("bid_ask_ratio") and not (depth and depth.get("bid_ask_ratio")):
                            flags.append("bid_ask_placeholder")
                    observed_at = str(member.get("observed_at") or member.get("timestamp") or "")
                    if not observed_at:
                        flags.append("invalid_market_timestamp")
                    else:
                        try:
                            parsed_observed_at = _parse_market_timestamp(observed_at)
                        except ValueError:
                            flags.append("invalid_market_timestamp")
                        else:
                            parsed_included_timestamp_count += 1
                            if reference_now is not None:
                                age_seconds = (reference_now - parsed_observed_at).total_seconds()
                                if age_seconds < -60:
                                    flags.append("market_data_future_timestamp")
                                    flags.append(f"market_data_future_timestamp:{symbol}")
                                elif age_seconds > max_age_seconds:
                                    flags.append("market_data_stale")
                                    flags.append(f"market_data_stale:{symbol}")
                    if is_kis_live_market_report:
                        price_observed_at = str(member.get("price_observed_at") or "")
                        depth_observed_at = str(member.get("depth_observed_at") or "")
                        gap_value = str(member.get("paired_snapshot_gap_seconds") or "")
                        if not price_observed_at or not depth_observed_at or not gap_value:
                            flags.append("paired_snapshot_missing")
                            flags.append(f"paired_snapshot_missing:{symbol}")
                        else:
                            try:
                                parsed_price_at = _parse_market_timestamp(price_observed_at)
                                parsed_depth_at = _parse_market_timestamp(depth_observed_at)
                                reported_gap = float(gap_value)
                            except (TypeError, ValueError):
                                flags.append("paired_snapshot_invalid")
                                flags.append(f"paired_snapshot_invalid:{symbol}")
                            else:
                                computed_gap = abs((parsed_depth_at - parsed_price_at).total_seconds())
                                if (
                                    reported_gap > 5.0
                                    or computed_gap > 5.0
                                    or abs(reported_gap - computed_gap) > 1.0
                                ):
                                    flags.append("paired_snapshot_gap_exceeded")
                                    flags.append(f"paired_snapshot_gap_exceeded:{symbol}")
        if evidence and evidence.get("within_budget") is False:
            flags.append("rate_limit_risk")
        for probe in payload.get("probes", []):
            diagnostics = probe.get("diagnostics") or {}
            flags.extend(str(flag) for flag in diagnostics.get("flags", []))
    if max_age_seconds is not None:
        if included_member_count > 0 and parsed_included_timestamp_count == 0:
            flags.append("market_data_missing_fresh_timestamp")
    if any(
        flag == "bid_ask_placeholder"
        or flag == "paired_snapshot_missing"
        or flag == "paired_snapshot_invalid"
        or flag == "paired_snapshot_gap_exceeded"
        or flag.startswith("paired_snapshot_missing:")
        or flag.startswith("paired_snapshot_invalid:")
        or flag.startswith("paired_snapshot_gap_exceeded:")
        or flag.startswith("field_data_incomplete:")
        or flag.startswith("invalid_market_timestamp")
        or flag in {"market_data_missing_fresh_timestamp", "market_data_future_timestamp", "market_data_stale"}
        for flag in flags
    ):
        flags.append("input_contract_degraded")
    return list(dict.fromkeys(flags))


def _has_input_contract_degradation(flags: tuple[str, ...]) -> bool:
    return any(
        flag == "input_contract_degraded"
        or flag == "api_schema_mismatch"
        or flag == "api_command_error"
        or flag == "bid_ask_placeholder"
        or flag == "paired_snapshot_missing"
        or flag == "paired_snapshot_invalid"
        or flag == "paired_snapshot_gap_exceeded"
        or flag.startswith("paired_snapshot_missing:")
        or flag.startswith("paired_snapshot_invalid:")
        or flag.startswith("paired_snapshot_gap_exceeded:")
        or flag.startswith("field_data_incomplete:")
        or flag.startswith("invalid_market_timestamp")
        or flag.startswith("market_data_stale:")
        or flag.startswith("market_data_future_timestamp:")
        or flag == "index_trend_missing"
        or flag == "index_trend_failed"
        or flag == "index_trend_no_bars"
        or flag == "index_trend_stale"
        or flag == "index_trend_future_timestamp"
        or flag.startswith("index_trend_api:")
        or flag.startswith("index_trend_missing:")
        or flag.startswith("index_trend_stale:")
        or flag.startswith("index_trend_future_timestamp:")
        or flag in {"market_data_missing_fresh_timestamp", "market_data_future_timestamp", "market_data_stale"}
        for flag in flags
    )


def _index_trend_provider_from_reports(paths: list[Path], *, enabled: bool):
    if not enabled:
        return None
    bars: list[Bar] = []
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        bars.extend(index_bars_from_report(payload))
    return provider_from_index_bars(bars)


def _validate_index_trend_reports_for_simulation(paths: list[Path], *, enabled: bool) -> None:
    flags = _index_trend_report_flags(
        paths,
        enabled=enabled,
        max_age_seconds=0,
        enforce_freshness=False,
    )
    if _has_input_contract_degradation(flags):
        raise ValueError(f"index trend report contract invalid: {','.join(flags)}")


def _index_payload_with_accumulated_bars(paths: list[Path], current_payload: dict[str, object]) -> dict[str, object]:
    bars_by_key: dict[tuple[str, datetime], Bar] = {}
    for path in paths:
        if path.exists():
            for bar in index_bars_from_report(json.loads(path.read_text(encoding="utf-8"))):
                bars_by_key[(bar.symbol, normalize_to_kst(bar.timestamp))] = bar
    for bar in index_bars_from_report(current_payload):
        bars_by_key[(bar.symbol, normalize_to_kst(bar.timestamp))] = bar
    payload = dict(current_payload)
    payload["bars"] = [_index_bar_payload(bar) for bar in sorted(bars_by_key.values(), key=lambda item: (item.timestamp, item.symbol))]
    return payload


def _index_bar_payload(bar: Bar) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "timestamp": bar.timestamp.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": bar.volume,
        "value": str(bar.value),
        "source": bar.source,
    }


def _index_trend_report_flags(
    paths: list[Path],
    *,
    enabled: bool,
    max_age_seconds: int,
    now: datetime | None = None,
    enforce_freshness: bool = True,
    required_index_codes: tuple[str, ...] = ("KOSPI", "KOSDAQ"),
) -> tuple[str, ...]:
    if not enabled:
        return ()
    if not paths:
        return ("index_trend_missing",)
    flags: list[str] = []
    reference = normalize_to_kst(now or datetime.now().astimezone())
    bar_count = 0
    latest_by_code: dict[str, datetime] = {}
    for path in paths:
        if not path.exists():
            flags.append("index_trend_missing")
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") not in ("passed", "ready"):
            flags.append("index_trend_failed")
        flags.extend(f"index_trend_api:{flag}" for flag in payload.get("api_flags", []) if flag)
        bars = index_bars_from_report(payload)
        bar_count += len(bars)
        for bar in bars:
            timestamp = normalize_to_kst(bar.timestamp)
            if bar.symbol in required_index_codes and (
                bar.symbol not in latest_by_code or timestamp > latest_by_code[bar.symbol]
            ):
                latest_by_code[bar.symbol] = timestamp
    if bar_count == 0:
        flags.append("index_trend_no_bars")
    for code in required_index_codes:
        latest_timestamp = latest_by_code.get(code)
        if latest_timestamp is None:
            flags.append(f"index_trend_missing:{code}")
            continue
        if not enforce_freshness:
            continue
        age_seconds = (reference - latest_timestamp).total_seconds()
        if age_seconds > max_age_seconds:
            flags.append(f"index_trend_stale:{code}:{int(age_seconds)}s")
        if age_seconds < -1:
            flags.append(f"index_trend_future_timestamp:{code}:{latest_timestamp.isoformat()}")
    return tuple(dict.fromkeys(flags))


def _api_report_payloads(paths: list[Path]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for path in paths:
        if path.exists():
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        else:
            payloads.append({"status": "missing", "path": str(path), "api_flags": ["report_missing"]})
    return payloads


def _bars_from_market_data_reports(paths: list[Path], *, quote_depth_reports: list[Path] | None = None) -> list[Bar]:
    bars: list[Bar] = []
    quote_depth_by_symbol = _quote_depth_by_symbol(quote_depth_reports or [])
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for member in payload.get("members", []):
            if not member.get("included"):
                continue
            price = _decimal(str(member.get("price") or "0"))
            if price <= 0:
                continue
            symbol = str(member["symbol"])
            observed_at = _member_observed_at(member, fallback=None)
            if observed_at is None:
                continue
            open_price = _positive_decimal(member.get("open"), fallback=price)
            high_price = _positive_decimal(member.get("high"), fallback=max(open_price, price))
            low_price = _positive_decimal(member.get("low"), fallback=min(open_price, price))
            volume = _nonnegative_int(member.get("volume"))
            traded_value = _positive_decimal(member.get("traded_value"), fallback=price * Decimal(volume))
            depth = quote_depth_by_symbol.get(_normalize_report_symbol(symbol))
            bid_ask_ratio = _positive_decimal(
                member.get("bid_ask_ratio") or (depth or {}).get("bid_ask_ratio"),
                fallback=Decimal("2.0"),
            )
            bars.append(
                Bar(
                    symbol=_normalize_report_symbol(symbol),
                    timestamp=observed_at,
                    open=open_price,
                    high=max(high_price, open_price, price),
                    low=min(low_price, open_price, price),
                    close=price,
                    volume=volume,
                    value=traded_value,
                    source=f"kis-readonly-report:{path.name}",
                    bid_ask_ratio=bid_ask_ratio,
                )
            )
    return bars


def _quote_depth_by_symbol(paths: list[Path]) -> dict[str, dict[str, object]]:
    depth_by_symbol: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for member in payload.get("members", []):
            if not isinstance(member, dict) or not member.get("included"):
                continue
            symbol = _normalize_report_symbol(str(member.get("symbol") or ""))
            if not symbol or not member.get("bid_ask_ratio"):
                continue
            depth_by_symbol[symbol] = member
    return depth_by_symbol


def _normalize_report_symbol(symbol: str) -> str:
    normalized = symbol.strip()
    if len(normalized) == 7 and normalized.startswith("A") and normalized[1:].isdigit():
        return normalized[1:]
    return normalized


def _member_observed_at(member: dict[str, object], *, fallback: datetime | None) -> datetime | None:
    observed_at = str(member.get("observed_at") or member.get("timestamp") or "")
    if not observed_at:
        return fallback
    try:
        parsed = _parse_market_timestamp(observed_at)
    except ValueError:
        return fallback
    return parsed


def _parse_market_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return normalize_to_kst(parsed)


def _positive_decimal(value: object, *, fallback: Decimal) -> Decimal:
    parsed = _decimal(str(value or "0"))
    return parsed if parsed > 0 else fallback


def _nonnegative_int(value: object) -> int:
    parsed = _decimal(str(value or "0"))
    return int(parsed) if parsed > 0 else 0


def _blacklist_report_flags(snapshot) -> list[str]:
    if snapshot is None:
        return []
    return list(snapshot.evaluation(now=normalize_to_kst(datetime.now().astimezone())).flags)


def _news_feed_flags(snapshot, *, require_news_feed: bool, now: datetime | None = None) -> list[str]:
    if snapshot is None:
        return ["news_feed_missing"] if require_news_feed else []
    reference_now = normalize_to_kst(now or datetime.now().astimezone())
    return list(snapshot.evaluation(now=reference_now).flags)


def _kis_quote_interval(args: argparse.Namespace) -> float:
    if args.quote_interval_seconds is not None:
        interval = float(args.quote_interval_seconds)
    else:
        field_budget = FieldApiBudgetPolicy().window_for(datetime.now().astimezone())
        field_limit = min(field_budget.total_limit_per_second, field_budget.scouter_limit_per_second)
        call_budget_after_token = max(1, field_limit - 1)
        interval = 0.5 if args.rate_profile == "paper" else max(0.3, 1 / call_budget_after_token)
    if interval < 0:
        raise ValueError("quote-interval-seconds must be non-negative")
    return interval


def _write_kis_daily_bar_csvs(result: dict[str, object], output_root: Path) -> int:
    written = 0
    for member in result.get("members", []):
        if not isinstance(member, dict) or not member.get("included"):
            continue
        symbol = str(member["symbol"])
        rows = member.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        rows_by_month: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            trading_date = date.fromisoformat(str(row["trading_date"]))
            rows_by_month.setdefault(trading_date.strftime("%Y%m"), []).append(row)
        for period, month_rows in sorted(rows_by_month.items()):
            path = output_root / period / f"A{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            merged_rows: dict[tuple[str, str], dict[str, object]] = {}
            if path.exists():
                with path.open(newline="", encoding="utf-8") as handle:
                    for existing in csv.DictReader(handle):
                        existing_date = str(existing.get("date") or "").strip()
                        existing_time = str(existing.get("time") or "1515").strip() or "1515"
                        if existing_date:
                            merged_rows[(existing_date, existing_time)] = {
                                "date": existing_date,
                                "time": existing_time,
                                "open": existing.get("open", ""),
                                "high": existing.get("high", ""),
                                "low": existing.get("low", ""),
                                "close": existing.get("close", ""),
                                "volume": existing.get("volume", ""),
                                "value": existing.get("value", ""),
                            }
            for row in month_rows:
                row_date = str(row["trading_date"]).replace("-", "")
                merged_rows[(row_date, "1515")] = {
                    "date": row_date,
                    "time": "1515",
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                    "value": row["traded_value"],
                }
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["date", "time", "open", "high", "low", "close", "volume", "value"],
                )
                writer.writeheader()
                for _, row in sorted(merged_rows.items()):
                    writer.writerow(row)
            written += 1
    return written


def _symbol_metadata_from_stock_master_members(members: object) -> list[SymbolMetadata]:
    if not isinstance(members, list):
        return []
    metadata_by_symbol: dict[str, SymbolMetadata] = {}
    for member in members:
        if not isinstance(member, dict):
            continue
        if member.get("included") is not True:
            continue
        item = SymbolMetadata(
            symbol=str(member["symbol"]),
            name=str(member["name"]),
            market=str(member["market"]),
            section_kind=str(member.get("section_kind") or ""),
            status_kind=str(member.get("status_kind") or ""),
            control_kind=str(member.get("control_kind") or ""),
            supervision_kind=str(member.get("supervision_kind") or ""),
            source=KIS_STOCK_MASTER_SOURCE,
        )
        metadata_by_symbol.setdefault(item.symbol, item)
    return list(metadata_by_symbol.values())


def _next_weekday(current: date) -> date:
    candidate = current + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _parse_cli_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return normalize_to_kst(parsed)


def _filter_bars_by_date(bars: list[Bar], *, start_date: str | None, end_date: str | None) -> list[Bar]:
    if not start_date and not end_date:
        return bars
    start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    if start and end and start > end:
        raise ValueError("--start-date must be before or equal to --end-date")
    return [
        bar
        for bar in bars
        if (start is None or bar.timestamp.date() >= start)
        and (end is None or bar.timestamp.date() <= end)
    ]


def _override_backtest_config(config: BacktestConfig, args: argparse.Namespace) -> BacktestConfig:
    return BacktestConfig(
        start_equity=_decimal(args.start_equity) if getattr(args, "start_equity", None) else config.start_equity,
        fee_rate=_decimal(args.fee_rate) if getattr(args, "fee_rate", None) else config.fee_rate,
        slippage_rate=_decimal(args.slippage_rate) if getattr(args, "slippage_rate", None) else config.slippage_rate,
        quantity_step=_decimal(args.quantity_step) if getattr(args, "quantity_step", None) else config.quantity_step,
        capital_mode=getattr(args, "capital_mode", None) or config.capital_mode,
        max_open_positions=(
            args.max_open_positions
            if getattr(args, "max_open_positions", None) is not None
            else config.max_open_positions
        ),
        signal_group_max_open_positions=(
            _parse_signal_group_limits(args.signal_group_max_open_positions)
            if getattr(args, "signal_group_max_open_positions", None)
            else config.signal_group_max_open_positions
        ),
        variable_slot_count=(
            True
            if getattr(args, "variable_slot_count", False)
            else config.variable_slot_count
        ),
        slot_capital_cap=(
            _decimal(args.slot_capital_cap)
            if getattr(args, "slot_capital_cap", None) is not None
            else config.slot_capital_cap
        ),
        weekly_contribution=(
            _decimal(args.weekly_contribution)
            if getattr(args, "weekly_contribution", None) is not None
            else config.weekly_contribution
        ),
        max_daily_stop_losses=(
            args.max_daily_stop_losses
            if getattr(args, "max_daily_stop_losses", None) is not None
            else config.max_daily_stop_losses
        ),
        max_daily_loss=(
            _decimal(args.max_daily_loss)
            if getattr(args, "max_daily_loss", None) is not None
            else config.max_daily_loss
        ),
        profit_target=_decimal(args.profit_target) if getattr(args, "profit_target", None) else config.profit_target,
        hard_stop=_decimal(args.hard_stop) if getattr(args, "hard_stop", None) else config.hard_stop,
        day_end_exit=False if getattr(args, "hold_overnight", False) else config.day_end_exit,
        day_end_exit_time=(
            _time(args.day_end_exit_time)
            if getattr(args, "day_end_exit_time", None) is not None
            else config.day_end_exit_time
        ),
        max_holding_minutes=(
            args.max_holding_minutes
            if getattr(args, "max_holding_minutes", None) is not None
            else config.max_holding_minutes
        ),
        intrabar_policy=getattr(args, "intrabar_policy", None) or config.intrabar_policy,
        ambiguous_intrabar_policy=getattr(args, "ambiguous_intrabar_policy", None) or config.ambiguous_intrabar_policy,
    )


def _strategy_factory_from_args(args: argparse.Namespace):
    strategy = getattr(args, "strategy", None)
    if strategy == "swing-support":
        return lambda: SwingSupportStrategy(
            sma_window=getattr(args, "swing_sma_window", None) or 20,
            volume_window=getattr(args, "swing_volume_window", None) or 5,
            support_band=_decimal(getattr(args, "swing_support_band", None) or "0.02"),
            max_volume_ratio=_decimal(getattr(args, "swing_max_volume_ratio", None) or "0.50"),
            max_rsi=_decimal(getattr(args, "swing_max_rsi", None) or "40"),
        )
    if strategy == "day-support-pullback":
        return lambda: DaySupportPullbackStrategy(
            entry_start=_time(getattr(args, "entry_start", None) or "13:30"),
            entry_end=_time(getattr(args, "entry_end", None) or "14:45"),
            sma_window=getattr(args, "swing_sma_window", None) or 20,
            volume_window=getattr(args, "swing_volume_window", None) or 5,
            support_band=_decimal(getattr(args, "swing_support_band", None) or "0.02"),
            max_volume_ratio=_decimal(getattr(args, "swing_max_volume_ratio", None) or "0.50"),
            max_rsi=_decimal(getattr(args, "swing_max_rsi", None) or "40"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "1.5"),
        )
    if strategy == "swing-momentum":
        return lambda: SwingMomentumStrategy(
            sma_window=getattr(args, "swing_sma_window", None) or 20,
            volume_window=getattr(args, "swing_volume_window", None) or 5,
            min_sma_distance=_decimal(getattr(args, "swing_min_sma_distance", None) or "0.01"),
            min_volume_ratio=_decimal(getattr(args, "swing_min_volume_ratio", None) or "1.00"),
            min_rsi=_decimal(getattr(args, "swing_min_rsi", None) or "55"),
        )
    if strategy == "portfolio-idmom-swing-support":
        if getattr(args, "regime_filter", None):
            regimes = load_regime_states(index_root=args.regime_index_root, symbol=args.regime_index_symbol)
            allowed = allowed_regimes(args.regime_filter)
            return lambda: IntradayMomentumSwingSupportPortfolioStrategy(
                regimes=regimes,
                allowed_regimes=allowed,
            )
        return IntradayMomentumSwingSupportPortfolioStrategy
    if strategy == "a-day-v2":
        return lambda: DefensivePullbackDayStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            pullback_band=_decimal(getattr(args, "pullback_band", None) or "0.006"),
            max_opening_gap=_decimal(getattr(args, "aday_max_opening_gap", None) or "0.05"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "09:05"),
            entry_end=_time(getattr(args, "entry_end", None) or "15:00"),
        )
    if strategy == "confirmed-day-pullback":
        return lambda: ConfirmedPullbackDayStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            pullback_band=_decimal(getattr(args, "pullback_band", None) or "0.006"),
            max_opening_gap=_decimal(getattr(args, "aday_max_opening_gap", None) or "0.05"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "09:05"),
            entry_end=_time(getattr(args, "entry_end", None) or "15:00"),
            reclaim_threshold=_decimal(getattr(args, "aday_reclaim_threshold", None) or "0.002"),
        )
    if strategy == "opening-range-breakout":
        return lambda: OpeningRangeBreakoutDayStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            max_opening_gap=_decimal(getattr(args, "aday_max_opening_gap", None) or "0.05"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "09:31"),
            entry_end=_time(getattr(args, "entry_end", None) or "14:45"),
            range_minutes=getattr(args, "opening_range_minutes", None) or 30,
            breakout_buffer=_decimal(getattr(args, "opening_breakout_buffer", None) or "0.003"),
            max_range_ratio=_decimal(getattr(args, "opening_max_range_ratio", None) or "0.06"),
        )
    if strategy == "intraday-momentum":
        return lambda: IntradayMomentumContinuationStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            max_opening_gap=_decimal(getattr(args, "aday_max_opening_gap", None) or "0.05"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "10:00"),
            entry_end=_time(getattr(args, "entry_end", None) or "14:30"),
            min_day_return=_decimal(getattr(args, "momentum_min_day_return", None) or "0.03"),
            max_day_return=_decimal(getattr(args, "momentum_max_day_return", None) or "0.12"),
            min_vwap_distance=_decimal(getattr(args, "momentum_min_vwap_distance", None) or "0.003"),
        )
    if strategy == "prior-momentum":
        return lambda: PriorMomentumContinuationStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            max_opening_gap=_decimal(getattr(args, "aday_max_opening_gap", None) or "0.05"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "10:00"),
            entry_end=_time(getattr(args, "entry_end", None) or "14:30"),
            min_prior_return=_decimal(getattr(args, "prior_min_return", None) or "0.04"),
            max_prior_return=_decimal(getattr(args, "prior_max_return", None) or "0.15"),
            min_confirm_above_prior_close=_decimal(getattr(args, "prior_confirm_above_close", None) or "0.005"),
        )
    if strategy == "gap-rebound":
        return lambda: GapReboundDayStrategy(
            sma_window=getattr(args, "aday_sma_window", None) or 20,
            atr_window=getattr(args, "aday_atr_window", None) or 14,
            value_window=getattr(args, "aday_value_window", None) or 5,
            min_average_value=_decimal(getattr(args, "aday_min_average_value", None) or "50000000000"),
            min_atr_ratio=_decimal(getattr(args, "aday_min_atr_ratio", None) or "0.03"),
            min_session_value=_decimal(getattr(args, "aday_min_session_value", None) or "0"),
            min_bid_ask_ratio=_decimal(getattr(args, "min_bid_ask_ratio", None) or "2.0"),
            entry_start=_time(getattr(args, "entry_start", None) or "10:00"),
            entry_end=_time(getattr(args, "entry_end", None) or "14:30"),
            min_gap_down=_decimal(getattr(args, "gap_min_down", None) or "0.005"),
            max_gap_down=_decimal(getattr(args, "gap_max_down", None) or "0.04"),
            reclaim_over_prior_close=_decimal(getattr(args, "gap_reclaim_over_prior_close", None) or "0.001"),
            min_vwap_distance=_decimal(getattr(args, "gap_min_vwap_distance", None) or "0"),
        )
    pullback_band = getattr(args, "pullback_band", None)
    min_bid_ask_ratio = getattr(args, "min_bid_ask_ratio", None)
    entry_start = getattr(args, "entry_start", None)
    entry_end = getattr(args, "entry_end", None)
    entry_mode = getattr(args, "entry_mode", None)
    require_above_vwap = bool(getattr(args, "require_above_vwap", False))
    impulse_threshold = getattr(args, "impulse_threshold", None)
    min_impulse_volume = getattr(args, "min_impulse_volume", None)
    impulse_volume_window = getattr(args, "impulse_volume_window", None)
    impulse_volume_multiple = getattr(args, "impulse_volume_multiple", None)
    if (
        pullback_band is None
        and min_bid_ask_ratio is None
        and entry_start is None
        and entry_end is None
        and entry_mode is None
        and strategy is None
        and not require_above_vwap
        and impulse_threshold is None
        and min_impulse_volume is None
        and impulse_volume_window is None
        and impulse_volume_multiple is None
    ):
        return None
    return lambda: VwapFirstPullbackStrategy(
        pullback_band=_decimal(pullback_band or "0.005"),
        min_bid_ask_ratio=_decimal(min_bid_ask_ratio or "2.0"),
        entry_start=_time(entry_start) if entry_start else None,
        entry_end=_time(entry_end) if entry_end else None,
        entry_mode=entry_mode or "pullback",
        require_above_vwap=require_above_vwap,
        impulse_threshold=_decimal(impulse_threshold or "0.01"),
        min_impulse_volume=min_impulse_volume or 3000,
        impulse_volume_window=impulse_volume_window or 0,
        impulse_volume_multiple=_decimal(impulse_volume_multiple or "0"),
    )


def _apply_regime_filter(strategy_factory, args: argparse.Namespace):
    policy = getattr(args, "regime_filter", None)
    if not policy:
        return strategy_factory
    if getattr(args, "strategy", None) == "portfolio-idmom-swing-support":
        return strategy_factory
    inner_factory = strategy_factory or VwapFirstPullbackStrategy
    regimes = load_regime_states(index_root=args.regime_index_root, symbol=args.regime_index_symbol)
    allowed = allowed_regimes(policy)
    return lambda: RegimeFilteredStrategy(
        inner_factory,
        regimes=regimes,
        allowed_regimes=allowed,
    )


def _apply_relative_strength_filter(strategy_factory, args: argparse.Namespace):
    threshold = getattr(args, "min_relative_strength", None)
    if not threshold:
        return strategy_factory
    inner_factory = strategy_factory or VwapFirstPullbackStrategy
    index_bars = load_index_bars(index_root=args.regime_index_root, symbol=args.regime_index_symbol)
    return lambda: RelativeStrengthFilteredStrategy(
        inner_factory,
        index_bars=index_bars,
        min_relative_return=_decimal(threshold),
    )


def _time(value: str):
    return datetime.strptime(value, "%H:%M").time()


def _csv_symbols(paths: list[Path], symbols: list[str] | None) -> list[str]:
    if symbols is None:
        return [path.stem for path in paths]
    if len(symbols) != len(paths):
        raise ValueError("--symbol count must match --path count")
    return symbols


def _unique_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
