from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv
from zurini.data.csv_quality import discover_daishin_csv_paths
from zurini.market import Bar

KST = ZoneInfo("Asia/Seoul")
DEFAULT_GRID_START = time(9, 1)
DEFAULT_GRID_END = time(15, 30)
CALENDAR_VERSION = "observed-session-v1"
# This profiler validates intra-day minute completeness for days with at least
# one observed bar. A full missing trading day still needs a calendar day-set
# gate before index coverage can be treated as final promotion evidence.
SPECIAL_SESSIONS = {
    "2025-11-13": (time(10, 1), time(16, 30)),
    "2026-01-02": (time(10, 1), time(15, 30)),
}


@dataclass(frozen=True)
class CoverageResult:
    path: str
    symbol: str
    status: str
    class_mode: str
    observed_minutes: int
    expected_session_minutes: int
    coverage_ratio: float
    missing_minutes_count: int
    longest_missing_run: int
    missing_edge_minutes: int
    out_of_session_count: int
    zero_volume_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CoverageSummary:
    root: str
    class_mode: str
    calendar_version: str
    file_count: int
    ok_count: int
    error_count: int
    accepted_count: int
    acceptance_status: str
    observed_minutes: int
    expected_session_minutes: int
    coverage_ratio: float
    missing_minutes_count: int
    longest_missing_run: int
    missing_edge_minutes: int
    out_of_session_count: int
    zero_volume_count: int
    results: list[CoverageResult]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [result.as_dict() for result in self.results]
        return payload


def profile_csv_coverage(
    root: Path | str,
    *,
    class_mode: str,
    source: str = "sample",
    periods: list[str] | None = None,
    limit_files: int | None = None,
    progress_every: int = 0,
    session_start: time = DEFAULT_GRID_START,
    session_end: time = DEFAULT_GRID_END,
    session_timezone: ZoneInfo = KST,
) -> CoverageSummary:
    if class_mode not in {"index-grid", "stock-sparse"}:
        raise ValueError("class_mode must be 'index-grid' or 'stock-sparse'")
    root = Path(root)
    period_filter = set(periods or [])
    paths = _coverage_paths(root, period_filter=period_filter)
    if limit_files is not None:
        paths = paths[:limit_files]
    results = []
    for index, path in enumerate(paths, start=1):
        results.append(
            _profile_one(
                path,
                class_mode=class_mode,
                source=source,
                session_start=session_start,
                session_end=session_end,
                session_timezone=session_timezone,
            )
        )
        if progress_every and (index == 1 or index % progress_every == 0 or index == len(paths)):
            print(f"[coverage] processed={index}/{len(paths)} path={path}", file=sys.stderr, flush=True)
    ok_results = [result for result in results if not result.error]
    accepted = [result for result in ok_results if result.status == "accepted"]
    expected = sum(result.expected_session_minutes for result in ok_results)
    observed = sum(result.observed_minutes for result in ok_results)
    return CoverageSummary(
        root=str(root),
        class_mode=class_mode,
        calendar_version=CALENDAR_VERSION,
        file_count=len(results),
        ok_count=len(ok_results),
        error_count=len(results) - len(ok_results),
        accepted_count=len(accepted),
        acceptance_status="accepted" if results and len(accepted) == len(results) else "review-required",
        observed_minutes=observed,
        expected_session_minutes=expected,
        coverage_ratio=_ratio(observed, expected),
        missing_minutes_count=sum(result.missing_minutes_count for result in ok_results),
        longest_missing_run=max((result.longest_missing_run for result in ok_results), default=0),
        missing_edge_minutes=sum(result.missing_edge_minutes for result in ok_results),
        out_of_session_count=sum(result.out_of_session_count for result in ok_results),
        zero_volume_count=sum(result.zero_volume_count for result in ok_results),
        results=results,
    )


def _profile_one(
    path: Path,
    *,
    class_mode: str,
    source: str,
    session_start: time,
    session_end: time,
    session_timezone: ZoneInfo,
) -> CoverageResult:
    try:
        bars = load_daishin_minute_csv(path, source=source)
        quality = build_csv_quality_report(bars, source_path=path, source=source)
        metrics = _coverage_metrics(bars, session_start=session_start, session_end=session_end, session_timezone=session_timezone)
        strict_passed = (
            metrics["observed_minutes"] > 0
            and quality.duplicate_timestamp_count == 0
            and metrics["out_of_session_count"] == 0
            and metrics["missing_minutes_count"] == 0
            and metrics["missing_edge_minutes"] == 0
        )
        sparse_passed = (
            metrics["observed_minutes"] > 0
            and quality.duplicate_timestamp_count == 0
            and metrics["out_of_session_count"] == 0
        )
        accepted = strict_passed if class_mode == "index-grid" else sparse_passed
        return CoverageResult(
            path=str(path),
            symbol=quality.symbol,
            status="accepted" if accepted else "review-required",
            class_mode=class_mode,
            observed_minutes=metrics["observed_minutes"],
            expected_session_minutes=metrics["expected_session_minutes"],
            coverage_ratio=_ratio(metrics["observed_minutes"], metrics["expected_session_minutes"]),
            missing_minutes_count=metrics["missing_minutes_count"],
            longest_missing_run=metrics["longest_missing_run"],
            missing_edge_minutes=metrics["missing_edge_minutes"],
            out_of_session_count=metrics["out_of_session_count"],
            zero_volume_count=quality.zero_volume_count,
            first_timestamp=quality.first_timestamp,
            last_timestamp=quality.last_timestamp,
        )
    except Exception as exc:
        return CoverageResult(
            path=str(path),
            symbol=path.stem,
            status="error",
            class_mode=class_mode,
            observed_minutes=0,
            expected_session_minutes=0,
            coverage_ratio=0.0,
            missing_minutes_count=0,
            longest_missing_run=0,
            missing_edge_minutes=0,
            out_of_session_count=0,
            zero_volume_count=0,
            first_timestamp=None,
            last_timestamp=None,
            error=str(exc),
        )


def _coverage_metrics(
    bars: list[Bar],
    *,
    session_start: time,
    session_end: time,
    session_timezone: ZoneInfo,
) -> dict[str, int]:
    by_symbol_day: dict[tuple[str, object], set[datetime]] = defaultdict(set)
    out_of_session = 0
    for bar in bars:
        local = _localize(bar.timestamp, session_timezone)
        day_start, day_end = _session_window(local, session_start=session_start, session_end=session_end)
        if not day_start <= local.time() <= day_end:
            out_of_session += 1
            continue
        by_symbol_day[(bar.symbol, local.date())].add(local)

    observed = 0
    expected = 0
    missing = 0
    longest_missing_run = 0
    edge_missing = 0
    for timestamps in by_symbol_day.values():
        expected_grid = _expected_grid(
            min(timestamps),
            session_start=session_start,
            session_end=session_end,
        )
        observed += len(timestamps)
        expected += len(expected_grid)
        missing_flags = [timestamp not in timestamps for timestamp in expected_grid]
        missing += sum(1 for item in missing_flags if item)
        longest_missing_run = max(longest_missing_run, _longest_true_run(missing_flags))
        if expected_grid and expected_grid[0] not in timestamps:
            edge_missing += 1
        if expected_grid and expected_grid[-1] not in timestamps:
            edge_missing += 1

    return {
        "observed_minutes": observed,
        "expected_session_minutes": expected,
        "missing_minutes_count": missing,
        "longest_missing_run": longest_missing_run,
        "missing_edge_minutes": edge_missing,
        "out_of_session_count": out_of_session,
    }


def _expected_grid(anchor: datetime, *, session_start: time, session_end: time) -> list[datetime]:
    day_start, day_end = _session_window(anchor, session_start=session_start, session_end=session_end)
    start = anchor.replace(hour=day_start.hour, minute=day_start.minute, second=0, microsecond=0)
    end = anchor.replace(hour=day_end.hour, minute=day_end.minute, second=0, microsecond=0)
    result = []
    current = start
    while current <= end:
        result.append(current)
        current += timedelta(minutes=1)
    return result


def _session_window(anchor: datetime, *, session_start: time, session_end: time) -> tuple[time, time]:
    return SPECIAL_SESSIONS.get(anchor.date().isoformat(), (session_start, session_end))


def _localize(timestamp: datetime, session_timezone: ZoneInfo) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=session_timezone)
    return timestamp.astimezone(session_timezone)


def _longest_true_run(values: list[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _period_key(path: Path) -> str:
    parent = path.parent.name
    return parent if len(parent) == 6 and parent.isdigit() else ""


def _coverage_paths(root: Path, *, period_filter: set[str]) -> list[Path]:
    if not period_filter:
        return discover_daishin_csv_paths(root)
    if root.is_file():
        return [root] if _period_key(root) in period_filter else []
    paths: list[Path] = []
    for period in sorted(period_filter):
        period_dir = root / period
        if period_dir.exists():
            paths.extend(sorted(path for path in period_dir.glob("*.csv") if path.is_file()))
    return paths
