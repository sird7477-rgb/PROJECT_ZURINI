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
