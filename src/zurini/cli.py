from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from zurini.backtest.engine import BacktestConfig, run_backtest
from zurini.data import db
from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv
from zurini.data.csv_quality import discover_daishin_csv_paths, scan_daishin_csv_tree
from zurini.data.dummy import generate_dummy_bars
from zurini.market import Bar
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
    backtest_csv.add_argument("--root", type=Path, action="append", default=[], help="CSV file or directory tree")
    backtest_csv.add_argument("--symbol", action="append", help="symbol override matching each --path; defaults to file stems")
    backtest_csv.add_argument("--source", default="sample")
    backtest_csv.add_argument("--limit-files", type=int, help="limit discovered CSV files for smoke runs")
    backtest_csv.add_argument("--output-dir", type=Path, default=Path("reports/sample-backtest"))
    backtest_csv.add_argument("--keep-db", action="store_true", help="do not reset market_bars before loading")

    scan_csv = subparsers.add_parser("scan-csv", help="scan Daishin/CYBOS CSV files without loading Postgres")
    scan_csv.add_argument("--root", type=Path, required=True, help="CSV file or directory tree")
    scan_csv.add_argument("--source", default="sample")
    scan_csv.add_argument("--output", type=Path, default=Path("reports/csv-scan.json"))
    return parser


def run_backtest_command(args: argparse.Namespace) -> int:
    config = load_config(args.config, output_dir=args.output_dir)
    bars = generate_configured_dummy_bars(config.dummy)

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
    paths = _csv_paths(args.path, args.root)
    if args.limit_files is not None:
        paths = paths[: args.limit_files]
    symbols = _csv_symbols(paths, args.symbol)
    report_symbols = _unique_preserve_order(symbols)
    bars: list[Bar] = []
    quality_reports = []
    for path, symbol in zip(paths, symbols, strict=True):
        loaded = load_daishin_minute_csv(path, symbol=symbol, source=args.source)
        bars.extend(loaded)
        quality_reports.append(build_csv_quality_report(loaded, source_path=path, symbol=symbol, source=args.source))

    if args.keep_db:
        db.apply_schema()
    else:
        db.reset_market_bars()
    inserted = db.insert_bars(bars)

    loaded_from_db: list[Bar] = []
    for symbol in report_symbols:
        loaded_from_db.extend(db.fetch_bars(symbol))

    report, trades = run_backtest(loaded_from_db, config=config.backtest)
    outputs = write_backtest_outputs(
        report=report,
        trades=trades,
        output_dir=args.output_dir,
        symbols=report_symbols,
        inserted_rows=inserted,
        title="PROJECT_ZURINI phase-1 CSV sample backtest",
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


def run_scan_csv_command(args: argparse.Namespace) -> int:
    summary = scan_daishin_csv_tree(args.root, source=args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"root={summary.root}")
    print(f"file_count={summary.file_count}")
    print(f"ok_count={summary.ok_count}")
    print(f"error_count={summary.error_count}")
    print(f"success_rate={summary.success_rate:.4f}")
    print(f"symbol_count={summary.symbol_count}")
    print(f"period_count={summary.period_count}")
    print(f"row_count={summary.row_count}")
    print(f"gap_count={summary.gap_count}")
    print(f"report={args.output}")
    return 1 if summary.error_count else 0


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


def _csv_paths(paths: list[Path], roots: list[Path]) -> list[Path]:
    resolved = list(paths)
    for root in roots:
        resolved.extend(discover_daishin_csv_paths(root))
    if not resolved:
        raise ValueError("at least one --path or --root is required")
    return list(dict.fromkeys(resolved))


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
