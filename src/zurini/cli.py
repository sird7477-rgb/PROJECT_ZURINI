from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.api_smoke import build_api_smoke_plan, run_api_smoke_network
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
    generate_symbol_metadata,
    get_large_dummy_profile,
    iter_large_dummy_index_bars,
    iter_large_dummy_market_bars,
    summarize_large_dummy_profile,
)
from zurini.market import Bar
from zurini.observability import append_event_jsonl, build_event
from zurini.observed_sessions import build_observed_session_plan, write_observed_session_plan
from zurini.operations import build_local_ops_status, write_local_ops_status
from zurini.strategies.baseline import VwapFirstPullbackStrategy
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
    if args.command == "rehearse-large-dummy":
        return run_rehearse_large_dummy_command(args)
    if args.command == "ops-status":
        return run_ops_status_command(args)
    if args.command == "record-event":
        return run_record_event_command(args)
    if args.command == "chaos-plan":
        return run_chaos_plan_command(args)
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
    backtest_csv.add_argument("--profit-target", help="override config backtest.profit_target")
    backtest_csv.add_argument("--hard-stop", help="override config backtest.hard_stop")
    backtest_csv.add_argument("--intrabar-policy", choices=["close-only", "conservative"], help="override config backtest.intrabar_policy")
    backtest_csv.add_argument(
        "--ambiguous-intrabar-policy",
        choices=["stop-first"],
        help="override config backtest.ambiguous_intrabar_policy",
    )
    backtest_csv.add_argument("--pullback-band", help="override VWAP pullback band")
    backtest_csv.add_argument("--min-bid-ask-ratio", help="override VWAP pressure threshold")
    backtest_csv.add_argument("--output-dir", type=Path, default=Path("reports/sample-backtest"))
    backtest_csv.add_argument("--keep-db", action="store_true", help="do not reset market_bars before loading")
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
                "profit_target": str(backtest_config.profit_target),
                "hard_stop": str(backtest_config.hard_stop),
                "fee_rate": str(backtest_config.fee_rate),
                "slippage_rate": str(backtest_config.slippage_rate),
                "intrabar_policy": backtest_config.intrabar_policy,
                "ambiguous_intrabar_policy": backtest_config.ambiguous_intrabar_policy,
                "pullback_band": str(_decimal(args.pullback_band)) if args.pullback_band else "default",
                "min_bid_ask_ratio": str(_decimal(args.min_bid_ask_ratio)) if args.min_bid_ask_ratio else "default",
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
        run_api_smoke_network(symbol=args.symbol)
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
    return 0 if payload["status"] == "ready" or not args.allow_network else 1


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
            profit_target=_decimal(backtest.get("profit_target", "0.03")),
            hard_stop=_decimal(backtest.get("hard_stop", "-0.03")),
            day_end_exit=_bool(backtest.get("day_end_exit", True)),
            intrabar_policy=str(backtest.get("intrabar_policy", "close-only")),
            ambiguous_intrabar_policy=str(backtest.get("ambiguous_intrabar_policy", "stop-first")),
            max_holding_minutes=(
                int(backtest["max_holding_minutes"])
                if backtest.get("max_holding_minutes") is not None
                else None
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


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _csv_paths(paths: list[Path], roots: list[Path], path_lists: list[Path] | None = None) -> list[Path]:
    resolved = list(paths)
    for path_list in path_lists or []:
        resolved.extend(read_path_list(path_list))
    for root in roots:
        resolved.extend(discover_daishin_csv_paths(root))
    if not resolved:
        raise ValueError("at least one --path or --root is required")
    return list(dict.fromkeys(resolved))


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
        start_equity=config.start_equity,
        fee_rate=config.fee_rate,
        slippage_rate=config.slippage_rate,
        profit_target=_decimal(args.profit_target) if getattr(args, "profit_target", None) else config.profit_target,
        hard_stop=_decimal(args.hard_stop) if getattr(args, "hard_stop", None) else config.hard_stop,
        day_end_exit=config.day_end_exit,
        max_holding_minutes=config.max_holding_minutes,
        intrabar_policy=getattr(args, "intrabar_policy", None) or config.intrabar_policy,
        ambiguous_intrabar_policy=getattr(args, "ambiguous_intrabar_policy", None) or config.ambiguous_intrabar_policy,
    )


def _strategy_factory_from_args(args: argparse.Namespace):
    pullback_band = getattr(args, "pullback_band", None)
    min_bid_ask_ratio = getattr(args, "min_bid_ask_ratio", None)
    if pullback_band is None and min_bid_ask_ratio is None:
        return None
    return lambda: VwapFirstPullbackStrategy(
        pullback_band=_decimal(pullback_band or "0.005"),
        min_bid_ask_ratio=_decimal(min_bid_ask_ratio or "2.0"),
    )


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
