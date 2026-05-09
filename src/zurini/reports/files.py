from __future__ import annotations

import csv
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from zurini.market import BacktestReport, Trade


def write_backtest_outputs(
    *,
    report: BacktestReport,
    trades: list[Trade],
    output_dir: Path,
    symbols: list[str],
    inserted_rows: int,
    title: str = "PROJECT_ZURINI phase-1 dummy multi-symbol backtest",
    extra: dict[str, Any] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "report.json",
        "csv": output_dir / "trades.csv",
        "txt": output_dir / "summary.txt",
    }
    _write_report_json(paths["json"], report, trades, symbols, inserted_rows, extra=extra)
    _write_trades_csv(paths["csv"], trades)
    _write_summary_txt(paths["txt"], report, symbols, inserted_rows, title)
    return paths


def _write_report_json(
    path: Path,
    report: BacktestReport,
    trades: list[Trade],
    symbols: list[str],
    inserted_rows: int,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "symbols": symbols,
        "inserted_rows": inserted_rows,
        "report": _json_safe(asdict(report)),
        "trades": [_json_safe(asdict(trade)) for trade in trades],
    }
    if extra:
        payload.update(_json_safe(extra))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_trades_csv(path: Path, trades: list[Trade]) -> None:
    fieldnames = [
        "symbol",
        "entry_time",
        "exit_time",
        "entry_price",
        "exit_price",
        "quantity",
        "gross_pnl",
        "net_pnl",
        "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            writer.writerow(_json_safe(asdict(trade)))


def _write_summary_txt(
    path: Path,
    report: BacktestReport,
    symbols: list[str],
    inserted_rows: int,
    title: str,
) -> None:
    lines = [
        title,
        f"symbols: {', '.join(symbols)}",
        f"inserted_rows: {inserted_rows}",
        f"trade_count: {report.trade_count}",
        f"gross_pnl: {report.gross_pnl}",
        f"net_pnl: {report.net_pnl}",
        f"max_drawdown: {report.max_drawdown}",
        f"start_equity: {report.start_equity}",
        f"end_equity: {report.end_equity}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
