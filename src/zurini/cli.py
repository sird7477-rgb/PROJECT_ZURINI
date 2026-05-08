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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
