from __future__ import annotations

import json

import pytest

from zurini.cli import main
from zurini.data import db
from zurini.data.csv_loader import build_csv_quality_report, load_daishin_minute_csv


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
