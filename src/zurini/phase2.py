from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MonthlyDataset:
    period: str
    path: str
    file_count: int
    symbol_count: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonthlyRehearsalPlan:
    root: str
    output_dir: str
    current_yyyymm: str
    limit_symbols: int
    months: list[MonthlyDataset]
    selected_months: list[str]
    excluded_months: list[str]
    selected_symbols: list[str]
    path_list: list[str]
    path_list_file: str
    plan_file: str
    recommended_command: list[str]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["months"] = [month.as_dict() for month in self.months]
        return payload


@dataclass(frozen=True)
class BacktestRunSummary:
    report_path: str
    symbol_count: int
    inserted_rows: int
    trade_count: int
    net_pnl: str
    valid_trades: int
    invalid_trades: int
    valid_net_pnl: str
    invalid_net_pnl: str
    continuity_status: str
    exit_reasons: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Phase2BatchSummary:
    purpose: str
    interpretation_boundary: str
    report_count: int
    total_inserted_rows: int
    total_trade_count: int
    total_net_pnl: str
    total_valid_trades: int
    total_invalid_trades: int
    total_valid_net_pnl: str
    total_invalid_net_pnl: str
    continuity_status: str
    invalid_trade_ratio: str
    invalid_net_pnl_ratio: str
    optimization_gate_status: str
    exit_reasons: dict[str, int]
    reports: list[BacktestRunSummary]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reports"] = [report.as_dict() for report in self.reports]
        return payload


def build_monthly_rehearsal_plan(
    root: Path | str,
    *,
    output_dir: Path | str,
    current_yyyymm: str | None = None,
    limit_symbols: int = 100,
    requested_months: list[str] | None = None,
) -> MonthlyRehearsalPlan:
    root = Path(root)
    output_dir = Path(output_dir)
    if not root.exists():
        raise FileNotFoundError(f"minute-bar root does not exist: {root}")
    if limit_symbols < 1:
        raise ValueError("--limit-symbols must be greater than zero")

    current = current_yyyymm or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m")
    months = _discover_months(root, current_yyyymm=current)
    requested = set(requested_months or [])
    unknown = sorted(requested - {month.period for month in months})
    if unknown:
        raise ValueError(f"requested months are missing: {','.join(unknown)}")

    completed = {month.period: month for month in months if month.status == "completed-candidate"}
    if requested:
        unavailable = sorted(period for period in requested if period not in completed)
        if unavailable:
            raise ValueError(f"requested months are not completed candidates: {','.join(unavailable)}")
        selected_periods = sorted(requested)
        _assert_contiguous(selected_periods)
    else:
        selected_periods = _latest_contiguous_periods(sorted(completed))

    excluded_months = [month.period for month in months if month.period not in set(selected_periods)]
    selected_symbols = _common_symbols(root, selected_periods)[:limit_symbols]
    path_list = [
        str(root / period / f"{symbol}.csv")
        for period in selected_periods
        for symbol in selected_symbols
    ]

    path_list_file = output_dir / "backtest-paths.txt"
    plan_file = output_dir / "monthly-plan.json"
    command = [
        ".venv/bin/python",
        "-m",
        "zurini.cli",
        "backtest-csv",
        "--source",
        "daishin-historical",
        "--path-list",
        str(path_list_file),
        "--trade-continuity-mode",
        "exact-bar",
        "--output-dir",
        str(output_dir / "backtest"),
    ]
    return MonthlyRehearsalPlan(
        root=str(root),
        output_dir=str(output_dir),
        current_yyyymm=current,
        limit_symbols=limit_symbols,
        months=months,
        selected_months=selected_periods,
        excluded_months=excluded_months,
        selected_symbols=selected_symbols,
        path_list=path_list,
        path_list_file=str(path_list_file),
        plan_file=str(plan_file),
        recommended_command=command,
    )


def write_monthly_rehearsal_plan(plan: MonthlyRehearsalPlan) -> dict[str, Path]:
    output_dir = Path(plan.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = Path(plan.plan_file)
    path_list_path = Path(plan.path_list_file)
    plan_path.write_text(json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path_list_path.write_text("\n".join(plan.path_list) + ("\n" if plan.path_list else ""), encoding="utf-8")
    return {"plan": plan_path, "path_list": path_list_path}


def read_path_list(path: Path | str) -> list[Path]:
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            items.append(Path(stripped))
    return items


def discover_report_paths(paths: list[Path], roots: list[Path]) -> list[Path]:
    discovered = list(paths)
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(f"report root does not exist: {root}")
        if root.is_dir():
            discovered.extend(sorted(path for path in root.rglob("report.json") if path.is_file()))
        else:
            discovered.append(root)
    if not discovered:
        raise ValueError("at least one --report or --root is required")
    return list(dict.fromkeys(discovered))


def build_phase2_batch_summary(report_paths: list[Path]) -> Phase2BatchSummary:
    if not report_paths:
        raise ValueError("at least one report path is required")
    reports = [_summarize_report(path) for path in report_paths]
    exit_reasons: dict[str, int] = {}
    for report in reports:
        for reason, count in report.exit_reasons.items():
            exit_reasons[reason] = exit_reasons.get(reason, 0) + count
    total_invalid_trades = sum(report.invalid_trades for report in reports)
    total_trade_count = sum(report.trade_count for report in reports)
    total_net_pnl = sum((_decimal(report.net_pnl) for report in reports), Decimal("0"))
    total_invalid_net_pnl = sum((_decimal(report.invalid_net_pnl) for report in reports), Decimal("0"))
    all_reports_passed = all(report.continuity_status == "passed" for report in reports)
    continuity_status = "passed" if total_invalid_trades == 0 and all_reports_passed else "review-required"
    invalid_trade_ratio = _ratio(total_invalid_trades, total_trade_count)
    invalid_net_pnl_ratio = _net_pnl_ratio(total_invalid_net_pnl, total_net_pnl)
    # Keep the gate defensive even if an upstream report mislabels continuity.
    optimization_gate_status = (
        "passed"
        if continuity_status == "passed" and invalid_trade_ratio == Decimal("0") and invalid_net_pnl_ratio == Decimal("0")
        else "blocked"
    )
    return Phase2BatchSummary(
        purpose="phase-2 backtest batch operational summary",
        interpretation_boundary=(
            "This summary checks pipeline and data continuity evidence; it is not a strategy profitability verdict."
        ),
        report_count=len(reports),
        total_inserted_rows=sum(report.inserted_rows for report in reports),
        total_trade_count=total_trade_count,
        total_net_pnl=str(total_net_pnl),
        total_valid_trades=sum(report.valid_trades for report in reports),
        total_invalid_trades=total_invalid_trades,
        total_valid_net_pnl=str(sum((_decimal(report.valid_net_pnl) for report in reports), Decimal("0"))),
        total_invalid_net_pnl=str(total_invalid_net_pnl),
        continuity_status=continuity_status,
        invalid_trade_ratio=_format_decimal(invalid_trade_ratio),
        invalid_net_pnl_ratio=_format_decimal(invalid_net_pnl_ratio),
        optimization_gate_status=optimization_gate_status,
        exit_reasons=exit_reasons,
        reports=reports,
    )


def write_phase2_batch_summary(summary: Phase2BatchSummary, *, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_markdown.write_text(_batch_summary_markdown(summary), encoding="utf-8")


def _summarize_report(path: Path) -> BacktestRunSummary:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require_report_fields(path, payload)
    report = payload.get("report", {})
    trades = payload.get("trades", [])
    continuity = payload.get("trade_continuity", {})
    continuity_summary = payload.get("trade_continuity_summary", {})
    trade_count = int(report.get("trade_count", len(trades)))
    return BacktestRunSummary(
        report_path=str(path),
        symbol_count=len(payload.get("symbols", [])),
        inserted_rows=int(payload.get("inserted_rows", 0)),
        trade_count=trade_count,
        net_pnl=str(report.get("net_pnl", "0")),
        valid_trades=int(continuity_summary.get("valid_trades", trade_count)),
        invalid_trades=int(continuity_summary.get("invalid_trades", 0)),
        valid_net_pnl=str(continuity_summary.get("valid_net_pnl", report.get("net_pnl", "0"))),
        invalid_net_pnl=str(continuity_summary.get("invalid_net_pnl", "0")),
        continuity_status=str(continuity.get("status", "unknown")),
        exit_reasons=_exit_reasons(trades),
    )


def _require_report_fields(path: Path, payload: dict[str, Any]) -> None:
    missing = []
    if "symbols" not in payload:
        missing.append("symbols")
    if "inserted_rows" not in payload:
        missing.append("inserted_rows")
    if "trades" not in payload:
        missing.append("trades")
    report = payload.get("report")
    if not isinstance(report, dict):
        missing.append("report")
    else:
        for key in ["trade_count", "net_pnl"]:
            if key not in report:
                missing.append(f"report.{key}")
    if missing:
        raise ValueError(f"report is missing required fields: {path}: {','.join(missing)}")


def _exit_reasons(trades: list[dict[str, Any]]) -> dict[str, int]:
    reasons: dict[str, int] = {}
    for trade in trades:
        reason = str(trade.get("reason", "unknown"))
        reasons[reason] = reasons.get(reason, 0) + 1
    return reasons


def _batch_summary_markdown(summary: Phase2BatchSummary) -> str:
    lines = [
        "# Phase 2 Batch Summary",
        "",
        f"- report_count: {summary.report_count}",
        f"- total_inserted_rows: {summary.total_inserted_rows}",
        f"- total_trade_count: {summary.total_trade_count}",
        f"- total_net_pnl: {summary.total_net_pnl}",
        f"- total_valid_trades: {summary.total_valid_trades}",
        f"- total_invalid_trades: {summary.total_invalid_trades}",
        f"- total_valid_net_pnl: {summary.total_valid_net_pnl}",
        f"- total_invalid_net_pnl: {summary.total_invalid_net_pnl}",
        f"- continuity_status: {summary.continuity_status}",
        f"- invalid_trade_ratio: {summary.invalid_trade_ratio}",
        f"- invalid_net_pnl_ratio: {summary.invalid_net_pnl_ratio}",
        f"- optimization_gate_status: {summary.optimization_gate_status}",
        "",
        "## Exit Reasons",
        "",
    ]
    if summary.exit_reasons:
        lines.extend(f"- {reason}: {count}" for reason, count in sorted(summary.exit_reasons.items()))
    else:
        lines.append("- none: 0")
    lines.extend(["", "## Reports", "", "| report | rows | trades | valid | invalid | net_pnl |", "|---|---:|---:|---:|---:|---:|"])
    for report in summary.reports:
        lines.append(
            "| "
            + " | ".join(
                [
                    report.report_path,
                    str(report.inserted_rows),
                    str(report.trade_count),
                    str(report.valid_trades),
                    str(report.invalid_trades),
                    report.net_pnl,
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return Decimal(numerator) / Decimal(denominator)


def _net_pnl_ratio(invalid_net_pnl: Decimal, total_net_pnl: Decimal) -> Decimal:
    denominator = abs(total_net_pnl) if total_net_pnl != 0 else Decimal("1")
    return abs(invalid_net_pnl) / denominator


def _format_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    formatted = format(value, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _discover_months(root: Path, *, current_yyyymm: str) -> list[MonthlyDataset]:
    months: list[MonthlyDataset] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not _is_yyyymm(child.name):
            continue
        symbols = _symbols_for_month(child)
        if child.name == current_yyyymm:
            status = "collecting-current-month"
        elif not symbols:
            status = "empty"
        elif child.name < current_yyyymm:
            status = "completed-candidate"
        else:
            status = "future"
        months.append(
            MonthlyDataset(
                period=child.name,
                path=str(child),
                file_count=len(symbols),
                symbol_count=len(symbols),
                status=status,
            )
        )
    return months


def _common_symbols(root: Path, periods: list[str]) -> list[str]:
    if not periods:
        return []
    per_month = [set(_symbols_for_month(root / period)) for period in periods]
    return sorted(set.intersection(*per_month)) if per_month else []


def _latest_contiguous_periods(periods: list[str]) -> list[str]:
    if not periods:
        return []
    selected = [periods[-1]]
    expected = _previous_month(periods[-1])
    for period in reversed(periods[:-1]):
        if period != expected:
            break
        selected.append(period)
        expected = _previous_month(period)
    return list(reversed(selected))


def _assert_contiguous(periods: list[str]) -> None:
    for previous, current in zip(periods, periods[1:], strict=False):
        expected = _next_month(previous)
        if current != expected:
            raise ValueError(f"requested months must be contiguous: expected {expected} after {previous}, got {current}")


def _previous_month(period: str) -> str:
    year = int(period[:4])
    month = int(period[4:])
    if month == 1:
        return f"{year - 1}12"
    return f"{year}{month - 1:02d}"


def _next_month(period: str) -> str:
    year = int(period[:4])
    month = int(period[4:])
    if month == 12:
        return f"{year + 1}01"
    return f"{year}{month + 1:02d}"


def _symbols_for_month(month_dir: Path) -> list[str]:
    symbols = []
    with os.scandir(month_dir) as entries:
        for entry in entries:
            if entry.is_file() and entry.name.endswith(".csv"):
                symbols.append(entry.name[:-4])
    return sorted(symbols)


def _is_yyyymm(value: str) -> bool:
    return len(value) == 6 and value.isdigit() and "01" <= value[4:] <= "12"
