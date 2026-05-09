from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
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
