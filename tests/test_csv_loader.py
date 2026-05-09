from __future__ import annotations

import json

import pytest

from zurini.cli import _csv_paths, main
from zurini.data import db
from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv
from zurini.data.csv_quality import discover_daishin_csv_paths, scan_daishin_csv_tree


def test_daishin_csv_loader_maps_file_contract_to_market_bars(tmp_path):
    path = tmp_path / "A123456.csv"
    path.write_text(
        "\ufeffdate,time,open,high,low,close,volume\n"
        "20250401,901,5960,6010,5960,5990,666\n"
        "20250401,903,5990,6000,5980,6000,10\n",
        encoding="utf-8",
    )

    bars = load_daishin_minute_csv(path)
    report = build_csv_quality_report(bars, source_path=path)

    assert [bar.symbol for bar in bars] == ["A123456", "A123456"]
    assert bars[0].timestamp.isoformat() == "2025-04-01T09:01:00+09:00"
    assert bars[0].value == 5990 * 666
    assert bars[0].source == "sample"
    assert report.row_count == 2
    assert report.gap_count == 1
    assert report.zero_volume_count == 0


def test_daishin_csv_loader_rejects_missing_required_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,time,open\n20250401,901,5960\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required CSV columns"):
        load_daishin_minute_csv(path)


def test_daishin_csv_loader_reports_corrupted_row_context(tmp_path):
    path = tmp_path / "bad-row.csv"
    path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250401,901,5960,6010,5960,5990,not-a-number\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid minute CSV row for bad-row at 20250401 901"):
        load_daishin_minute_csv(path)


def test_sample_csv_loads_with_expected_quality_profile():
    bars = load_daishin_minute_csv("sample/A000020.csv")
    report = build_csv_quality_report(bars, source_path="sample/A000020.csv")

    assert report.symbol == "A000020"
    assert report.row_count == 4208
    assert report.duplicate_timestamp_count == 0
    assert report.zero_volume_count == 0
    assert report.first_timestamp == "2025-04-01T09:01:00+09:00"
    assert report.last_timestamp == "2025-04-30T15:30:00+09:00"
    assert report.gap_count > 0


def test_csv_tree_scan_summarizes_ok_and_error_files(tmp_path):
    good = tmp_path / "202504" / "A111111.csv"
    bad = tmp_path / "202504" / "A222222.csv"
    good.parent.mkdir()
    good.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250401,901,100,110,100,105,10\n"
        "20250401,903,105,110,104,106,20\n",
        encoding="utf-8",
    )
    bad.write_text("date,time,open\n20250401,901,100\n", encoding="utf-8")

    summary = scan_daishin_csv_tree(tmp_path)

    assert summary.file_count == 2
    assert summary.ok_count == 1
    assert summary.error_count == 1
    assert summary.success_rate == 0.5
    assert summary.row_count == 2
    assert summary.gap_count == 1
    assert summary.symbol_count == 1
    assert summary.period_count == 1
    assert summary.error_paths == [str(bad)]
    assert {result.status for result in summary.results} == {"ok", "error"}


def test_scan_csv_cli_writes_json_report(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    output = tmp_path / "scan.json"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250401,901,100,110,100,105,10\n",
        encoding="utf-8",
    )

    exit_code = main(["scan-csv", "--root", str(tmp_path), "--output", str(output)])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["file_count"] == 1
    assert payload["ok_count"] == 1
    assert payload["success_rate"] == 1
    assert payload["symbol_count"] == 1
    assert payload["period_count"] == 0
    assert payload["row_count"] == 1


def test_csv_path_discovery_accepts_files_and_directory_trees(tmp_path):
    first = tmp_path / "202504" / "A111111.csv"
    second = tmp_path / "202505" / "A222222.csv"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("date,time,open,high,low,close,volume\n", encoding="utf-8")
    second.write_text("date,time,open,high,low,close,volume\n", encoding="utf-8")

    assert discover_daishin_csv_paths(first) == [first]
    assert discover_daishin_csv_paths(tmp_path) == [first, second]


def test_csv_paths_preserves_explicit_symbol_matching_order(tmp_path):
    explicit_second = tmp_path / "A222222.csv"
    explicit_first = tmp_path / "A111111.csv"
    discovered = tmp_path / "202504" / "A333333.csv"
    discovered.parent.mkdir()
    for path in (explicit_second, explicit_first, discovered):
        path.write_text("date,time,open,high,low,close,volume\n", encoding="utf-8")

    assert _csv_paths([explicit_second, explicit_first], [tmp_path / "202504"]) == [
        explicit_second,
        explicit_first,
        discovered,
    ]


def test_csv_path_discovery_rejects_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError, match="CSV path does not exist"):
        discover_daishin_csv_paths(tmp_path / "missing")


@pytest.mark.integration
def test_load_sample_cli_inserts_csv_and_writes_quality_report(tmp_path):
    output_dir = tmp_path / "sample-report"

    exit_code = main(["load-sample", "--path", "sample/A000020.csv", "--output-dir", str(output_dir)])

    assert exit_code == 0
    payload = json.loads((output_dir / "sample-quality.json").read_text(encoding="utf-8"))
    assert payload["symbol"] == "A000020"
    assert payload["row_count"] == 4208
    assert payload["inserted_rows"] == 4208
    assert len(db.fetch_bars("A000020")) == 4208


@pytest.mark.integration
def test_backtest_csv_cli_runs_sample_through_existing_engine(tmp_path):
    output_dir = tmp_path / "sample-backtest"

    exit_code = main(["backtest-csv", "--path", "sample/A000020.csv", "--output-dir", str(output_dir)])

    assert exit_code == 0
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    quality = json.loads((output_dir / "csv-quality.json").read_text(encoding="utf-8"))
    summary = (output_dir / "summary.txt").read_text(encoding="utf-8")

    assert report["symbols"] == ["A000020"]
    assert report["inserted_rows"] == 4208
    assert "trade_count" in report["report"]
    assert quality[0]["symbol"] == "A000020"
    assert quality[0]["row_count"] == 4208
    assert "PROJECT_ZURINI phase-1 CSV sample backtest" in summary


@pytest.mark.integration
def test_backtest_csv_cli_accepts_root_discovery(tmp_path):
    output_dir = tmp_path / "sample-backtest-root"

    exit_code = main(["backtest-csv", "--root", "sample", "--output-dir", str(output_dir)])

    assert exit_code == 0
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["symbols"] == ["A000020"]
    assert report["inserted_rows"] == 4208


@pytest.mark.integration
def test_backtest_csv_cli_can_limit_discovered_files(tmp_path):
    output_dir = tmp_path / "sample-backtest-limited"

    exit_code = main(["backtest-csv", "--root", "sample", "--limit-files", "1", "--output-dir", str(output_dir)])

    assert exit_code == 0
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["inserted_rows"] == 4208


def test_backtest_csv_cli_rejects_root_with_symbol_overrides(tmp_path):
    with pytest.raises(ValueError, match="--symbol overrides are only supported"):
        main(["backtest-csv", "--root", "sample", "--symbol", "A000020", "--output-dir", str(tmp_path)])


@pytest.mark.integration
def test_backtest_csv_cli_deduplicates_symbols_for_multi_period_roots(tmp_path):
    root = tmp_path / "raw"
    first = root / "202504" / "A111111.csv"
    second = root / "202505" / "A111111.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250401,901,100,110,100,105,10\n",
        encoding="utf-8",
    )
    second.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250501,901,105,112,104,110,20\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "multi-period-backtest"

    exit_code = main(["backtest-csv", "--root", str(root), "--output-dir", str(output_dir)])

    assert exit_code == 0
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["symbols"] == ["A111111"]
    assert report["inserted_rows"] == 2
