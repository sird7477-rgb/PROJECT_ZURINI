import json

import pytest

from zurini.cli import main

pytestmark = pytest.mark.integration


def test_phase1_cli_loads_db_runs_backtest_and_writes_reports(tmp_path):
    output_dir = tmp_path / "phase-1-report"

    exit_code = main(["backtest", "--output-dir", str(output_dir)])

    assert exit_code == 0
    report_path = output_dir / "report.json"
    trades_path = output_dir / "trades.csv"
    summary_path = output_dir / "summary.txt"
    assert report_path.exists()
    assert trades_path.exists()
    assert summary_path.exists()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["symbols"] == ["ZRN001", "ZRN002", "ZRN003"]
    assert payload["inserted_rows"] == 90
    assert payload["report"]["trade_count"] == 3
    assert {"gross_pnl", "net_pnl", "max_drawdown", "start_equity", "end_equity"} <= set(
        payload["report"]
    )
    assert trades_path.read_text(encoding="utf-8").startswith("symbol,entry_time,exit_time")
    assert "PROJECT_ZURINI phase-1 dummy multi-symbol backtest" in summary_path.read_text(
        encoding="utf-8"
    )


def test_phase15_large_dummy_rehearsal_cli_writes_profile_report(tmp_path):
    output_dir = tmp_path / "phase15-report"

    exit_code = main(
        [
            "rehearse-large-dummy",
            "--profile",
            "smoke",
            "--include-quality-anomalies",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    summary_path = output_dir / "rehearsal-summary.json"
    backtest_path = output_dir / "backtest" / "report.json"
    assert summary_path.exists()
    assert backtest_path.exists()

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["purpose"] == "phase-1.5 synthetic system rehearsal; not strategy profitability evidence"
    assert payload["real_data_source_boundary"] == (
        "promoted stage/API data source is Korea Investment Securities only; "
        "two-year historical raw acquisition may use Daishin Securities CYBOS "
        "only as unpromoted read-only intake"
    )
    assert payload["profile"]["name"] == "smoke"
    assert payload["profile"]["logical_months"] == 24
    assert payload["profile"]["market_bar_count"] == 2304
    assert payload["profile"]["index_bar_count"] == 1152
    assert payload["inserted_rows"]["market_bars"] == 2303
    assert payload["inserted_rows"]["index_bars"] == 1152
    assert payload["inserted_rows"]["symbol_metadata"] == 8
    assert "duplicate" in payload["quality_anomalies"]["duplicate_timestamp_error"]
    assert {"trade_count", "gross_pnl", "net_pnl", "max_drawdown", "start_equity", "end_equity"} <= set(
        payload["backtest"]
    )


def test_phase15_large_dummy_scale_profile_can_dry_run_without_db(tmp_path):
    output_dir = tmp_path / "phase15-scale"

    exit_code = main(
        [
            "rehearse-large-dummy",
            "--profile",
            "scale",
            "--dry-run",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    payload = json.loads((output_dir / "rehearsal-summary.json").read_text(encoding="utf-8"))
    assert payload["profile"]["name"] == "scale"
    assert payload["profile"]["logical_months"] == 24
    assert payload["inserted_rows"]["market_bars"] == 0
    assert payload["backtest"] == {}


def test_phase15_large_dummy_scale_profile_requires_explicit_materialization_limit(tmp_path):
    with pytest.raises(ValueError, match="would materialize"):
        main(
            [
                "rehearse-large-dummy",
                "--profile",
                "scale",
                "--output-dir",
                str(tmp_path / "phase15-scale"),
            ]
        )
