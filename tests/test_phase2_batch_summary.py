from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from zurini.cli import main
from zurini.phase2 import build_phase2_batch_summary, discover_report_paths


def _write_report(
    path: Path,
    *,
    symbols: list[str],
    inserted_rows: int,
    trade_count: int,
    net_pnl: str,
    valid_trades: int | None = None,
    invalid_trades: int = 0,
    invalid_net_pnl: str | None = None,
    ambiguous_intrabar: bool = False,
    reason: str = "profit-target",
    continuity_status: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    valid = trade_count if valid_trades is None else valid_trades
    trades = [
        {
            "symbol": symbols[index % len(symbols)] if symbols else "A000000",
            "entry_time": "2026-01-02T09:01:00+09:00",
            "exit_time": "2026-01-02T09:10:00+09:00",
            "entry_price": "100",
            "exit_price": "101",
            "quantity": "1",
            "gross_pnl": "1",
            "net_pnl": "1",
            "reason": reason,
            "ambiguous_intrabar": ambiguous_intrabar,
        }
        for index in range(trade_count)
    ]
    status = continuity_status or ("passed" if invalid_trades == 0 else "failed")
    path.write_text(
        json.dumps(
            {
                "symbols": symbols,
                "inserted_rows": inserted_rows,
                "report": {
                    "trade_count": trade_count,
                    "gross_pnl": net_pnl,
                    "net_pnl": net_pnl,
                    "max_drawdown": "0",
                    "start_equity": "10000000",
                    "end_equity": "10000000",
                },
                "trades": trades,
                "trade_continuity": {"status": status},
                "trade_continuity_summary": {
                    "valid_trades": valid,
                    "invalid_trades": invalid_trades,
                    "valid_net_pnl": "10.50",
                    "invalid_net_pnl": invalid_net_pnl if invalid_net_pnl is not None else ("-3.25" if invalid_trades else "0"),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_phase2_summarize_runs_cli_writes_json_and_markdown(tmp_path):
    first = tmp_path / "runs" / "b" / "report.json"
    second = tmp_path / "runs" / "a" / "report.json"
    _write_report(first, symbols=["A000020"], inserted_rows=100, trade_count=1, net_pnl="5.50")
    _write_report(second, symbols=["A000030"], inserted_rows=200, trade_count=2, net_pnl="-1.25")
    output_json = tmp_path / "summary.json"
    output_md = tmp_path / "summary.md"

    exit_code = main(
        [
            "phase2-summarize-runs",
            "--root",
            str(tmp_path / "runs"),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ]
    )

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    markdown = output_md.read_text(encoding="utf-8")
    assert exit_code == 0
    assert payload["purpose"] == "phase-2 backtest batch operational summary"
    assert "not a strategy profitability verdict" in payload["interpretation_boundary"]
    assert payload["report_count"] == 2
    assert payload["total_inserted_rows"] == 300
    assert payload["total_trade_count"] == 3
    assert payload["total_net_pnl"] == "4.25"
    assert payload["continuity_status"] == "passed"
    assert payload["invalid_trade_ratio"] == "0"
    assert payload["invalid_net_pnl_ratio"] == "0"
    assert payload["ambiguous_intrabar_ratio"] == "0"
    assert payload["optimization_gate_status"] == "passed"
    assert "Phase 2 Batch Summary" in markdown


def test_phase2_summarize_runs_accepts_report_list_comments_and_deduplicates(tmp_path):
    report = tmp_path / "run" / "report.json"
    _write_report(report, symbols=["A000020"], inserted_rows=100, trade_count=1, net_pnl="1")
    report_list = tmp_path / "reports.txt"
    report_list.write_text(f"\n# comment\n{report}\n{report}\n", encoding="utf-8")

    paths = discover_report_paths([report], [report])
    summary = build_phase2_batch_summary(paths)

    assert [str(path) for path in paths] == [str(report)]
    assert summary.report_count == 1
    assert (
        main(
            [
                "phase2-summarize-runs",
                "--report-list",
                str(report_list),
                "--output-json",
                str(tmp_path / "s.json"),
                "--output-md",
                str(tmp_path / "s.md"),
            ]
        )
        == 0
    )


def test_phase2_summarize_runs_rejects_empty_input(tmp_path):
    with pytest.raises(ValueError, match="at least one --report or --root is required"):
        main(["phase2-summarize-runs", "--root", str(tmp_path)])


def test_phase2_summarize_runs_reports_malformed_json(tmp_path):
    bad = tmp_path / "bad" / "report.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        main(["phase2-summarize-runs", "--report", str(bad), "--output-json", str(tmp_path / "s.json")])


def test_phase2_summarize_runs_rejects_missing_required_fields(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"report": {"trade_count": 1}, "trades": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="report is missing required fields"):
        main(["phase2-summarize-runs", "--report", str(report), "--output-json", str(tmp_path / "s.json")])


def test_phase2_summarize_runs_handles_zero_trade_reports(tmp_path):
    report = tmp_path / "report.json"
    _write_report(report, symbols=["A000020"], inserted_rows=100, trade_count=0, net_pnl="0")

    summary = build_phase2_batch_summary([report])

    assert summary.report_count == 1
    assert summary.total_trade_count == 0
    assert summary.continuity_status == "passed"


def test_phase2_summarize_runs_flags_continuity_failures(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=2,
        net_pnl="7.25",
        valid_trades=1,
        invalid_trades=1,
        reason="day-end",
    )

    summary = build_phase2_batch_summary([report])

    assert summary.continuity_status == "review-required"
    assert summary.optimization_gate_status == "blocked"
    assert summary.invalid_trade_ratio == "0.5"
    assert summary.invalid_net_pnl_ratio == str(Decimal("3.25") / Decimal("7.25"))
    assert summary.total_valid_trades == 1
    assert summary.total_invalid_trades == 1
    assert summary.total_invalid_net_pnl == "-3.25"
    assert summary.exit_reasons == {"day-end": 2}


def test_phase2_summarize_runs_formats_small_invalid_net_pnl_ratio_without_scientific_notation(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=1,
        net_pnl="1000000",
        valid_trades=0,
        invalid_trades=1,
        invalid_net_pnl="-0.001",
    )

    summary = build_phase2_batch_summary([report])

    assert summary.invalid_net_pnl_ratio == "0.000000001"


def test_phase2_summarize_runs_uses_actual_small_total_net_pnl_as_ratio_denominator(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=1,
        net_pnl="0.5",
        valid_trades=0,
        invalid_trades=1,
        invalid_net_pnl="-0.25",
    )

    summary = build_phase2_batch_summary([report])

    assert summary.invalid_net_pnl_ratio == "0.5"


def test_phase2_summarize_runs_flags_failed_continuity_status_even_without_invalid_count(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=1,
        net_pnl="1",
        invalid_trades=0,
        continuity_status="failed",
    )

    summary = build_phase2_batch_summary([report])

    assert summary.total_invalid_trades == 0
    assert summary.continuity_status == "review-required"


def test_phase2_summarize_runs_blocks_ambiguous_intrabar_trades(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=2,
        net_pnl="2",
        ambiguous_intrabar=True,
    )

    summary = build_phase2_batch_summary([report])

    assert summary.total_ambiguous_intrabar_trades == 2
    assert summary.ambiguous_intrabar_ratio == "1"
    assert summary.continuity_status == "review-required"
    assert summary.optimization_gate_status == "blocked"


def test_phase2_summarize_runs_cli_succeeds_when_summary_requires_review(tmp_path):
    report = tmp_path / "report.json"
    _write_report(
        report,
        symbols=["A000020"],
        inserted_rows=100,
        trade_count=1,
        net_pnl="-1",
        valid_trades=0,
        invalid_trades=1,
    )
    output_json = tmp_path / "summary.json"

    exit_code = main(
        [
            "phase2-summarize-runs",
            "--report",
            str(report),
            "--output-json",
            str(output_json),
            "--output-md",
            str(tmp_path / "summary.md"),
        ]
    )

    assert exit_code == 0
    assert json.loads(output_json.read_text(encoding="utf-8"))["continuity_status"] == "review-required"
