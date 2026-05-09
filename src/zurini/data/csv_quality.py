from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv


@dataclass(frozen=True)
class CsvScanResult:
    path: str
    symbol: str
    status: str
    row_count: int
    duplicate_timestamp_count: int
    gap_count: int
    missing_minutes_count: int
    max_gap_minutes: int
    zero_volume_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    error: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CsvScanSummary:
    root: str
    file_count: int
    ok_count: int
    error_count: int
    success_rate: float
    row_count: int
    duplicate_timestamp_count: int
    gap_count: int
    missing_minutes_count: int
    max_gap_minutes: int
    zero_volume_count: int
    symbol_count: int
    period_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    error_paths: list[str]
    results: list[CsvScanResult]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [result.as_dict() for result in self.results]
        return payload


def scan_daishin_csv_tree(root: Path | str, *, source: str = "sample") -> CsvScanSummary:
    root = Path(root)
    paths = discover_daishin_csv_paths(root)
    results = [_scan_one(path, source=source) for path in paths]
    ok_results = [result for result in results if result.status == "ok"]
    first_timestamp = min((result.first_timestamp for result in ok_results if result.first_timestamp), default=None)
    last_timestamp = max((result.last_timestamp for result in ok_results if result.last_timestamp), default=None)
    return CsvScanSummary(
        root=str(root),
        file_count=len(results),
        ok_count=len(ok_results),
        error_count=len(results) - len(ok_results),
        success_rate=(len(ok_results) / len(results)) if results else 0.0,
        row_count=sum(result.row_count for result in ok_results),
        duplicate_timestamp_count=sum(result.duplicate_timestamp_count for result in ok_results),
        gap_count=sum(result.gap_count for result in ok_results),
        missing_minutes_count=sum(result.missing_minutes_count for result in ok_results),
        max_gap_minutes=max((result.max_gap_minutes for result in ok_results), default=0),
        zero_volume_count=sum(result.zero_volume_count for result in ok_results),
        symbol_count=len({result.symbol for result in ok_results}),
        period_count=len({period for period in (_period_key(result.path) for result in ok_results) if period}),
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        error_paths=[result.path for result in results if result.status == "error"],
        results=results,
    )


def discover_daishin_csv_paths(root: Path | str) -> list[Path]:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"CSV path does not exist: {root}")
    if root.is_dir():
        return sorted(path for path in root.rglob("*.csv") if path.is_file())
    return [root]


def _scan_one(path: Path, *, source: str) -> CsvScanResult:
    try:
        bars = load_daishin_minute_csv(path, source=source)
        report = build_csv_quality_report(bars, source_path=path, source=source)
        return CsvScanResult(
            path=str(path),
            symbol=report.symbol,
            status="ok",
            row_count=report.row_count,
            duplicate_timestamp_count=report.duplicate_timestamp_count,
            gap_count=report.gap_count,
            missing_minutes_count=report.missing_minutes_count,
            max_gap_minutes=report.max_gap_minutes,
            zero_volume_count=report.zero_volume_count,
            first_timestamp=report.first_timestamp,
            last_timestamp=report.last_timestamp,
            error="",
        )
    except Exception as exc:
        return CsvScanResult(
            path=str(path),
            symbol=path.stem,
            status="error",
            row_count=0,
            duplicate_timestamp_count=0,
            gap_count=0,
            missing_minutes_count=0,
            max_gap_minutes=0,
            zero_volume_count=0,
            first_timestamp=None,
            last_timestamp=None,
            error=str(exc),
        )


def _period_key(path: str) -> str:
    parent = Path(path).parent.name
    return parent if parent.isdigit() and len(parent) == 6 else ""
