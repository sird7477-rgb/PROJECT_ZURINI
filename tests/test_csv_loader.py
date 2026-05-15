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
    assert report.missing_minutes_count == 1
    assert report.max_gap_minutes == 1
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
    assert summary.missing_minutes_count == 1
    assert summary.max_gap_minutes == 1
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


def test_scan_csv_cli_without_acceptance_report_keeps_plain_scan_output(tmp_path):
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
    assert "acceptance" not in payload
    assert payload["error_count"] == 0


def test_scan_csv_cli_without_acceptance_report_still_fails_bad_csv(tmp_path):
    csv_path = tmp_path / "bad.csv"
    output = tmp_path / "scan.json"
    csv_path.write_text("date,time,open\n20250401,901,100\n", encoding="utf-8")

    exit_code = main(["scan-csv", "--root", str(tmp_path), "--output", str(output)])

    assert exit_code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["error_count"] == 1
    assert payload["error_paths"] == [str(csv_path)]


def test_scan_csv_cli_writes_phase_two_acceptance_report(tmp_path):
    first = tmp_path / "202504" / "A111111.csv"
    second = tmp_path / "202505" / "A222222.csv"
    output = tmp_path / "scan.json"
    acceptance = tmp_path / "acceptance.json"
    first.parent.mkdir()
    second.parent.mkdir()
    for path in (first, second):
        path.write_text(
            "date,time,open,high,low,close,volume\n"
            "20250401,901,100,110,100,105,10\n",
            encoding="utf-8",
        )

    exit_code = main(
        [
            "scan-csv",
            "--root",
            str(tmp_path),
            "--output",
            str(output),
            "--acceptance-report",
            str(acceptance),
            "--min-symbols",
            "2",
            "--min-periods",
            "2",
        ]
    )

    assert exit_code == 0
    payload = json.loads(acceptance.read_text(encoding="utf-8"))
    assert payload["purpose"] == "phase-2 real-data intake gate before DB promotion"
    assert payload["real_data_source_boundary"] == (
        "promoted stage/API data source is Korea Investment Securities only; "
        "two-year historical raw acquisition may use Daishin Securities CYBOS "
        "only as unpromoted read-only intake"
    )
    assert payload["acceptance"]["status"] == "accepted"
    assert payload["acceptance"]["failures"] == []


def test_scan_csv_cli_rejects_acceptance_threshold_failures(tmp_path):
    csv_path = tmp_path / "A111111.csv"
    acceptance = tmp_path / "acceptance.json"
    csv_path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20250401,901,100,110,100,105,10\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "scan-csv",
            "--root",
            str(tmp_path),
            "--acceptance-report",
            str(acceptance),
            "--min-symbols",
            "2",
        ]
    )

    assert exit_code == 1
    payload = json.loads(acceptance.read_text(encoding="utf-8"))
    assert payload["acceptance"]["status"] == "rejected"
    assert payload["acceptance"]["failures"] == ["symbol_count 1 < 2"]


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
    assert report["trade_continuity"]["status"] in {"passed", "failed"}
    assert report["trade_continuity"]["window_minutes"] == 5
    assert report["phase2_parameters"]["profit_target"] == "0.03"
    assert "trade_count" in report["report"]
    assert quality[0]["symbol"] == "A000020"
    assert quality[0]["row_count"] == 4208
    assert "PROJECT_ZURINI phase-1 CSV sample backtest" in summary


@pytest.mark.integration
def test_backtest_csv_cli_accepts_phase2_parameter_overrides(tmp_path):
    output_dir = tmp_path / "sample-backtest"

    exit_code = main(
        [
            "backtest-csv",
            "--path",
            "sample/A000020.csv",
            "--profit-target",
            "0.02",
            "--hard-stop",
            "-0.02",
            "--fee-rate",
            "0.00030",
            "--slippage-rate",
            "0.00100",
            "--hold-overnight",
            "--capital-mode",
            "shared-slot",
            "--max-open-positions",
            "3",
            "--variable-slot-count",
            "--slot-capital-cap",
            "10000000",
            "--weekly-contribution",
            "100000",
            "--max-daily-stop-losses",
            "2",
            "--max-daily-loss",
            "10000",
            "--day-end-exit-time",
            "15:15",
            "--max-holding-minutes",
            "30",
            "--pullback-band",
            "0.004",
            "--min-bid-ask-ratio",
            "1.5",
            "--strategy",
            "vwap",
            "--entry-start",
            "10:30",
            "--entry-end",
            "14:30",
            "--entry-mode",
            "breakout",
            "--require-above-vwap",
            "--impulse-threshold",
            "0.02",
            "--min-impulse-volume",
            "10000",
            "--impulse-volume-window",
            "20",
            "--impulse-volume-multiple",
            "3.0",
            "--swing-sma-window",
            "20",
            "--swing-volume-window",
            "5",
            "--swing-support-band",
            "0.02",
            "--swing-max-volume-ratio",
            "0.5",
            "--swing-max-rsi",
            "40",
            "--swing-min-sma-distance",
            "0.01",
            "--swing-min-volume-ratio",
            "1.0",
            "--swing-min-rsi",
            "55",
            "--min-relative-strength",
            "0.05",
            "--aday-sma-window",
            "20",
            "--aday-atr-window",
            "14",
            "--aday-value-window",
            "5",
            "--aday-min-average-value",
            "50000000000",
            "--aday-min-atr-ratio",
            "0.03",
            "--aday-max-opening-gap",
            "0.05",
            "--aday-min-session-value",
            "100000000",
            "--intrabar-policy",
            "conservative",
            "--ambiguous-intrabar-policy",
            "stop-first",
            "--skip-db",
            "--output-dir",
            str(output_dir),
        ]
    )

    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["phase2_parameters"]["profit_target"] == "0.02"
    assert report["phase2_parameters"]["hard_stop"] == "-0.02"
    assert report["phase2_parameters"]["fee_rate"] == "0.00030"
    assert report["phase2_parameters"]["slippage_rate"] == "0.00100"
    assert report["phase2_parameters"]["day_end_exit"] is False
    assert report["phase2_parameters"]["capital_mode"] == "shared-slot"
    assert report["phase2_parameters"]["max_open_positions"] == 3
    assert report["phase2_parameters"]["variable_slot_count"] is True
    assert report["phase2_parameters"]["slot_capital_cap"] == "10000000"
    assert report["phase2_parameters"]["weekly_contribution"] == "100000"
    assert report["phase2_parameters"]["max_daily_stop_losses"] == 2
    assert report["phase2_parameters"]["max_daily_loss"] == "10000"
    assert report["phase2_parameters"]["day_end_exit_time"] == "15:15"
    assert report["phase2_parameters"]["max_holding_minutes"] == 30
    assert report["phase2_parameters"]["strategy"] == "vwap"
    assert report["phase2_parameters"]["pullback_band"] == "0.004"
    assert report["phase2_parameters"]["min_bid_ask_ratio"] == "1.5"
    assert report["phase2_parameters"]["entry_start"] == "10:30"
    assert report["phase2_parameters"]["entry_end"] == "14:30"
    assert report["phase2_parameters"]["entry_mode"] == "breakout"
    assert report["phase2_parameters"]["require_above_vwap"] is True
    assert report["phase2_parameters"]["impulse_threshold"] == "0.02"
    assert report["phase2_parameters"]["min_impulse_volume"] == 10000
    assert report["phase2_parameters"]["impulse_volume_window"] == 20
    assert report["phase2_parameters"]["impulse_volume_multiple"] == "3.0"
    assert report["phase2_parameters"]["swing_sma_window"] == 20
    assert report["phase2_parameters"]["swing_volume_window"] == 5
    assert report["phase2_parameters"]["swing_support_band"] == "0.02"
    assert report["phase2_parameters"]["swing_max_volume_ratio"] == "0.5"
    assert report["phase2_parameters"]["swing_max_rsi"] == "40"
    assert report["phase2_parameters"]["swing_min_sma_distance"] == "0.01"
    assert report["phase2_parameters"]["swing_min_volume_ratio"] == "1.0"
    assert report["phase2_parameters"]["swing_min_rsi"] == "55"
    assert report["phase2_parameters"]["min_relative_strength"] == "0.05"
    assert report["phase2_parameters"]["aday_sma_window"] == 20
    assert report["phase2_parameters"]["aday_atr_window"] == 14
    assert report["phase2_parameters"]["aday_value_window"] == 5
    assert report["phase2_parameters"]["aday_min_average_value"] == "50000000000"
    assert report["phase2_parameters"]["aday_min_atr_ratio"] == "0.03"
    assert report["phase2_parameters"]["aday_max_opening_gap"] == "0.05"
    assert report["phase2_parameters"]["aday_min_session_value"] == "100000000"
    assert report["phase2_parameters"]["intrabar_policy"] == "conservative"
    assert report["phase2_parameters"]["ambiguous_intrabar_policy"] == "stop-first"


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


@pytest.mark.integration
def test_backtest_csv_cli_accepts_path_list(tmp_path):
    output_dir = tmp_path / "sample-backtest-path-list"
    path_list = tmp_path / "paths.txt"
    path_list.write_text("sample/A000020.csv\n", encoding="utf-8")

    exit_code = main(["backtest-csv", "--path-list", str(path_list), "--output-dir", str(output_dir)])

    assert exit_code == 0
    report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
    assert report["symbols"] == ["A000020"]
    assert report["inserted_rows"] == 4208


def test_backtest_csv_cli_rejects_root_with_symbol_overrides(tmp_path):
    with pytest.raises(ValueError, match="--symbol overrides are only supported"):
        main(["backtest-csv", "--root", "sample", "--symbol", "A000020", "--output-dir", str(tmp_path)])


def test_backtest_csv_cli_rejects_missing_path_list(tmp_path):
    with pytest.raises(FileNotFoundError):
        main(["backtest-csv", "--path-list", str(tmp_path / "missing.txt"), "--output-dir", str(tmp_path)])


def test_backtest_csv_cli_rejects_empty_path_list(tmp_path):
    path_list = tmp_path / "paths.txt"
    path_list.write_text("\n# only comments\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one --path or --root is required"):
        main(["backtest-csv", "--path-list", str(path_list), "--output-dir", str(tmp_path)])


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
