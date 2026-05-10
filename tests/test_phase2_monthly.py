from __future__ import annotations

import json
from pathlib import Path

import pytest

from zurini.cli import main
from zurini.phase2 import build_monthly_rehearsal_plan, read_path_list


def _write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,time,open,high,low,close,volume\n"
        "20260102,901,100,101,99,100,10\n",
        encoding="utf-8",
    )


def _write_coverage_report(path: Path, *, csv_path: Path, accepted: bool, missing_days: list[str] | None = None) -> None:
    missing_days = missing_days or []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "acceptance_status": "accepted" if accepted else "review-required",
                "calendar_version": "krx-korean-equity-v1",
                "calendar_certified": False,
                "day_set_evaluated": accepted,
                "day_set_complete": accepted,
                "missing_trading_days": missing_days,
                "expected_trading_days": 20,
                "observed_trading_days": 20 - len(missing_days),
                "results": [
                    {
                        "path": str(csv_path),
                        "status": "accepted" if accepted else "review-required",
                        "day_set_evaluated": accepted,
                        "day_set_complete": accepted,
                        "missing_trading_days": missing_days,
                        "expected_trading_days": 20,
                        "observed_trading_days": 20 - len(missing_days),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_multi_coverage_report(path: Path, *, results: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "acceptance_status": "review-required",
                "calendar_version": "krx-korean-equity-v1",
                "calendar_certified": False,
                "day_set_evaluated": False,
                "day_set_complete": False,
                "missing_trading_days": ["2099-01-01"],
                "expected_trading_days": 40,
                "observed_trading_days": 39,
                "results": results,
            }
        ),
        encoding="utf-8",
    )


def test_monthly_plan_selects_completed_months_and_common_symbols(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602", "202603"]:
        _write_csv(root / period / "A111111.csv")
    _write_csv(root / "202601" / "A222222.csv")
    _write_csv(root / "202603" / "A222222.csv")

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports",
        current_yyyymm="202603",
        limit_symbols=10,
    )

    assert plan.selected_months == ["202601", "202602"]
    assert plan.excluded_months == ["202603"]
    assert plan.selected_symbols == ["A111111"]
    assert plan.path_list == [
        str(root / "202601" / "A111111.csv"),
        str(root / "202602" / "A111111.csv"),
    ]
    assert "--path-list" in plan.recommended_command
    assert "--trade-continuity-mode" in plan.recommended_command
    assert "exact-bar" in plan.recommended_command


def test_monthly_plan_can_restrict_requested_months(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202512", "202601", "202602"]:
        _write_csv(root / period / "A111111.csv")

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports",
        current_yyyymm="202603",
        requested_months=["202601", "202602"],
    )

    assert plan.selected_months == ["202601", "202602"]
    assert plan.excluded_months == ["202512"]


def test_monthly_plan_rejects_missing_requested_month(tmp_path):
    root = tmp_path / "minute-bars"
    _write_csv(root / "202601" / "A111111.csv")

    with pytest.raises(ValueError, match="requested months are missing"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202604"],
        )


def test_monthly_plan_rejects_requested_current_month(tmp_path):
    root = tmp_path / "minute-bars"
    _write_csv(root / "202602" / "A111111.csv")
    _write_csv(root / "202603" / "A111111.csv")

    with pytest.raises(ValueError, match="requested months are not completed candidates"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202603"],
        )


def test_monthly_plan_rejects_non_contiguous_requested_months(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602", "202603"]:
        _write_csv(root / period / "A111111.csv")

    with pytest.raises(ValueError, match="requested months must be contiguous"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202604",
            requested_months=["202601", "202603"],
        )


def test_monthly_plan_defaults_to_latest_contiguous_completed_range(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202501", "202503", "202504", "202505"]:
        _write_csv(root / period / "A111111.csv")

    plan = build_monthly_rehearsal_plan(root, output_dir=tmp_path / "reports", current_yyyymm="202506")

    assert plan.selected_months == ["202503", "202504", "202505"]
    assert plan.excluded_months == ["202501"]


def test_monthly_plan_treats_empty_month_as_not_completed(tmp_path):
    root = tmp_path / "minute-bars"
    (root / "202601").mkdir(parents=True)
    _write_csv(root / "202602" / "A111111.csv")

    plan = build_monthly_rehearsal_plan(root, output_dir=tmp_path / "reports", current_yyyymm="202603")

    assert plan.selected_months == ["202602"]
    assert plan.excluded_months == ["202601"]
    assert [month.status for month in plan.months if month.period == "202601"] == ["empty"]


def test_monthly_plan_uses_coverage_report_to_gate_completed_months(tmp_path):
    root = tmp_path / "minute-bars"
    accepted_csv = root / "202601" / "A111111.csv"
    rejected_csv = root / "202602" / "A111111.csv"
    _write_csv(accepted_csv)
    _write_csv(rejected_csv)
    accepted_report = tmp_path / "reports" / "coverage-202601.json"
    rejected_report = tmp_path / "reports" / "coverage-202602.json"
    _write_coverage_report(accepted_report, csv_path=accepted_csv, accepted=True)
    _write_coverage_report(rejected_report, csv_path=rejected_csv, accepted=False, missing_days=["2026-02-03"])

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports" / "monthly",
        current_yyyymm="202603",
        coverage_reports=[accepted_report, rejected_report],
    )

    assert plan.selected_months == ["202601"]
    assert [month.status for month in plan.months if month.period == "202602"] == ["incomplete-dayset"]
    assert plan.months[1].missing_trading_days == ["2026-02-03"]


def test_monthly_plan_merges_same_period_coverage_reports_conservatively(tmp_path):
    root = tmp_path / "minute-bars"
    csv_path = root / "202601" / "A111111.csv"
    _write_csv(csv_path)
    rejected_report = tmp_path / "reports" / "coverage-202601-rejected.json"
    accepted_report = tmp_path / "reports" / "coverage-202601-accepted.json"
    _write_coverage_report(rejected_report, csv_path=csv_path, accepted=False, missing_days=["2026-01-05"])
    _write_coverage_report(accepted_report, csv_path=csv_path, accepted=True)

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports" / "monthly",
        current_yyyymm="202602",
        coverage_reports=[rejected_report, accepted_report],
    )

    assert plan.selected_months == []
    assert plan.months[0].status == "incomplete-dayset"
    assert plan.months[0].missing_trading_days == ["2026-01-05"]
    assert str(rejected_report) in plan.months[0].coverage_report
    assert str(accepted_report) in plan.months[0].coverage_report


def test_monthly_plan_does_not_bypass_gate_for_empty_coverage_report(tmp_path):
    root = tmp_path / "minute-bars"
    _write_csv(root / "202601" / "A111111.csv")
    coverage_report = tmp_path / "reports" / "coverage-empty.json"
    coverage_report.parent.mkdir(parents=True, exist_ok=True)
    coverage_report.write_text('{"results": []}\n', encoding="utf-8")

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports" / "monthly",
        current_yyyymm="202602",
        coverage_reports=[coverage_report],
    )

    assert plan.selected_months == []
    assert plan.months[0].status == "incomplete-dayset"
    assert plan.months[0].coverage_status == "missing"


def test_monthly_plan_keeps_multi_period_coverage_metrics_separate(tmp_path):
    root = tmp_path / "minute-bars"
    accepted_csv = root / "202601" / "A111111.csv"
    rejected_csv = root / "202602" / "A111111.csv"
    _write_csv(accepted_csv)
    _write_csv(rejected_csv)
    coverage_report = tmp_path / "reports" / "coverage-combined.json"
    _write_multi_coverage_report(
        coverage_report,
        results=[
            {
                "path": str(accepted_csv),
                "status": "accepted",
                "day_set_evaluated": True,
                "day_set_complete": True,
                "missing_trading_days": [],
                "expected_trading_days": 20,
                "observed_trading_days": 20,
            },
            {
                "path": str(rejected_csv),
                "status": "review-required",
                "day_set_evaluated": True,
                "day_set_complete": False,
                "missing_trading_days": ["2026-02-03"],
                "expected_trading_days": 20,
                "observed_trading_days": 19,
            },
        ],
    )

    plan = build_monthly_rehearsal_plan(
        root,
        output_dir=tmp_path / "reports" / "monthly",
        current_yyyymm="202603",
        coverage_reports=[coverage_report],
    )

    assert plan.months[0].status == "completed-candidate"
    assert plan.months[0].missing_trading_days == []
    assert plan.months[1].status == "incomplete-dayset"
    assert plan.months[1].missing_trading_days == ["2026-02-03"]


def test_monthly_plan_rejects_requested_empty_month(tmp_path):
    root = tmp_path / "minute-bars"
    (root / "202601").mkdir(parents=True)

    with pytest.raises(ValueError, match="requested months are not completed candidates"):
        build_monthly_rehearsal_plan(
            root,
            output_dir=tmp_path / "reports",
            current_yyyymm="202603",
            requested_months=["202601"],
        )


def test_read_path_list_ignores_blank_lines_and_comments(tmp_path):
    path_list = tmp_path / "paths.txt"
    path_list.write_text("\n# comment\nsample/A000020.csv\n\n", encoding="utf-8")

    assert read_path_list(path_list) == [Path("sample/A000020.csv")]


def test_phase2_monthly_plan_cli_writes_plan_and_path_list(tmp_path):
    root = tmp_path / "minute-bars"
    for period in ["202601", "202602"]:
        _write_csv(root / period / "A111111.csv")
    output_dir = tmp_path / "reports"

    exit_code = main(
        [
            "phase2-monthly-plan",
            "--root",
            str(root),
            "--output-dir",
            str(output_dir),
            "--current-yyyymm",
            "202603",
        ]
    )

    assert exit_code == 0
    plan = json.loads((output_dir / "monthly-plan.json").read_text(encoding="utf-8"))
    paths = (output_dir / "backtest-paths.txt").read_text(encoding="utf-8").splitlines()
    assert plan["selected_months"] == ["202601", "202602"]
    assert plan["selected_symbols"] == ["A111111"]
    assert paths == [
        str(root / "202601" / "A111111.csv"),
        str(root / "202602" / "A111111.csv"),
    ]


def test_phase2_monthly_plan_cli_accepts_coverage_reports(tmp_path):
    root = tmp_path / "minute-bars"
    csv_path = root / "202601" / "A111111.csv"
    _write_csv(csv_path)
    coverage_report = tmp_path / "coverage-202601.json"
    _write_coverage_report(coverage_report, csv_path=csv_path, accepted=True)
    output_dir = tmp_path / "reports"

    exit_code = main(
        [
            "phase2-monthly-plan",
            "--root",
            str(root),
            "--output-dir",
            str(output_dir),
            "--current-yyyymm",
            "202602",
            "--coverage-report",
            str(coverage_report),
        ]
    )

    assert exit_code == 0
    plan = json.loads((output_dir / "monthly-plan.json").read_text(encoding="utf-8"))
    assert plan["coverage_reports"] == [str(coverage_report)]
    assert plan["months"][0]["coverage_status"] == "accepted"
