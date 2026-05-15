from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_INDEX_CODES = {
    "U001": "KOSPI",
    "U201": "KOSDAQ",
    "U180": "KOSPI200",
}

BAR_COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]
SYMBOL_COLUMNS = [
    "code",
    "name",
    "market",
    "section_kind",
    "status_kind",
    "control_kind",
    "supervision_kind",
]


@dataclass(frozen=True)
class Period:
    folder_name: str
    start: str
    end: str


@dataclass(frozen=True)
class CollectionConfig:
    output_dir: Path
    months: int
    start_date: str | None
    end_date: str | None
    collect_stocks: bool
    collect_indices: bool
    collect_daily_stocks: bool
    collect_daily_indices: bool
    collect_metadata: bool
    index_codes: dict[str, str]
    fail_fast: bool
    sleep_on_error: float


def parse_args(argv: list[str] | None = None) -> CollectionConfig:
    parser = argparse.ArgumentParser(
        prog="collect_yearly",
        description="Collect CYBOS minute bars, index bars, and symbol metadata for PROJECT_ZURINI.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("ZURINI_COLLECT_OUTPUT", "data/raw/daishin")),
        help="raw data output root; default: data/raw/daishin",
    )
    parser.add_argument("--months", type=int, default=24, help="month count when explicit dates are not provided")
    parser.add_argument("--start-date", help="inclusive start date, YYYYMMDD")
    parser.add_argument("--end-date", help="inclusive end date, YYYYMMDD")
    parser.add_argument("--stocks", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--indices", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--daily-stocks",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also collect daily stock OHLCV bars into daily-bars/",
    )
    parser.add_argument(
        "--daily-indices",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="also collect daily index OHLCV bars into daily-index-bars/",
    )
    parser.add_argument("--metadata", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--index-code",
        action="append",
        default=[],
        metavar="CODE=NAME",
        help="extra or overriding CYBOS index code, for example U001=KOSPI",
    )
    parser.add_argument("--fail-fast", action="store_true", help="stop at the first collection error")
    parser.add_argument("--sleep-on-error", type=float, default=1.0)

    args = parser.parse_args(argv)
    if args.months < 1:
        raise SystemExit("--months must be >= 1")
    if bool(args.start_date) != bool(args.end_date):
        raise SystemExit("--start-date and --end-date must be provided together")

    index_codes = dict(DEFAULT_INDEX_CODES)
    for item in args.index_code:
        if "=" not in item:
            raise SystemExit("--index-code must use CODE=NAME format")
        code, name = item.split("=", 1)
        index_codes[code.strip()] = name.strip() or code.strip()

    return CollectionConfig(
        output_dir=args.output_dir,
        months=args.months,
        start_date=args.start_date,
        end_date=args.end_date,
        collect_stocks=args.stocks,
        collect_indices=args.indices,
        collect_daily_stocks=args.daily_stocks,
        collect_daily_indices=args.daily_indices,
        collect_metadata=args.metadata,
        index_codes=index_codes,
        fail_fast=args.fail_fast,
        sleep_on_error=args.sleep_on_error,
    )


def monthly_periods_reverse(months: int, *, today: datetime | None = None) -> list[Period]:
    """Build reverse monthly windows from this month back."""
    if months < 1:
        raise ValueError("months must be >= 1")
    end_dt = today or datetime.now()
    start_dt = end_dt.replace(day=1)
    periods = [
        Period(
            folder_name=start_dt.strftime("%Y%m"),
            start=start_dt.strftime("%Y%m%d"),
            end=end_dt.strftime("%Y%m%d"),
        )
    ]

    current_start = start_dt
    for _ in range(months - 1):
        end_prev_month = current_start - timedelta(days=1)
        start_prev_month = end_prev_month.replace(day=1)
        periods.append(
            Period(
                folder_name=start_prev_month.strftime("%Y%m"),
                start=start_prev_month.strftime("%Y%m%d"),
                end=end_prev_month.strftime("%Y%m%d"),
            )
        )
        current_start = start_prev_month
    return periods


def explicit_periods(start_date: str, end_date: str) -> list[Period]:
    """Build month-bounded windows inside an explicit inclusive date range."""
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    if start > end:
        raise ValueError("start_date must be <= end_date")

    periods: list[Period] = []
    current = start.replace(day=1)
    while current <= end:
        next_month = _first_day_next_month(current)
        period_start = max(start, current)
        period_end = min(end, next_month - timedelta(days=1))
        periods.append(
            Period(
                folder_name=current.strftime("%Y%m"),
                start=period_start.strftime("%Y%m%d"),
                end=period_end.strftime("%Y%m%d"),
            )
        )
        current = next_month
    return list(reversed(periods))


def output_path(root: Path, category: str, period: Period, code: str) -> Path:
    return root / category / period.folder_name / f"{code}.csv"


def metadata_path(root: Path, run_id: str) -> Path:
    return root / "symbols" / f"symbols_{run_id}.csv"


def manifest_path(root: Path, run_id: str) -> Path:
    return root / "manifests" / f"collection_manifest_{run_id}.jsonl"


def _first_day_next_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


class CybosSession:
    def __init__(self) -> None:
        try:
            import win32com.client
        except Exception as exc:  # pragma: no cover - Windows/CYBOS only.
            raise RuntimeError("pywin32 is required on a 32-bit Windows CYBOS environment") from exc

        try:
            self.status = win32com.client.Dispatch("CpUtil.CpCybos")
            self.code_mgr = win32com.client.Dispatch("CpUtil.CpCodeMgr")
            self.stock_chart = win32com.client.Dispatch("CpSysDib.StockChart")
        except Exception as exc:  # pragma: no cover - Windows/CYBOS only.
            raise RuntimeError("failed to load CYBOS Plus COM objects") from exc

        if self.status.IsConnect == 0:
            raise RuntimeError("CYBOS Plus is not connected; run the 32-bit collector as administrator")

    def check_limit_and_wait(self) -> None:
        remain_count = self.status.GetLimitRemainCount(1)
        if remain_count <= 3:
            remain_time = self.status.LimitRequestRemainTime
            print(f"  [wait] CYBOS quote limit near; sleeping {remain_time / 1000:.1f}s")
            time.sleep(remain_time / 1000 + 0.2)

    def stock_codes(self) -> list[str]:
        kospi_codes = list(self.code_mgr.GetStockListByMarket(1))
        kosdaq_codes = list(self.code_mgr.GetStockListByMarket(2))
        target_codes: list[str] = []
        for code in kospi_codes + kosdaq_codes:
            if self.code_mgr.GetStockSectionKind(code) == 1:
                target_codes.append(code)
        return target_codes

    def code_name(self, code: str) -> str:
        return str(self.code_mgr.CodeToName(code))

    def metadata_rows(self, codes: Iterable[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            rows.append(
                {
                    "code": code,
                    "name": self.code_name(code),
                    "market": _safe_call(self.code_mgr, "GetStockMarketKind", code),
                    "section_kind": _safe_call(self.code_mgr, "GetStockSectionKind", code),
                    "status_kind": _safe_call(self.code_mgr, "GetStockStatusKind", code),
                    "control_kind": _safe_call(self.code_mgr, "GetStockControlKind", code),
                    "supervision_kind": _safe_call(self.code_mgr, "GetStockSupervisionKind", code),
                }
            )
        return rows

    def fetch_minute_bars(self, code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self.fetch_bars(code, start_date, end_date, ord("m"))

    def fetch_daily_bars(self, code: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        return self.fetch_bars(code, start_date, end_date, ord("D"))

    def fetch_bars(self, code: str, start_date: str, end_date: str, chart_kind: int) -> list[dict[str, Any]]:
        chart = self.stock_chart
        chart.SetInputValue(0, code)
        chart.SetInputValue(1, ord("1"))
        chart.SetInputValue(2, end_date)
        chart.SetInputValue(3, start_date)
        chart.SetInputValue(5, [0, 1, 2, 3, 4, 5, 8])
        chart.SetInputValue(6, chart_kind)
        chart.SetInputValue(9, ord("1"))

        rows: list[dict[str, Any]] = []
        while True:
            self.check_limit_and_wait()
            chart.BlockRequest()
            status = chart.GetDibStatus()
            if status != 0:
                raise RuntimeError(f"CYBOS request failed for {code}: {chart.GetDibMsg1()}")

            count = chart.GetHeaderValue(3)
            if count == 0:
                break

            for index in range(count):
                rows.append(
                    {
                        "date": chart.GetDataValue(0, index),
                        "time": chart.GetDataValue(1, index),
                        "open": chart.GetDataValue(2, index),
                        "high": chart.GetDataValue(3, index),
                        "low": chart.GetDataValue(4, index),
                        "close": chart.GetDataValue(5, index),
                        "volume": chart.GetDataValue(6, index),
                    }
                )
            if not chart.Continue:
                break

        return sorted(rows, key=lambda row: (int(row["date"]), int(row["time"])))


def run(config: CollectionConfig) -> int:
    print("PROJECT_ZURINI CYBOS data collector")
    print(f"output_dir={config.output_dir}")

    session = CybosSession()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    periods = (
        explicit_periods(config.start_date, config.end_date)
        if config.start_date and config.end_date
        else monthly_periods_reverse(config.months)
    )
    manifest_file = manifest_path(config.output_dir, run_id)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)

    needs_stock_codes = config.collect_stocks or config.collect_daily_stocks or config.collect_metadata
    stock_codes = session.stock_codes() if needs_stock_codes else []
    if config.collect_metadata:
        write_csv(metadata_path(config.output_dir, run_id), SYMBOL_COLUMNS, session.metadata_rows(stock_codes))

    if config.collect_indices:
        index_rows = [
            {"code": code, "name": name, "market": "INDEX", "section_kind": "index"}
            for code, name in sorted(config.index_codes.items())
        ]
        write_csv(config.output_dir / "symbols" / f"indices_{run_id}.csv", ["code", "name", "market", "section_kind"], index_rows)

    for period in periods:
        print(f"[period] {period.folder_name} {period.start}..{period.end}")
        if config.collect_indices:
            collect_bars_for_codes(
                session=session,
                root=config.output_dir,
                category="index-bars",
                period=period,
                codes=list(config.index_codes),
                bar_kind="minute",
                fail_fast=config.fail_fast,
                sleep_on_error=config.sleep_on_error,
                manifest_file=manifest_file,
            )
        if config.collect_daily_indices:
            collect_bars_for_codes(
                session=session,
                root=config.output_dir,
                category="daily-index-bars",
                period=period,
                codes=list(config.index_codes),
                bar_kind="daily",
                fail_fast=config.fail_fast,
                sleep_on_error=config.sleep_on_error,
                manifest_file=manifest_file,
            )
        if config.collect_stocks:
            collect_bars_for_codes(
                session=session,
                root=config.output_dir,
                category="minute-bars",
                period=period,
                codes=stock_codes,
                bar_kind="minute",
                fail_fast=config.fail_fast,
                sleep_on_error=config.sleep_on_error,
                manifest_file=manifest_file,
            )
        if config.collect_daily_stocks:
            collect_bars_for_codes(
                session=session,
                root=config.output_dir,
                category="daily-bars",
                period=period,
                codes=stock_codes,
                bar_kind="daily",
                fail_fast=config.fail_fast,
                sleep_on_error=config.sleep_on_error,
                manifest_file=manifest_file,
            )

    print("collection complete")
    return 0


def collect_bars_for_codes(
    *,
    session: CybosSession,
    root: Path,
    category: str,
    period: Period,
    codes: list[str],
    bar_kind: str,
    fail_fast: bool,
    sleep_on_error: float,
    manifest_file: Path,
) -> None:
    for index, code in enumerate(codes, start=1):
        path = output_path(root, category, period, code)
        name = session.code_name(code) if category in {"minute-bars", "daily-bars"} else code
        if path.exists():
            append_manifest(manifest_file, category, code, period, path, "skipped", 0, "exists")
            continue

        print(f"  [{category}] {index}/{len(codes)} {name}({code})", end="\r")
        try:
            if bar_kind == "daily":
                rows = session.fetch_daily_bars(code, period.start, period.end)
            else:
                rows = session.fetch_minute_bars(code, period.start, period.end)
            write_csv(path, BAR_COLUMNS, rows)
            append_manifest(manifest_file, category, code, period, path, "ok", len(rows), "")
        except Exception as exc:
            append_manifest(manifest_file, category, code, period, path, "error", 0, str(exc))
            print(f"\n  [error] {category} {code}: {exc}")
            if fail_fast:
                raise
            time.sleep(sleep_on_error)
    print()


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def append_manifest(
    path: Path,
    category: str,
    code: str,
    period: Period,
    output: Path,
    status: str,
    rows: int,
    message: str,
) -> None:
    entry = {
        "category": category,
        "code": code,
        "period": period.folder_name,
        "start": period.start,
        "end": period.end,
        "output": str(output),
        "status": status,
        "rows": rows,
        "message": message,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _safe_call(obj: Any, name: str, *args: Any) -> Any:
    method = getattr(obj, name, None)
    if method is None:
        return ""
    try:
        return method(*args)
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
