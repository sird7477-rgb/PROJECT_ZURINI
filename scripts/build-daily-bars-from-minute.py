#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


BAR_COLUMNS = ["date", "time", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class BuildResult:
    input_path: Path
    output_path: Path
    input_rows: int
    output_rows: int


@dataclass(frozen=True)
class RetentionResult:
    cutoff_date: str | None
    files_checked: int
    files_rewritten: int
    files_deleted: int
    rows_removed: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build daily OHLCV bars from Daishin/CYBOS minute-bar CSV files."
    )
    parser.add_argument("--root", type=Path, default=Path("data/raw/daishin/minute-bars"))
    parser.add_argument("--output-root", type=Path, default=Path("data/derived/daishin/daily-bars"))
    parser.add_argument("--manifest", type=Path, default=Path("data/derived/daishin/daily-bars-manifest.jsonl"))
    parser.add_argument("--limit-files", type=int)
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument(
        "--retention-trading-days",
        type=int,
        help="after building, keep only the latest N distinct daily-bar dates under output-root",
    )
    parser.add_argument(
        "--confirm-retention-data-loss",
        action="store_true",
        help="allow retention to rewrite or delete existing daily-bar CSV rows/files",
    )
    args = parser.parse_args(argv)
    if args.limit_files is not None and args.limit_files < 1:
        raise SystemExit("--limit-files must be >= 1")
    if args.retention_trading_days is not None and args.retention_trading_days < 1:
        raise SystemExit("--retention-trading-days must be >= 1")
    if _is_self_or_child(args.output_root, args.root):
        raise SystemExit("--output-root must not be the same as --root or inside --root")
    return args


def build_daily_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    daily: dict[str, dict[str, int | str]] = {}
    order: list[str] = []
    normalized_rows = [
        (str(row["date"]).strip(), _minute_time_sort_key(str(row["time"]).strip()), row)
        for row in rows
    ]
    for day, _minute_time, row in sorted(normalized_rows, key=lambda item: (item[0], item[1])):
        if day not in daily:
            daily[day] = {
                "date": day,
                "time": "0",
                "open": row["open"],
                "high": int(row["high"]),
                "low": int(row["low"]),
                "close": row["close"],
                "volume": int(row["volume"]),
            }
            order.append(day)
            continue

        current = daily[day]
        current["high"] = max(int(current["high"]), int(row["high"]))
        current["low"] = min(int(current["low"]), int(row["low"]))
        current["close"] = row["close"]
        current["volume"] = int(current["volume"]) + int(row["volume"])

    return [
        {
            "date": str(daily[day]["date"]),
            "time": str(daily[day]["time"]),
            "open": str(daily[day]["open"]),
            "high": str(daily[day]["high"]),
            "low": str(daily[day]["low"]),
            "close": str(daily[day]["close"]),
            "volume": str(daily[day]["volume"]),
        }
        for day in order
    ]


def _is_self_or_child(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _minute_time_sort_key(value: str) -> int:
    if not value.isdecimal():
        raise ValueError(f"minute time must be numeric HHMM/HMM: {value!r}")
    numeric = int(value)
    hour, minute = divmod(numeric, 100)
    if hour > 23 or minute > 59:
        raise ValueError(f"minute time out of HHMM bounds: {value!r}")
    return hour * 60 + minute


def build_file(input_path: Path, *, root: Path, output_root: Path) -> BuildResult:
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in BAR_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"{input_path} missing columns: {', '.join(missing)}")
        source_rows = list(reader)

    daily_rows = build_daily_rows(source_rows)
    output_path = output_root / input_path.relative_to(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAR_COLUMNS)
        writer.writeheader()
        writer.writerows(daily_rows)

    return BuildResult(
        input_path=input_path,
        output_path=output_path,
        input_rows=len(source_rows),
        output_rows=len(daily_rows),
    )


def iter_inputs(root: Path, limit_files: int | None = None) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*.csv")):
        yield path
        count += 1
        if limit_files is not None and count >= limit_files:
            return


def apply_retention(
    output_root: Path,
    *,
    keep_latest_days: int,
    confirm_data_loss: bool = False,
) -> RetentionResult:
    csv_paths = sorted(path for path in output_root.rglob("*.csv") if path.is_file())
    dates = sorted({row["date"] for path in csv_paths for row in _read_daily_rows(path)})
    if len(dates) <= keep_latest_days:
        return RetentionResult(
            cutoff_date=dates[0] if dates else None,
            files_checked=len(csv_paths),
            files_rewritten=0,
            files_deleted=0,
            rows_removed=0,
        )

    cutoff_date = dates[-keep_latest_days]
    removal_plan: list[tuple[Path, int, bool]] = []
    for path in csv_paths:
        rows = _read_daily_rows(path)
        kept = [row for row in rows if row["date"] >= cutoff_date]
        removed = len(rows) - len(kept)
        if removed:
            removal_plan.append((path, removed, not kept))
    if removal_plan and not confirm_data_loss:
        affected = ", ".join(str(path) for path, _removed, _delete_file in removal_plan[:5])
        more = "" if len(removal_plan) <= 5 else f", ... +{len(removal_plan) - 5} files"
        raise RuntimeError(
            "retention would remove existing daily-bar data; rerun with "
            "--confirm-retention-data-loss after backing up or explicitly accepting this loss. "
            f"cutoff_date={cutoff_date}; affected={affected}{more}"
        )

    files_rewritten = 0
    files_deleted = 0
    rows_removed = 0
    for path in csv_paths:
        rows = _read_daily_rows(path)
        kept = [row for row in rows if row["date"] >= cutoff_date]
        removed = len(rows) - len(kept)
        if removed == 0:
            continue
        rows_removed += removed
        if kept:
            _write_daily_rows(path, kept)
            files_rewritten += 1
        else:
            path.unlink()
            files_deleted += 1

    _remove_empty_dirs(output_root)
    return RetentionResult(
        cutoff_date=cutoff_date,
        files_checked=len(csv_paths),
        files_rewritten=files_rewritten,
        files_deleted=files_deleted,
        rows_removed=rows_removed,
    )


def _read_daily_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [column for column in BAR_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"{path} missing columns: {', '.join(missing)}")
        return [{column: str(row[column]).strip() for column in BAR_COLUMNS} for row in reader]


def _write_daily_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _remove_empty_dirs(root: Path) -> None:
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.root.exists():
        raise SystemExit(f"input root does not exist: {args.root}")
    inputs = list(iter_inputs(args.root, args.limit_files))
    if not inputs:
        raise SystemExit(f"no minute CSV files found under: {args.root}")

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    total_input_rows = 0
    total_output_rows = 0
    with args.manifest.open("w", encoding="utf-8") as manifest:
        for input_path in inputs:
            result = build_file(input_path, root=args.root, output_root=args.output_root)
            manifest.write(
                json.dumps(
                    {
                        "input": str(result.input_path),
                        "output": str(result.output_path),
                        "input_rows": result.input_rows,
                        "output_rows": result.output_rows,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            processed += 1
            total_input_rows += result.input_rows
            total_output_rows += result.output_rows
            if args.progress_every and processed % args.progress_every == 0:
                print(
                    f"[daily-build] files={processed} input_rows={total_input_rows} output_rows={total_output_rows}",
                    file=sys.stderr,
                    flush=True,
                )

    retention = None
    if args.retention_trading_days is not None:
        retention = apply_retention(
            args.output_root,
            keep_latest_days=args.retention_trading_days,
            confirm_data_loss=args.confirm_retention_data_loss,
        )

    print(
        json.dumps(
            {
                "files": processed,
                "input_rows": total_input_rows,
                "output_rows": total_output_rows,
                "output_root": str(args.output_root),
                "manifest": str(args.manifest),
                "retention": (
                    {
                        "cutoff_date": retention.cutoff_date,
                        "files_checked": retention.files_checked,
                        "files_rewritten": retention.files_rewritten,
                        "files_deleted": retention.files_deleted,
                        "rows_removed": retention.rows_removed,
                    }
                    if retention is not None
                    else None
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
