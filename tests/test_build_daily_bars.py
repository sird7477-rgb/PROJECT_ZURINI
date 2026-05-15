from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest


def load_builder():
    path = Path("scripts/build-daily-bars-from-minute.py")
    spec = importlib.util.spec_from_file_location("build_daily_bars_from_minute", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_daily_rows_preserves_open_close_and_sums_volume():
    builder = load_builder()

    rows = builder.build_daily_rows(
        [
            {"date": "20260508", "time": "901", "open": "1000", "high": "1010", "low": "990", "close": "1005", "volume": "10"},
            {"date": "20260508", "time": "902", "open": "1005", "high": "1020", "low": "995", "close": "1015", "volume": "12"},
            {"date": "20260511", "time": "901", "open": "1100", "high": "1110", "low": "1090", "close": "1105", "volume": "8"},
        ]
    )

    assert rows == [
        {"date": "20260508", "time": "0", "open": "1000", "high": "1020", "low": "990", "close": "1015", "volume": "22"},
        {"date": "20260511", "time": "0", "open": "1100", "high": "1110", "low": "1090", "close": "1105", "volume": "8"},
    ]


def test_build_daily_rows_sorts_minutes_before_aggregation():
    builder = load_builder()

    rows = builder.build_daily_rows(
        [
            {"date": "20260508", "time": "902", "open": "1005", "high": "1020", "low": "995", "close": "1015", "volume": "12"},
            {"date": "20260508", "time": "901", "open": "1000", "high": "1010", "low": "990", "close": "1005", "volume": "10"},
        ]
    )

    assert rows == [
        {"date": "20260508", "time": "0", "open": "1000", "high": "1020", "low": "990", "close": "1015", "volume": "22"}
    ]


def test_build_daily_rows_rejects_invalid_minute_time():
    builder = load_builder()

    with pytest.raises(ValueError, match="minute time out of HHMM bounds"):
        builder.build_daily_rows(
            [
                {
                    "date": "20260508",
                    "time": "2460",
                    "open": "1000",
                    "high": "1010",
                    "low": "990",
                    "close": "1005",
                    "volume": "10",
                }
            ]
        )

    with pytest.raises(ValueError, match="minute time must be numeric"):
        builder.build_daily_rows(
            [
                {
                    "date": "20260508",
                    "time": "09:01",
                    "open": "1000",
                    "high": "1010",
                    "low": "990",
                    "close": "1005",
                    "volume": "10",
                }
            ]
        )


def test_parse_args_rejects_zero_limit_files():
    builder = load_builder()

    with pytest.raises(SystemExit):
        builder.parse_args(["--limit-files", "0"])


def test_main_rejects_missing_root_without_truncating_manifest(tmp_path: Path):
    builder = load_builder()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("previous\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        builder.main(["--root", str(tmp_path / "missing"), "--manifest", str(manifest)])

    assert manifest.read_text(encoding="utf-8") == "previous\n"


def test_build_file_keeps_month_and_symbol_partition(tmp_path: Path):
    builder = load_builder()
    root = tmp_path / "minute-bars"
    source = root / "202605" / "A000020.csv"
    source.parent.mkdir(parents=True)
    with source.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=builder.BAR_COLUMNS)
        writer.writeheader()
        writer.writerows(
            [
                {"date": "20260508", "time": "901", "open": "1000", "high": "1010", "low": "990", "close": "1005", "volume": "10"},
                {"date": "20260508", "time": "902", "open": "1005", "high": "1020", "low": "995", "close": "1015", "volume": "12"},
            ]
        )

    result = builder.build_file(source, root=root, output_root=tmp_path / "daily-bars")

    assert result.output_path == tmp_path / "daily-bars" / "202605" / "A000020.csv"
    assert result.input_rows == 2
    assert result.output_rows == 1


def test_iter_inputs_recurses_beyond_month_symbol_depth(tmp_path: Path):
    builder = load_builder()
    root = tmp_path / "minute-bars"
    shallow = root / "202605" / "A000020.csv"
    deep = root / "kospi" / "202605" / "A000030.csv"
    shallow.parent.mkdir(parents=True)
    deep.parent.mkdir(parents=True)
    shallow.write_text("date,time,open,high,low,close,volume\n", encoding="utf-8")
    deep.write_text("date,time,open,high,low,close,volume\n", encoding="utf-8")

    assert list(builder.iter_inputs(root)) == [shallow, deep]


def test_parse_args_rejects_zero_retention_days():
    builder = load_builder()

    with pytest.raises(SystemExit):
        builder.parse_args(["--retention-trading-days", "0"])


def test_parse_args_rejects_output_root_equal_to_input_root(tmp_path: Path):
    builder = load_builder()
    root = tmp_path / "minute-bars"

    with pytest.raises(SystemExit, match="output-root"):
        builder.parse_args(["--root", str(root), "--output-root", str(root)])


def test_parse_args_rejects_output_root_inside_input_root(tmp_path: Path):
    builder = load_builder()
    root = tmp_path / "minute-bars"

    with pytest.raises(SystemExit, match="output-root"):
        builder.parse_args(["--root", str(root), "--output-root", str(root / "derived")])


def test_apply_retention_keeps_latest_distinct_dates_across_output_root(tmp_path: Path):
    builder = load_builder()
    output_root = tmp_path / "daily-bars"
    _write_daily_csv(
        output_root / "202605" / "A000020.csv",
        [
            {"date": "20260508", "time": "0", "open": "1000", "high": "1010", "low": "990", "close": "1005", "volume": "10"},
            {"date": "20260509", "time": "0", "open": "1010", "high": "1020", "low": "1000", "close": "1015", "volume": "11"},
            {"date": "20260512", "time": "0", "open": "1020", "high": "1030", "low": "1010", "close": "1025", "volume": "12"},
        ],
    )
    _write_daily_csv(
        output_root / "202605" / "A000030.csv",
        [
            {"date": "20260507", "time": "0", "open": "900", "high": "910", "low": "890", "close": "905", "volume": "20"},
            {"date": "20260509", "time": "0", "open": "910", "high": "920", "low": "900", "close": "915", "volume": "21"},
        ],
    )

    with pytest.raises(RuntimeError, match="retention would remove existing daily-bar data"):
        builder.apply_retention(output_root, keep_latest_days=2)

    result = builder.apply_retention(output_root, keep_latest_days=2, confirm_data_loss=True)

    assert result.cutoff_date == "20260509"
    assert result.files_checked == 2
    assert result.files_rewritten == 2
    assert result.files_deleted == 0
    assert result.rows_removed == 2
    assert _read_dates(output_root / "202605" / "A000020.csv") == ["20260509", "20260512"]
    assert _read_dates(output_root / "202605" / "A000030.csv") == ["20260509"]


def test_apply_retention_deletes_files_without_retained_rows(tmp_path: Path):
    builder = load_builder()
    output_root = tmp_path / "daily-bars"
    obsolete = output_root / "202604" / "A000020.csv"
    _write_daily_csv(
        obsolete,
        [
            {"date": "20260429", "time": "0", "open": "1000", "high": "1010", "low": "990", "close": "1005", "volume": "10"},
        ],
    )
    _write_daily_csv(
        output_root / "202605" / "A000030.csv",
        [
            {"date": "20260509", "time": "0", "open": "910", "high": "920", "low": "900", "close": "915", "volume": "21"},
            {"date": "20260512", "time": "0", "open": "920", "high": "930", "low": "910", "close": "925", "volume": "22"},
        ],
    )

    with pytest.raises(RuntimeError, match="retention would remove existing daily-bar data"):
        builder.apply_retention(output_root, keep_latest_days=1)

    result = builder.apply_retention(output_root, keep_latest_days=1, confirm_data_loss=True)

    assert result.cutoff_date == "20260512"
    assert result.files_deleted == 1
    assert result.rows_removed == 2
    assert not obsolete.exists()
    assert _read_dates(output_root / "202605" / "A000030.csv") == ["20260512"]


def _write_daily_csv(path: Path, rows: list[dict[str, str]]) -> None:
    builder = load_builder()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=builder.BAR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read_dates(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [row["date"] for row in csv.DictReader(handle)]
