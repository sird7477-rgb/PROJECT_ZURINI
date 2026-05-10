from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from zurini.data.calendar import TradingCalendar, load_trading_calendar
from zurini.data.csv_loader import load_daishin_minute_csv


@dataclass(frozen=True)
class ObservedSessionDay:
    trading_day: str
    start_time: str
    end_time: str
    index_symbol_count: int
    expected_minutes: int
    observed_minutes_per_symbol: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObservedSessionBlock:
    name: str
    start_date: str
    end_date: str
    trading_day_count: int
    periods: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ObservedSessionPlan:
    index_root: str
    stock_root: str
    output_dir: str
    index_symbols: list[str]
    accepted_day_count: int
    rejected_day_count: int
    blocks: list[ObservedSessionBlock]
    selected_block: ObservedSessionBlock | None
    selected_symbols: list[str]
    path_list: list[str]
    path_list_file: str
    plan_file: str
    recommended_command: list[str]
    boundary: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocks"] = [block.as_dict() for block in self.blocks]
        payload["selected_block"] = self.selected_block.as_dict() if self.selected_block else None
        return payload


def build_observed_session_plan(
    *,
    index_root: Path,
    stock_root: Path,
    output_dir: Path,
    limit_symbols: int,
    min_trading_days: int = 20,
    select_block: str = "",
) -> ObservedSessionPlan:
    index_root = Path(index_root)
    stock_root = Path(stock_root)
    output_dir = Path(output_dir)
    sessions, rejected_count, index_symbols = _accepted_index_sessions(index_root)
    blocks = _contiguous_blocks(sessions, min_trading_days=min_trading_days)
    selected = _select_block(blocks, select_block)
    selected_symbols = _common_symbols(stock_root, selected.periods if selected else [])[:limit_symbols]
    path_list = [
        str(stock_root / period / f"{symbol}.csv")
        for period in (selected.periods if selected else [])
        for symbol in selected_symbols
    ]
    path_list_file = output_dir / "observed-backtest-paths.txt"
    plan_file = output_dir / "observed-session-plan.json"
    command = [
        ".venv/bin/python",
        "-m",
        "zurini.cli",
        "backtest-csv",
        "--config",
        "config/phase2-backtest-conservative.toml",
        "--source",
        "daishin-historical",
        "--path-list",
        str(path_list_file),
        "--trade-continuity-mode",
        "exact-bar",
        "--output-dir",
        str(output_dir / "backtest"),
    ]
    if selected:
        command.extend(["--start-date", selected.start_date, "--end-date", selected.end_date])
    return ObservedSessionPlan(
        index_root=str(index_root),
        stock_root=str(stock_root),
        output_dir=str(output_dir),
        index_symbols=index_symbols,
        accepted_day_count=len(sessions),
        rejected_day_count=rejected_count,
        blocks=blocks,
        selected_block=selected,
        selected_symbols=selected_symbols,
        path_list=path_list,
        path_list_file=str(path_list_file),
        plan_file=str(plan_file),
        recommended_command=command,
        boundary="observed index sessions only; not official-calendar-certified for field-test promotion",
    )


def _select_block(blocks: list[ObservedSessionBlock], select_block: str) -> ObservedSessionBlock | None:
    if not select_block:
        return max(blocks, key=lambda block: block.trading_day_count, default=None)
    for block in blocks:
        if block.name == select_block:
            return block
    return None


def write_observed_session_plan(plan: ObservedSessionPlan) -> dict[str, Path]:
    output_dir = Path(plan.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = Path(plan.plan_file)
    path_list_path = Path(plan.path_list_file)
    plan_path.write_text(json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path_list_path.write_text("\n".join(plan.path_list) + ("\n" if plan.path_list else ""), encoding="utf-8")
    return {"plan": plan_path, "path_list": path_list_path}


def _accepted_index_sessions(index_root: Path) -> tuple[list[ObservedSessionDay], int, list[str]]:
    files = sorted(index_root.glob("*/*.csv"))
    by_symbol_day: dict[str, dict[date, set[datetime]]] = {}
    for path in files:
        symbol = path.stem
        symbol_days = by_symbol_day.setdefault(symbol, {})
        for bar in load_daishin_minute_csv(path, source="daishin-historical"):
            local_day = bar.timestamp.date()
            symbol_days.setdefault(local_day, set()).add(bar.timestamp)
    index_symbols = sorted(by_symbol_day)
    all_days = sorted({day for symbol_days in by_symbol_day.values() for day in symbol_days})
    accepted: list[ObservedSessionDay] = []
    rejected = 0
    for trading_day in all_days:
        day_sets = [by_symbol_day[symbol].get(trading_day, set()) for symbol in index_symbols]
        if any(not timestamps for timestamps in day_sets):
            rejected += 1
            continue
        starts = {min(timestamps).time() for timestamps in day_sets}
        ends = {max(timestamps).time() for timestamps in day_sets}
        counts = {len(timestamps) for timestamps in day_sets}
        if len(starts) != 1 or len(ends) != 1 or len(counts) != 1:
            rejected += 1
            continue
        first_set = day_sets[0]
        if any(timestamps != first_set for timestamps in day_sets[1:]):
            rejected += 1
            continue
        if not _is_continuous_minute_grid(first_set):
            rejected += 1
            continue
        accepted.append(
            ObservedSessionDay(
                trading_day=trading_day.isoformat(),
                start_time=next(iter(starts)).strftime("%H:%M"),
                end_time=next(iter(ends)).strftime("%H:%M"),
                index_symbol_count=len(index_symbols),
                expected_minutes=next(iter(counts)),
                observed_minutes_per_symbol=next(iter(counts)),
            )
        )
    return accepted, rejected, index_symbols


def _is_continuous_minute_grid(timestamps: set[datetime]) -> bool:
    ordered = sorted(timestamps)
    if not ordered:
        return False
    expected_count = int((ordered[-1] - ordered[0]).total_seconds() // 60) + 1
    if expected_count != len(ordered):
        return False
    return all(current - previous == timedelta(minutes=1) for previous, current in zip(ordered, ordered[1:]))


def _contiguous_blocks(
    sessions: list[ObservedSessionDay],
    *,
    min_trading_days: int,
    calendar: TradingCalendar | None = None,
) -> list[ObservedSessionBlock]:
    if not sessions:
        return []
    calendar = calendar or load_trading_calendar()
    blocks: list[list[ObservedSessionDay]] = [[sessions[0]]]
    previous = date.fromisoformat(sessions[0].trading_day)
    for session in sessions[1:]:
        current = date.fromisoformat(session.trading_day)
        if _has_no_missing_trading_day(previous, current, calendar):
            blocks[-1].append(session)
        else:
            blocks.append([session])
        previous = current
    result = []
    for index, block in enumerate(blocks, start=1):
        if len(block) < min_trading_days:
            continue
        start = block[0].trading_day
        end = block[-1].trading_day
        periods = sorted({day.trading_day[:7].replace("-", "") for day in block})
        result.append(
            ObservedSessionBlock(
                name=f"observed-block-{index}",
                start_date=start,
                end_date=end,
                trading_day_count=len(block),
                periods=periods,
            )
        )
    return result


def _has_no_missing_trading_day(previous: date, current: date, calendar: TradingCalendar) -> bool:
    cursor = previous + timedelta(days=1)
    while cursor < current:
        if calendar.is_trading_day(cursor):
            return False
        cursor += timedelta(days=1)
    return True


def _common_symbols(stock_root: Path, periods: list[str]) -> list[str]:
    if not periods:
        return []
    per_period = []
    for period in periods:
        period_dir = stock_root / period
        per_period.append({path.stem for path in period_dir.glob("*.csv") if path.is_file()})
    return sorted(set.intersection(*per_period)) if per_period else []
